"""Browser automation gateway interfacing with Chromium and Playwright (FR-10, FR-17)."""
import asyncio
import io
import re
import time
from pathlib import Path
from typing import Any, Protocol

import structlog
from django.conf import settings

from core.agent.narration import compute_accessible_name, compute_role, is_url_like
from core.agent.schema import (
    ElementMeta,
    ExecResult,
    NormalizedAction,
    PageObservation,
    PerceptionCapture,
)
from core.enums import ActionType
from core.errors import ErrorCode

logger = structlog.get_logger(__name__)

MAIN_TEXT_CAP = 30_000
SCREENSHOT_MAX_WIDTH = 1280
SCREENSHOT_JPEG_QUALITY = 70

_PERCEPTION_DOM_JS = """
(() => {
  const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
    .map((el) => (el.innerText || '').trim())
    .filter(Boolean);
  const landmarkFlags = {
    nav: Boolean(document.querySelector('nav, [role="navigation"]')),
    main: Boolean(document.querySelector('main, [role="main"]')),
    search: Boolean(document.querySelector('[role="search"], input[type="search"]')),
    form: Boolean(document.querySelector('form')),
  };
  const passwords = Array.from(document.querySelectorAll('input[type="password"]'))
    .map((el) => el.value || '');
  return {
    headings,
    landmarks: Object.keys(landmarkFlags).filter((key) => landmarkFlags[key]),
    link_count: document.querySelectorAll('a[href]').length,
    button_count: document.querySelectorAll('button, [role="button"], input[type="submit"]').length,
    field_count: document.querySelectorAll('input, select, textarea').length,
    password_values: passwords,
    has_filled_password: passwords.some((value) => value.length > 0),
  };
})()
"""


def resize_screenshot_jpeg(data: bytes, max_width: int = SCREENSHOT_MAX_WIDTH, quality: int = SCREENSHOT_JPEG_QUALITY) -> bytes:
    """Downscale a screenshot to max_width and re-encode as JPEG quality 70."""
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.width > max_width:
        height = max(1, int(image.height * (max_width / image.width)))
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def headings_from_markdown(text: str) -> list[str]:
    """Collect ATX h1–h3 headings from extracted markdown."""
    found: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
        if match:
            found.append(match.group(2).strip())
    return found


def mask_secrets(text: str, secrets: list[str]) -> str:
    masked = text
    for secret in secrets:
        if secret:
            masked = masked.replace(secret, "********")
    return masked


class BrowserGateway(Protocol):
    """Protocol defining the browser abstraction layer."""

    async def start(self, profile_dir: Path) -> None:
        """Initialize and launch the browser session using the given profile directory."""
        ...

    async def observe(self) -> PageObservation:
        """Capture the current page state, indexed DOM elements, and metadata."""
        ...

    async def refresh_title(self, url: str = "") -> str:
        """Retry the page title after a navigation when observe() still returned empty."""
        ...

    async def execute(self, action: NormalizedAction) -> ExecResult:
        """Execute a single normalized browser action in Chromium."""
        ...

    async def close(self) -> None:
        """Safely terminate the browser process and release the profile lock."""
        ...

    async def get_current_page_url(self) -> str:
        """Return the URL of the currently focused page."""
        ...

    async def capture_for_perception(self) -> PerceptionCapture:
        """Capture URL, title, screenshot, and main text for the Perception Agent (FR-26)."""
        ...


