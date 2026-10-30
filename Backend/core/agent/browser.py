"""Browser automation gateway interfacing with Chromium and Playwright (FR-10, FR-17)."""
import asyncio
import time
from pathlib import Path
from typing import Protocol

import structlog
from django.conf import settings

from core.agent.schema import ElementMeta, ExecResult, NormalizedAction, PageObservation
from core.enums import ActionType
from core.errors import ErrorCode

logger = structlog.get_logger(__name__)


class BrowserGateway(Protocol):
    """Protocol defining the browser abstraction layer."""

    async def start(self, profile_dir: Path) -> None:
        """Initialize and launch the browser session using the given profile directory."""
        ...

    async def observe(self) -> PageObservation:
        """Capture the current page state, indexed DOM elements, and metadata."""
        ...

    async def execute(self, action: NormalizedAction) -> ExecResult:
        """Execute a single normalized browser action in Chromium."""
        ...

    async def close(self) -> None:
        """Safely terminate the browser process and release the profile lock."""
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

        elements_text = ""
        element_indexes: set[int] = set()
        element_meta: dict[int, ElementMeta] = {}

        if state.dom_state:
            elements_text = state.dom_state.llm_representation()
            selector_map = getattr(state.dom_state, "selector_map", {})
            for idx, node in selector_map.items():
                element_indexes.add(idx)
                attrs = getattr(node, "attributes", {}) or {}
                element_meta[idx] = ElementMeta(
                    tag=getattr(node, "tag_name", "") or "",
                    input_type=attrs.get("type", ""),
                    name=attrs.get("name", ""),
                    id=attrs.get("id", ""),
                    aria_label=attrs.get("aria-label", ""),
                    text=attrs.get("value", "") or getattr(node, "text", "") or "",
                )

        return PageObservation(
            url=state.url or "about:blank",
            title=state.title or "",
            elements_text=elements_text,
            element_indexes=element_indexes,
            element_meta=element_meta,
            screenshot_b64=None,
        )

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


class FakeBrowserGateway:
    """In-memory mock browser gateway for unit testing without Chromium (NFR-MAINT-03)."""

    def __init__(
        self,
        pages: list[PageObservation] | None = None,
        fail_on_sequences: set[int] | None = None,
        crash_on_sequence: int | None = None,
    ):
        self.pages: list[PageObservation] = list(pages or [])
        self.fail_on_sequences = set(fail_on_sequences or set())
        self.crash_on_sequence = crash_on_sequence
        self.executed_actions: list[NormalizedAction] = []
        self.action_counter = 0
        self.is_closed = False
        self.started_profile: Path | None = None

    async def start(self, profile_dir: Path) -> None:
        self.started_profile = profile_dir
        self.is_closed = False

    async def observe(self) -> PageObservation:
        if self.pages:
            return self.pages.pop(0)
        return PageObservation(url="https://example.com", title="Example Domain")

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
        return ExecResult(ok=True, duration_ms=10)

    async def close(self) -> None:
        self.is_closed = True
