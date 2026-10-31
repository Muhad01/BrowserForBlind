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