class BrowserUseGateway:
    """Production browser gateway wrapping browser-use 0.13.14 primitives.

    Mandates captcha_solver=False (FR-38) and uses persistent browser profiles (FR-52).
    """

    def __init__(self, headless: bool | None = None, action_timeout: int | None = None):
        self.headless = headless if headless is not None else getattr(settings, "BROWSER_HEADLESS", False)
        self.action_timeout = action_timeout or getattr(settings, "ACTION_TIMEOUT_SECONDS", 30)
        self.session = None

    async def start(self, profile_dir: Path) -> None:
        """Start a browser session using browser-use BrowserSession and BrowserProfile."""
        if self.session is not None:
            return
        from browser_use.browser.profile import BrowserProfile
        from browser_use.browser.session import BrowserSession

        profile_dir.mkdir(parents=True, exist_ok=True)
        # FR-38: captcha_solver=False is mandatory per SRS scope
        profile = BrowserProfile(
            user_data_dir=str(profile_dir),
            headless=self.headless,
            captcha_solver=False,
        )
        self.session = BrowserSession(browser_profile=profile)
        await self.session.start()

    async def observe(self) -> PageObservation:
        """Extract DOM elements, indexes, and accessibility tags."""
        if not self.session:
            raise RuntimeError("Browser session has not been started.")

        state = await self.session.get_browser_state_summary(include_screenshot=False)

        url = state.url or "about:blank"
        title = state.title or ""
        if is_url_like(title, url):
            recovered = await self.refresh_title(url)
            title = recovered if recovered else ""

        elements_text = ""
        element_indexes: set[int] = set()
        element_meta: dict[int, ElementMeta] = {}

        if state.dom_state:
            elements_text = state.dom_state.llm_representation()
            selector_map = getattr(state.dom_state, "selector_map", {})
            for idx, node in selector_map.items():
                element_indexes.add(idx)
                attrs = getattr(node, "attributes", {}) or {}
                tag = getattr(node, "tag_name", "") or ""
                input_type = attrs.get("type", "") or ""

                ax_node = getattr(node, "ax_node", None)
                ax_name = getattr(ax_node, "name", "") or ""
                ax_role = getattr(ax_node, "role", "") or ""
                aria_label = attrs.get("aria-label", "") or ""

                children_text = ""
                if hasattr(node, "get_all_children_text") and callable(node.get_all_children_text):
                    try:
                        children_text = node.get_all_children_text(max_depth=3) or ""
                    except Exception:
                        children_text = ""
                if not children_text:
                    children_text = getattr(node, "text", "") or ""

                placeholder = attrs.get("placeholder", "") or ""
                title_attr = attrs.get("title", "") or ""
                alt = attrs.get("alt", "") or ""
                val = attrs.get("value", "") or ""
                is_password = input_type.lower() == "password" or "password" in f"{attrs.get('name', '')} {attrs.get('id', '')}".lower()

                acc_name = compute_accessible_name(
                    ax_name=ax_name,
                    aria_label=aria_label,
                    children_text=children_text,
                    placeholder=placeholder,
                    title=title_attr,
                    alt=alt,
                    value=val,
                    is_password=is_password,
                )
                has_href = "href" in attrs
                is_option = (
                    ax_role == "option"
                    or attrs.get("role", "").lower() == "option"
                    or tag.lower() == "option"
                )
                role = compute_role(
                    ax_role=ax_role,
                    tag=tag,
                    input_type=input_type,
                    has_href=has_href,
                    is_option=is_option,
                )

                element_meta[idx] = ElementMeta(
                    index=idx,
                    tag=tag,
                    input_type=input_type,
                    name=attrs.get("name", "") or "",
                    id=attrs.get("id", "") or "",
                    aria_label=aria_label,
                    text=val or children_text,
                    accessible_name=acc_name,
                    role=role,
                    placeholder=placeholder,
                    title=title_attr,
                    alt=alt,
                )

        return PageObservation(
            url=url,
            title=title,
            elements_text=elements_text,
            element_indexes=element_indexes,
            element_meta=element_meta,
            screenshot_b64=None,
        )

    async def refresh_title(self, url: str = "") -> str:
        """Retry the page title 4×0.5s when observe() still has an empty or URL-like title."""
        if not self.session:
            return ""
        title = ""
        for _ in range(4):
            await asyncio.sleep(0.5)
            try:
                candidate = await self.session.get_current_page_title()
                if candidate and not is_url_like(candidate, url):
                    return candidate
                if candidate:
                    title = candidate
            except Exception:
                pass
        if title and not is_url_like(title, url):
            return title
        return ""

    async def execute(self, action: NormalizedAction) -> ExecResult:
        """Dispatch a single event into browser-use's internal event bus."""
        from browser_use.browser.events import (
            ClickElementEvent,
            GoBackEvent,
            NavigateToUrlEvent,
            ScrollEvent,
            SelectDropdownOptionEvent,
            TypeTextEvent,
            WaitEvent,
        )

        if not self.session:
            return ExecResult(
                ok=False,
                error_code=ErrorCode.BROWSER_CRASHED,
                detail="Browser session is not running.",
            )

        start_time = time.monotonic()
        try:
            event = None
            if action.action == ActionType.NAVIGATE:
                event = NavigateToUrlEvent(url=action.target)
            elif action.action == ActionType.CLICK:
                if action.element_index is None:
                    return ExecResult(ok=False, error_code=ErrorCode.INVALID_ACTION, detail="Missing element index")
                node = await self.session.get_element_by_index(action.element_index)
                event = ClickElementEvent(node=node)
            elif action.action == ActionType.TYPE:
                if action.element_index is None:
                    return ExecResult(ok=False, error_code=ErrorCode.INVALID_ACTION, detail="Missing element index")
                node = await self.session.get_element_by_index(action.element_index)
                event = TypeTextEvent(node=node, text=action.value, clear=True)
            elif action.action == ActionType.SELECT:
                if action.element_index is None:
                    return ExecResult(ok=False, error_code=ErrorCode.INVALID_ACTION, detail="Missing element index")
                node = await self.session.get_element_by_index(action.element_index)
                event = SelectDropdownOptionEvent(node=node, text=action.value)
            elif action.action == ActionType.SCROLL:
                direction = action.scroll_direction or "down"
                event = ScrollEvent(direction=direction, amount=600)
            elif action.action == ActionType.WAIT:
                seconds = float(action.value) if action.value else 1.0
                event = WaitEvent(seconds=seconds)
            elif action.action == ActionType.BACK:
                event = GoBackEvent()
            else:
                return ExecResult(
                    ok=False,
                    error_code=ErrorCode.UNSUPPORTED_ACTION,
                    detail=f"Action {action.action.value} cannot be dispatched to browser.",
                )

            coro = self._dispatch_event(event)
            await asyncio.wait_for(coro, timeout=self.action_timeout)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return ExecResult(ok=True, duration_ms=duration_ms)

        except TimeoutError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return ExecResult(
                ok=False,
                error_code=ErrorCode.ACTION_TIMEOUT,
                detail=f"Action {action.action.value} timed out after {self.action_timeout}s.",
                duration_ms=duration_ms,
            )
        except Exception as err:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            err_msg = str(err)
            if any(err_term in err_msg for err_term in ["ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_REFUSED", "net::"]):
                return ExecResult(
                    ok=False,
                    error_code=ErrorCode.SITE_UNREACHABLE,
                    detail=err_msg,
                    duration_ms=duration_ms,
                )
            return ExecResult(
                ok=False,
                error_code=ErrorCode.ACTION_FAILED,
                detail=err_msg,
                duration_ms=duration_ms,
            )

    async def _dispatch_event(self, event) -> None:
        ev = self.session.event_bus.dispatch(event)
        await ev
        await ev.event_result(raise_if_any=True, raise_if_none=False)

    async def close(self) -> None:
        """Safely close browser session (idempotent, with Windows transport drain)."""
        if self.session is not None:
            session = self.session
            self.session = None
            try:
                await session.kill()
            except Exception as e:
                logger.warning("Error killing browser session", error=str(e))
            finally:
                await asyncio.sleep(0.3)

    async def get_current_page_url(self) -> str:
        if not self.session:
            raise RuntimeError("Browser session has not been started.")
        return await self.session.get_current_page_url()

    async def capture_for_perception(self) -> PerceptionCapture:
        """Capture viewport screenshot, main text, and page structure (FR-26, NFR-SEC-07)."""
        if not self.session:
            raise RuntimeError("Browser session has not been started.")

        url = "about:blank"
        title = ""
        try:
            url = await self.session.get_current_page_url() or "about:blank"
        except Exception as err:
            logger.warning("perception_capture_url_failed", error=str(err))
        try:
            title = await self.session.get_current_page_title() or ""
        except Exception as err:
            logger.warning("perception_capture_title_failed", error=str(err))

        meta = await self._collect_perception_dom()
        has_filled_password = bool(meta.get("has_filled_password"))
        secrets = [value for value in meta.get("password_values", []) if value]

        main_text = ""
        try:
            from browser_use.dom.markdown_extractor import extract_clean_markdown

            content, _stats = await extract_clean_markdown(
                browser_session=self.session,
                extract_links=False,
                extract_images=False,
            )
            main_text = (content or "")[:MAIN_TEXT_CAP]
        except Exception as err:
            logger.warning("perception_markdown_failed", error=str(err))

        if secrets:
            main_text = mask_secrets(main_text, secrets)

        headings = list(meta.get("headings") or [])
        if not headings:
            headings = headings_from_markdown(main_text)

        screenshot: bytes | None = None
        if not has_filled_password:
            try:
                raw = await self.session.take_screenshot(format="jpeg", quality=SCREENSHOT_JPEG_QUALITY)
                screenshot = resize_screenshot_jpeg(raw)
            except Exception as err:
                logger.warning("perception_screenshot_failed", error=str(err))

        return PerceptionCapture(
            url=url,
            title=title,
            screenshot_png=screenshot,
            main_text=main_text,
            headings=headings,
            landmarks=list(meta.get("landmarks") or []),
            link_count=int(meta.get("link_count") or 0),
            button_count=int(meta.get("button_count") or 0),
            field_count=int(meta.get("field_count") or 0),
            has_filled_password=has_filled_password,
        )

    async def _collect_perception_dom(self) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "headings": [],
            "landmarks": [],
            "link_count": 0,
            "button_count": 0,
            "field_count": 0,
            "password_values": [],
            "has_filled_password": False,
        }
        try:
            cdp_session = await self.session.get_or_create_cdp_session()
            result = await cdp_session.cdp_client.send.Runtime.evaluate(
                params={
                    "expression": _PERCEPTION_DOM_JS,
                    "returnByValue": True,
                    "awaitPromise": False,
                },
                session_id=cdp_session.session_id,
            )
            value = (result or {}).get("result", {}).get("value")
            if isinstance(value, dict):
                return {**empty, **value}
        except Exception as err:
            logger.warning("perception_dom_eval_failed", error=str(err))
        return empty


