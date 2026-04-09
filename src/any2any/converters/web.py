"""Web page converter: URL → image / PDF / HTML / TXT / SVG.

Renders web pages using Playwright's headless Chromium.  The browser
binary is auto-installed on first use so users never need to run a
separate setup step.

Social-media post URLs are detected automatically and rendered as
clean embed cards (for image outputs) instead of full-page screenshots.
"""

from __future__ import annotations

import base64
import io
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from any2any.converters import (
    ImageData,
    register_direct_converter,
    write_image,
    writable_extensions,
)

# ── constants ───────────────────────────────────────────────────────────

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# CSS injected on full-page renders to hide login walls / cookie banners.
_CLEANUP_CSS = """
/* Twitter / X */
[data-testid="sheetDialog"], [data-testid="bottomBar"],
[data-testid="LoginForm"],
div[aria-label="Sign up"] ~ div[role="dialog"],
/* Instagram */
div[role="dialog"]:has(input[name="username"]),
div[role="presentation"]:has(input[name="username"]),
/* Generic cookie / consent banners */
[class*="cookie-banner" i], [class*="cookie-consent" i],
[id*="cookie-banner" i], [id*="cookie-consent" i],
[class*="CookieBanner" i], [id*="CookieBanner" i],
div[class*="BottomBar" i]
{ display: none !important; visibility: hidden !important; }
html, body {
    overflow: visible !important;
    position: static !important;
}
"""

# ── social-media embed detection ────────────────────────────────────────


def _social_embed(url: str) -> tuple[str, str | None] | None:
    """Detect a social-media post URL.

    Returns ``(embed_url, card_css_selector)`` when matched, or *None*.
    *card_css_selector* is used to screenshot only the card element;
    pass *None* to screenshot the entire embed page.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path

    # Twitter / X
    if host in (
        "twitter.com", "www.twitter.com",
        "x.com", "www.x.com",
        "mobile.twitter.com", "mobile.x.com",
    ):
        m = re.search(r"/status/(\d+)", path)
        if m:
            return (
                f"https://platform.twitter.com/embed/Tweet.html?id={m.group(1)}",
                "article",
            )

    # Instagram  (posts and reels)
    if host in ("instagram.com", "www.instagram.com"):
        m = re.search(r"/(p|reel)/([^/?#]+)", path)
        if m:
            return (
                f"https://www.instagram.com/p/{m.group(2)}/embed/",
                None,
            )

    # TikTok
    if host in ("tiktok.com", "www.tiktok.com"):
        m = re.search(r"/video/(\d+)", path)
        if m:
            return (
                f"https://www.tiktok.com/embed/v2/{m.group(1)}",
                None,
            )

    return None


# ── browser lifecycle ───────────────────────────────────────────────────

_browser_ready = False


def _ensure_browser() -> None:
    """Download Playwright's Chromium (one-time, ~180 MB)."""
    print(
        "any2any: downloading Chromium (first run only, ~180 MB)...",
        file=sys.stderr,
        flush=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "failed to install Chromium — "
            "run 'python -m playwright install chromium' manually"
        )
    print("any2any: Chromium ready.", file=sys.stderr)


def _launch_browser():
    """Launch Chromium, auto-installing on first run.

    Returns ``(playwright_instance, browser)``.
    """
    global _browser_ready
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()

    if not _browser_ready:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pw.stop()
            _ensure_browser()
            pw = sync_playwright().start()
            browser = pw.chromium.launch()
        _browser_ready = True
    else:
        browser = pw.chromium.launch()

    return pw, browser


# ── page rendering ──────────────────────────────────────────────────────


def _render(url: str):
    """Full-page render.  Returns *(pw, browser, page)*.

    Used for non-social URLs and for PDF / HTML / TXT outputs.
    """
    pw, browser = _launch_browser()

    page = browser.new_page(
        viewport={"width": 1920, "height": 1080},
        user_agent=_DESKTOP_UA,
    )

    page.goto(url, wait_until="load", timeout=60_000)

    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    page.add_style_tag(content=_CLEANUP_CSS)
    page.wait_for_timeout(2_000)

    return pw, browser, page


def _screenshot_url(url: str) -> bytes:
    """Return PNG bytes: embed card for social-media posts, full page otherwise."""
    embed = _social_embed(url)

    if embed is not None:
        return _screenshot_embed(*embed)

    # Generic full-page screenshot.
    pw, browser, page = _render(url)
    try:
        return page.screenshot(full_page=True)
    finally:
        browser.close()
        pw.stop()


