"""Unit tests for BrowserUseGateway title heuristics (FR-19, FR-20)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.agent.browser import BrowserUseGateway


def _state(title: str, url: str, dom_state=None):
    return SimpleNamespace(title=title, url=url, dom_state=dom_state)


@pytest.mark.asyncio
async def test_observe_keeps_site_name_title(monkeypatch):
    """A title like 'Wikipedia' matching the site name is a real title; keep it."""
    async def fail_if_slept(_seconds):
        raise AssertionError("Title retry should not run for a real site-name title")

    monkeypatch.setattr(asyncio, "sleep", fail_if_slept)

    gateway = BrowserUseGateway()
    gateway.session = SimpleNamespace(
        get_browser_state_summary=AsyncMock(
            return_value=_state("Wikipedia", "https://en.wikipedia.org"),
        ),
        get_current_page_title=AsyncMock(return_value="should-not-be-called"),
    )

    obs = await gateway.observe()
    assert obs.title == "Wikipedia"
    assert obs.url == "https://en.wikipedia.org"
    gateway.session.get_current_page_title.assert_not_called()


@pytest.mark.asyncio
async def test_observe_retries_hostname_title(monkeypatch):
    """A title equal to the full hostname including a dot is URL-like and is retried."""
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    gateway = BrowserUseGateway()
    gateway.session = SimpleNamespace(
        get_browser_state_summary=AsyncMock(
            return_value=_state("en.wikipedia.org", "https://en.wikipedia.org/wiki/Main_Page"),
        ),
        get_current_page_title=AsyncMock(
            side_effect=["en.wikipedia.org", "en.wikipedia.org", "Wikipedia"],
        ),
    )

    obs = await gateway.observe()
    assert obs.title == "Wikipedia"
    assert gateway.session.get_current_page_title.await_count == 3


@pytest.mark.asyncio
async def test_observe_retries_scheme_and_path_titles(monkeypatch):
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    gateway = BrowserUseGateway()
    gateway.session = SimpleNamespace(
        get_browser_state_summary=AsyncMock(
            return_value=_state("https://example.com/page", "https://example.com/page"),
        ),
        get_current_page_title=AsyncMock(return_value="Example Domain"),
    )

    obs = await gateway.observe()
    assert obs.title == "Example Domain"


@pytest.mark.asyncio
async def test_observe_clears_title_if_retry_stays_url_like(monkeypatch):
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    gateway = BrowserUseGateway()
    gateway.session = SimpleNamespace(
        get_browser_state_summary=AsyncMock(
            return_value=_state("/wiki/Main_Page", "https://en.wikipedia.org/wiki/Main_Page"),
        ),
        get_current_page_title=AsyncMock(return_value="en.wikipedia.org"),
    )

    obs = await gateway.observe()
    assert obs.title == ""
    assert gateway.session.get_current_page_title.await_count == 4


def _tiny_jpeg() -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.new("RGB", (1600, 400), color=(20, 40, 80))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_capture_skips_screenshot_when_password_filled(monkeypatch):
    """NFR-SEC-07: filled password fields suppress the screenshot and mask secrets."""
    jpeg = _tiny_jpeg()
    gateway = BrowserUseGateway()
    gateway.session = SimpleNamespace(
        get_current_page_url=AsyncMock(return_value="https://example.com/login"),
        get_current_page_title=AsyncMock(return_value="Sign in"),
        take_screenshot=AsyncMock(return_value=jpeg),
        get_or_create_cdp_session=AsyncMock(),
    )

    async def fake_dom(_self):
        return {
            "headings": ["Sign in"],
            "landmarks": ["main", "form"],
            "link_count": 2,
            "button_count": 1,
            "field_count": 2,
            "password_values": ["hunter2"],
            "has_filled_password": True,
        }

    async def fake_markdown(**_kwargs):
        return ("Password is hunter2 on this form.", {})

    monkeypatch.setattr(BrowserUseGateway, "_collect_perception_dom", fake_dom)

    import types
    import sys

    fake_mod = types.ModuleType("browser_use.dom.markdown_extractor")
    fake_mod.extract_clean_markdown = fake_markdown
    monkeypatch.setitem(sys.modules, "browser_use.dom.markdown_extractor", fake_mod)

    capture = await gateway.capture_for_perception()
    assert capture.has_filled_password is True
    assert capture.screenshot_png is None
    gateway.session.take_screenshot.assert_not_called()
    assert "hunter2" not in capture.main_text
    assert "********" in capture.main_text


def test_resize_screenshot_jpeg_caps_width():
    from core.agent.browser import resize_screenshot_jpeg
    from PIL import Image
    from io import BytesIO

    raw = _tiny_jpeg()
    out = resize_screenshot_jpeg(raw, max_width=1280, quality=70)
    image = Image.open(BytesIO(out))
    assert image.width <= 1280
    assert image.format == "JPEG"


def test_headings_from_markdown_h1_h3_only():
    from core.agent.browser import headings_from_markdown

    text = "# Title\n\n## Section\n\n### Detail\n\n#### Too deep\nplain"
    assert headings_from_markdown(text) == ["Title", "Section", "Detail"]