class _FakeCdpSession:
    """Minimal session stand-in so BrowserHost health checks work in tests."""

    def __init__(self, url: str = "https://example.com"):
        self.is_cdp_connected = True
        self._url = url

    async def get_current_page_url(self) -> str:
        if not self.is_cdp_connected:
            raise RuntimeError("CDP disconnected")
        return self._url


class FakeBrowserGateway:
    """In-memory mock browser gateway for unit testing without Chromium (NFR-MAINT-03)."""

    def __init__(
        self,
        pages: list[PageObservation] | None = None,
        fail_on_sequences: set[int] | None = None,
        crash_on_sequence: int | None = None,
        title_retries: list[str] | None = None,
        captures: list[PerceptionCapture] | None = None,
    ):
        self.pages: list[PageObservation] = list(pages or [])
        self.fail_on_sequences = set(fail_on_sequences or set())
        self.crash_on_sequence = crash_on_sequence
        self.title_retries = list(title_retries or [])
        self.captures: list[PerceptionCapture] = list(captures or [])
        self.executed_actions: list[NormalizedAction] = []
        self.action_counter = 0
        self.is_closed = False
        self.started_profile: Path | None = None
        self.session: _FakeCdpSession | None = None

    async def start(self, profile_dir: Path) -> None:
        self.started_profile = profile_dir
        self.is_closed = False
        if self.session is None:
            self.session = _FakeCdpSession()

    async def observe(self) -> PageObservation:
        if self.pages:
            return self.pages.pop(0)
        return PageObservation(url="https://example.com", title="Example Domain")

    async def refresh_title(self, url: str = "") -> str:
        if getattr(self, "title_retries", None):
            return self.title_retries.pop(0)
        return ""

    async def execute(self, action: NormalizedAction) -> ExecResult:
        self.action_counter += 1
        if self.crash_on_sequence == self.action_counter:
            raise RuntimeError("Simulated browser crash")

        if self.action_counter in self.fail_on_sequences:
            return ExecResult(
                ok=False,
                error_code=ErrorCode.ACTION_FAILED,
                detail=f"Failed on sequence {self.action_counter}",
                duration_ms=10,
            )

        self.executed_actions.append(action)
        if action.action == ActionType.NAVIGATE and self.session is not None:
            self.session._url = action.target
        return ExecResult(ok=True, duration_ms=10)

    async def close(self) -> None:
        self.is_closed = True
        self.session = None

    async def get_current_page_url(self) -> str:
        if self.session is None:
            raise RuntimeError("Browser session has not been started.")
        return await self.session.get_current_page_url()

    async def capture_for_perception(self) -> PerceptionCapture:
        if self.captures:
            return self.captures.pop(0)
        page = self.pages[0] if self.pages else PageObservation(url="https://example.com", title="Example Domain")
        return PerceptionCapture(
            url=page.url,
            title=page.title,
            screenshot_png=b"fake-jpeg",
            main_text=f"{page.title}\n\nExample page text for tests.",
            headings=[page.title] if page.title else [],
            landmarks=["main"],
            link_count=1,
            button_count=0,
            field_count=0,
            has_filled_password=False,
        )