_EMBED_CLEANUP_JS: dict[str, str] = {
    "instagram.com": """
        // Walk the DOM and hide elements containing "Add a comment"
        // and login prompts — Instagram's embed uses plain divs, not
        // <form> or <input>, so CSS selectors cannot target them.
        (function() {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT);
            const targets = [];
            while (walker.nextNode()) {
                const t = walker.currentNode.textContent.trim();
                if (t === 'Add a comment\u2026' || t === 'Add a comment...') {
                    targets.push(walker.currentNode);
                }
                if (t.startsWith('Log in') || t.startsWith('Sign up')) {
                    targets.push(walker.currentNode);
                }
            }
            for (const node of targets) {
                // Walk up to find a meaningful container and hide it.
                let el = node.parentElement;
                while (el && el !== document.body &&
                       el.offsetHeight < 5) {
                    el = el.parentElement;
                }
                if (el && el !== document.body) {
                    el.style.display = 'none';
                }
            }
        })();
    """,
}


def _screenshot_embed(embed_url: str, card_selector: str | None) -> bytes:
    """Render an embed page and return the card as PNG bytes."""
    pw, browser = _launch_browser()

    page = browser.new_page(
        viewport={"width": 550, "height": 800},
        user_agent=_DESKTOP_UA,
    )

    try:
        page.goto(embed_url, wait_until="load", timeout=60_000)

        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        # Extra time for images / iframes inside the embed.
        page.wait_for_timeout(3_000)

        # Platform-specific cleanup (e.g. hide Instagram comment input).
        for domain, js in _EMBED_CLEANUP_JS.items():
            if domain in embed_url:
                page.evaluate(js)
                page.wait_for_timeout(200)
                break

        # Try to screenshot just the card element.
        if card_selector:
            el = page.query_selector(card_selector)
            if el:
                return el.screenshot()

        return page.screenshot(full_page=True)
    finally:
        browser.close()
        pw.stop()


# ── converters ──────────────────────────────────────────────────────────


def _convert_url_to_image(url: str, out_path: Path) -> None:
    """Screenshot the page (card for social media) and save as image."""
    from PIL import Image

    png_bytes = _screenshot_url(url)
    img = Image.open(io.BytesIO(png_bytes))
    data = ImageData(frames=[img], metadata={})
    write_image(data, out_path)


def _convert_url_to_pdf(url: str, out_path: Path) -> None:
    """Print the page to PDF using the browser's native PDF renderer."""
    pw, browser, page = _render(url)
    try:
        page.pdf(path=str(out_path), format="A4", print_background=True)
    finally:
        browser.close()
        pw.stop()


def _convert_url_to_html(url: str, out_path: Path) -> None:
    """Save the fully-rendered HTML source (after JS execution)."""
    pw, browser, page = _render(url)
    try:
        html = page.content()
    finally:
        browser.close()
        pw.stop()

    out_path.write_text(html, encoding="utf-8")


def _convert_url_to_txt(url: str, out_path: Path) -> None:
    """Extract visible text from the page body."""
    pw, browser, page = _render(url)
    try:
        text = page.inner_text("body")
    finally:
        browser.close()
        pw.stop()

    out_path.write_text(text, encoding="utf-8")


def _convert_url_to_svg(url: str, out_path: Path) -> None:
    """Screenshot the page (card for social media) and embed in SVG."""
    from PIL import Image

    png_bytes = _screenshot_url(url)
    img = Image.open(io.BytesIO(png_bytes))
    w, h = img.size
    b64 = base64.b64encode(png_bytes).decode("ascii")

    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
        f'  <image width="{w}" height="{h}" '
        f'href="data:image/png;base64,{b64}"/>\n'
        '</svg>\n'
    )

    out_path.write_text(svg, encoding="utf-8")


# ── registration ────────────────────────────────────────────────────────

# URL → all writable image formats (screenshot path).
for _ext in writable_extensions():
    register_direct_converter("url", _ext, _convert_url_to_image)

# URL → PDF (Playwright native — much better than screenshot-as-PDF).
register_direct_converter("url", "pdf", _convert_url_to_pdf)

# URL → HTML source.
register_direct_converter("url", "html", _convert_url_to_html)
register_direct_converter("url", "htm", _convert_url_to_html)

# URL → plain text.
register_direct_converter("url", "txt", _convert_url_to_txt)

# URL → SVG (embedded screenshot).
register_direct_converter("url", "svg", _convert_url_to_svg)
