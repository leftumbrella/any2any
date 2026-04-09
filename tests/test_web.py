"""Tests for URL → file conversion."""

from __future__ import annotations

import http.server
import io
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import any2any.converters.web as web_module
import pytest
from PIL import Image

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
    assert selector == ".instagram-media-rendered"


def test_instagram_reel_embed() -> None:
    result = _social_embed("https://www.instagram.com/reel/XYZ789/")
    assert result is not None
    assert "XYZ789" in result[0]


def test_instagram_with_query_params() -> None:
    url = "https://www.instagram.com/p/DWx59MNDNCO/?utm_source=ig_web_copy_link&igsh=abc"
    result = _social_embed(url)
    assert result is not None
    assert "DWx59MNDNCO" in result[0]


def test_instagram_embed_uses_wider_viewport() -> None:
    assert web_module._embed_viewport("https://www.instagram.com/p/ABC123/embed/") == {
        "width": 1200,
        "height": 1200,
    }


def test_twitter_embed_uses_wider_viewport() -> None:
    assert web_module._embed_viewport(
        "https://platform.twitter.com/embed/Tweet.html?id=123",
    ) == {
        "width": 1200,
        "height": 1200,
    }


def test_other_embed_uses_default_viewport() -> None:
    assert web_module._embed_viewport(
        "https://www.tiktok.com/embed/v2/7000000000000",
    ) == {
        "width": 550,
        "height": 800,
    }


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


class _FakePage:
    def __init__(self, width: int, height: int, total_height: int) -> None:
        self.viewport_size = {"width": width, "height": height}
        self.total_height = total_height
        self.full_page_calls = 0
        self.normal_calls = 0
        self.resize_calls: list[dict[str, int]] = []
        self.evaluate_calls: list[str] = []

    def screenshot(self, *, full_page: bool = False) -> bytes:
        if full_page:
            self.full_page_calls += 1
            img = Image.new("RGBA", (self.viewport_size["width"], self.total_height), "white")
        else:
            self.normal_calls += 1
            img = Image.new("RGBA", (self.viewport_size["width"], self.viewport_size["height"]), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def set_viewport_size(self, viewport: dict[str, int]) -> None:
        self.resize_calls.append(viewport)
        self.viewport_size = viewport

    def evaluate(self, script: str) -> None:
        self.evaluate_calls.append(script)


def test_capture_page_png_uses_native_full_page_for_short_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage(width=20, height=200, total_height=210)

    monkeypatch.setattr(web_module, "_page_height", lambda _page: 210)
    monkeypatch.setattr(
        web_module,
        "_wait_for_paint",
        lambda *_args: pytest.fail("short pages should not resize viewport"),
    )

    png = web_module._capture_page_png(page)
    img = Image.open(io.BytesIO(png))

    assert page.full_page_calls == 1
    assert page.normal_calls == 0
    assert page.resize_calls == []
    assert img.size == (20, 210)


def test_capture_page_png_resizes_viewport_for_long_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage(width=12, height=200, total_height=450)
    monkeypatch.setattr(web_module, "_page_height", lambda _page: 450)
    wait_calls: list[str] = []
    monkeypatch.setattr(
        web_module,
        "_wait_for_paint",
        lambda _page: wait_calls.append("paint"),
    )

    png = web_module._capture_page_png(page)
    img = Image.open(io.BytesIO(png))

    assert page.full_page_calls == 0
    assert page.normal_calls == 1
    assert page.resize_calls == [{"width": 12, "height": 450}]
    assert page.evaluate_calls == ["window.scrollTo(0, 0)"]
    assert wait_calls == ["paint"]
    assert img.size == (12, 450)


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
