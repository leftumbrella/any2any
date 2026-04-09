"""Tests for URL → file conversion."""

from __future__ import annotations

import http.server
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from any2any.cli import _is_url, main
from any2any.converters import can_convert, has_direct
from any2any.converters.web import _social_embed


# ── URL detection ───────────────────────────────────────────────────────


def test_is_url_http() -> None:
    assert _is_url("http://example.com")


def test_is_url_https() -> None:
    assert _is_url("https://example.com/page?q=1")


def test_is_url_rejects_file_path() -> None:
    assert not _is_url("/tmp/file.png")
    assert not _is_url("file.png")
    assert not _is_url("C:\\Users\\file.png")


# ── converter registry ──────────────────────────────────────────────────


def test_can_convert_url_to_png() -> None:
    assert can_convert("url", "png")


def test_can_convert_url_to_jpg() -> None:
    assert can_convert("url", "jpg")


def test_can_convert_url_to_webp() -> None:
    assert can_convert("url", "webp")


def test_can_convert_url_to_pdf() -> None:
    assert can_convert("url", "pdf")


def test_can_convert_url_to_html() -> None:
    assert can_convert("url", "html")


def test_can_convert_url_to_txt() -> None:
    assert can_convert("url", "txt")


def test_can_convert_url_to_svg() -> None:
    assert can_convert("url", "svg")


def test_has_direct_url() -> None:
    assert has_direct("url", "png")
    assert has_direct("url", "pdf")
    assert has_direct("url", "html")
    assert has_direct("url", "txt")
    assert has_direct("url", "svg")


def test_no_direct_for_file() -> None:
    assert not has_direct("png", "jpg")


# ── social-media embed detection ────────────────────────────────────────


def test_twitter_embed() -> None:
    result = _social_embed("https://x.com/user/status/123456789")
    assert result is not None
    embed_url, selector = result
    assert "123456789" in embed_url
    assert "platform.twitter.com" in embed_url
    assert selector == "article"


def test_twitter_www_embed() -> None:
    result = _social_embed("https://www.twitter.com/user/status/99999")
    assert result is not None
    assert "99999" in result[0]


def test_instagram_post_embed() -> None:
    result = _social_embed("https://www.instagram.com/p/ABC123/")
    assert result is not None
    embed_url, selector = result
    assert "ABC123" in embed_url
    assert "/embed/" in embed_url
    assert selector is None


def test_instagram_reel_embed() -> None:
    result = _social_embed("https://www.instagram.com/reel/XYZ789/")
    assert result is not None
    assert "XYZ789" in result[0]


def test_instagram_with_query_params() -> None:
    url = "https://www.instagram.com/p/DWx59MNDNCO/?utm_source=ig_web_copy_link&igsh=abc"
    result = _social_embed(url)
    assert result is not None
    assert "DWx59MNDNCO" in result[0]


def test_tiktok_embed() -> None:
    result = _social_embed("https://www.tiktok.com/@user/video/7000000000000")
    assert result is not None
    assert "7000000000000" in result[0]
    assert "/embed/" in result[0]


def test_non_social_url_returns_none() -> None:
    assert _social_embed("https://example.com/page") is None
    assert _social_embed("https://google.com") is None


def test_social_homepage_not_matched() -> None:
    """Profile pages (no post ID) should not be treated as embeds."""
    assert _social_embed("https://x.com/user") is None
    assert _social_embed("https://www.instagram.com/user/") is None


# ── CLI error paths (no browser needed) ─────────────────────────────────


def test_url_no_output_extension(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["https://example.com", "noext"]) == 1
    assert "no extension" in capsys.readouterr().err


def test_url_unsupported_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["https://example.com", "out.xyz"]) == 1
    assert "no converter" in capsys.readouterr().err


def test_url_multi_frame_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """Multi-frame output patterns make no sense for URLs."""
    with patch("any2any.converters.web._render") as mock_render:
        assert main(["https://example.com", "*.png"]) == 1
        assert "not supported" in capsys.readouterr().err
        mock_render.assert_not_called()


# ── integration tests (require Playwright + Chromium) ───────────────────

_SAMPLE_HTML = """\
<!DOCTYPE html>
<html><head><title>Test Page</title></head>
<body><h1>Hello any2any</h1><p>Visible text here.</p></body>
</html>
"""


@pytest.fixture(scope="module")
def local_server():
    """Spin up a tiny HTTP server serving a single test page."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_SAMPLE_HTML.encode())

        def log_message(self, *_args: object) -> None:
            pass  # silence request logs

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch()
            browser.close()
            return True
        except Exception:
            return False
        finally:
            pw.stop()
    except Exception:
        return False


_need_playwright = pytest.mark.skipif(
    not _playwright_available(),
    reason="Playwright Chromium not available",
)


@_need_playwright
def test_url_to_png(local_server: str, tmp_path: Path) -> None:
    out = tmp_path / "page.png"
    assert main([local_server, str(out)]) == 0
    assert out.exists()
    assert out.stat().st_size > 100


@_need_playwright
def test_url_to_jpg(local_server: str, tmp_path: Path) -> None:
    out = tmp_path / "page.jpg"
    assert main([local_server, str(out)]) == 0
    assert out.exists()
    assert out.stat().st_size > 100


@_need_playwright
def test_url_to_pdf(local_server: str, tmp_path: Path) -> None:
    out = tmp_path / "page.pdf"
    assert main([local_server, str(out)]) == 0
    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


@_need_playwright
def test_url_to_html(local_server: str, tmp_path: Path) -> None:
    out = tmp_path / "page.html"
    assert main([local_server, str(out)]) == 0
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Hello any2any" in content


@_need_playwright
def test_url_to_txt(local_server: str, tmp_path: Path) -> None:
    out = tmp_path / "page.txt"
    assert main([local_server, str(out)]) == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Hello any2any" in text
    assert "Visible text here" in text
    # Should not contain HTML tags.
    assert "<h1>" not in text


@_need_playwright
def test_url_to_svg(local_server: str, tmp_path: Path) -> None:
    out = tmp_path / "page.svg"
    assert main([local_server, str(out)]) == 0
    assert out.exists()
    svg = out.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "data:image/png;base64," in svg


@_need_playwright
def test_url_stderr_message(
    local_server: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "page.png"
    assert main([local_server, str(out)]) == 0
    err = capsys.readouterr().err
    assert "->" in err
    assert "page.png" in err
