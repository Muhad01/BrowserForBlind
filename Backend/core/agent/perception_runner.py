"""PerceptionRunner: capture the open page and speak a description (CON-02, FR-24..28)."""
from __future__ import annotations

import hashlib
import uuid

import structlog
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from core.agent.browser import BrowserGateway
from core.agent.events import EventPublisher
from core.agent.messages import t
from core.agent.perception import PerceptionAgent, PerceptionCancelled, PerceptionResult
from core.agent.schema import PerceptionCapture
from core.enums import TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask, BrowserSession, PageState
from core.services.commands import (
    CommandIntent,
    classify_command,
    perception_op_key,
    perception_question_key,
    read_cursor_key,
)
from core.services.screenshots import save_screenshot

logger = structlog.get_logger(__name__)

NO_PAGE_TEXT = "There's no page open yet. Tell me where to go first."
NOTHING_TO_CONTINUE = "There's nothing to continue."
LOOKING_BRIEF = "Looking at the page."
READING_BRIEF = "Reading."


async def _call_maybe_kwargs(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except TypeError:
        return await fn(*args)


class PerceptionRunner:
    """Logically separate from TaskRunner (CON-02)."""

    def __init__(
        self,
        task_id: str | uuid.UUID,
        browser: BrowserGateway,
        publisher: EventPublisher,
        perception: PerceptionAgent | None = None,
        reopened_page: bool = False,
        browser_was_open: bool = True,
    ):
        self.task_id = task_id
        self.browser = browser
        self.publisher = publisher
        self.perception = perception or PerceptionAgent()
        self.reopened_page = reopened_page
        self.browser_was_open = browser_was_open
        self.lang = "en"

    async def run(self) -> None:
        close_old_connections()
        task = await AgentTask.objects.select_related("user", "session", "session__profile").aget(
            pk=self.task_id
        )
        session = task.session
        self.lang = getattr(task, "language", "en") or "en"
        operation = await self._operation_for(task)
        brief_key = "reading" if operation in {CommandIntent.READ, CommandIntent.READ_MORE} else "looking_brief"
        brief = t(brief_key, self.lang)
        await self.publisher.publish(
            task,
            "task_started",
            {"speak": brief, "brief": brief, "goal": task.goal_original or task.goal},
        )

        try:
            if not self.browser_was_open and not (session.last_url or "").strip():
                await self._finish(task, t("no_page", self.lang), operation, uncertain=False)
                return

            if getattr(self.browser, "session", None) is None:
                profile_dir = (
                    session.profile.path
                    if session.profile
                    else None
                )
                if profile_dir is not None:
                    await self.browser.start(profile_dir)

            if self.reopened_page:
                await self.publisher.publish(
                    task,
                    "agent_status",
                    {
                        "speak": t("reopened", self.lang),
                        "step": 0,
                        "url": session.last_url or "",
                        "title": "",
                    },
                )

            await task.arefresh_from_db()
            if task.cancel_requested:
                await self._cancelled(task)
                return

            capture = await self.browser.capture_for_perception()
            if capture.url and capture.url != "about:blank":
                await BrowserSession.objects.filter(pk=session.id).aupdate(
                    last_url=capture.url[:2048],
                    updated_at=timezone.now(),
                )

            try:
                result = await self._run_operation(task, session, capture, operation)
            except PerceptionCancelled:
                await self._cancelled(task)
                return
            speak = result.text
            if operation in {CommandIntent.READ, CommandIntent.READ_MORE} and result.has_more:
                speak = f"{result.text} {t('say_continue', self.lang)}"

            screenshot_ref = save_screenshot(str(task.id), capture.screenshot_png)
            state_hash = hashlib.sha256(f"{capture.url}{capture.title}".encode()).hexdigest()
            await PageState.objects.acreate(
                task=task,
                url=capture.url or "",
                title=capture.title or "",
                state_hash=state_hash,
                summary=(result.text or "")[:2000],
                screenshot_ref=screenshot_ref,
            )

            await self.publisher.publish(
                task,
                "perception_result",
                {
                    "speak": speak,
                    "text": result.text,
                    "operation": operation.value,
                    "uncertain": result.uncertain,
                    "has_more": result.has_more,
                    "model": result.model,
                },
            )
            await self._complete(task, result.text, capture.url)
        except Exception as err:
            logger.exception("perception_runner_failed", task_id=str(task.id), error=str(err))
            await self._fail(task, ErrorCode.INTERNAL_ERROR, str(err))
        finally:
            close_old_connections()

    async def _operation_for(self, task: AgentTask) -> CommandIntent:
        cached = await sync_to_async(cache.get)(perception_op_key(str(task.id)))
        if cached:
            try:
                return CommandIntent(cached)
            except ValueError:
                pass
        return classify_command(task.goal)

    async def _run_operation(
        self,
        task: AgentTask,
        session: BrowserSession,
        capture: PerceptionCapture,
        operation: CommandIntent,
    ) -> PerceptionResult:
        cursor_key = read_cursor_key(str(session.id))
        stored = (await sync_to_async(cache.get)(cursor_key)) or {}
        if stored.get("url") != capture.url:
            stored = {"url": capture.url, "index": 0}
            await sync_to_async(cache.set)(cursor_key, stored, 86_400)

        await task.arefresh_from_db()
        if task.cancel_requested:
            raise PerceptionCancelled("Task aborted by user cancellation.")

        def should_abort() -> bool:
            task.refresh_from_db(fields=["cancel_requested"])
            return bool(task.cancel_requested)

        lang = getattr(self, "lang", "en")
        extra = {"language": lang, "should_abort": should_abort}
        if operation == CommandIntent.DESCRIBE:
            return await _call_maybe_kwargs(self.perception.describe, capture, **extra)

        if operation == CommandIntent.ANSWER:
            question = (await sync_to_async(cache.get)(perception_question_key(str(task.id)))) or task.goal
            return await _call_maybe_kwargs(self.perception.answer, capture, question, **extra)

        if operation == CommandIntent.READ:
            result = await _call_maybe_kwargs(self.perception.read, capture, 0, **extra)
            await sync_to_async(cache.set)(cursor_key, {"url": capture.url, "index": result.cursor}, 86_400)
            return result

        if operation == CommandIntent.READ_MORE:
            index = int(stored.get("index") or 0)
            if index <= 0:
                return PerceptionResult(text=t("nothing_to_continue", lang), uncertain=False, has_more=False)
            result = await _call_maybe_kwargs(self.perception.read, capture, index, **extra)
            await sync_to_async(cache.set)(cursor_key, {"url": capture.url, "index": result.cursor}, 86_400)
            return result

        return await _call_maybe_kwargs(self.perception.describe, capture, **extra)

    async def _finish(self, task: AgentTask, text: str, operation: CommandIntent, uncertain: bool) -> None:
        await self.publisher.publish(
            task,
            "perception_result",
            {
                "speak": text,
                "text": text,
                "operation": operation.value,
                "uncertain": uncertain,
                "has_more": False,
                "model": "",
            },
        )
        await self._complete(task, text, "")

    async def _cancelled(self, task: AgentTask) -> None:
        from core.agent.narration import format_task_cancelled

        await task.arefresh_from_db()
        if task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            return
        task.error_code = ErrorCode.CANCELLED_BY_USER.value
        task.error_message = t("error.cancelled_by_user", self.lang)
        await task.asave(update_fields=["error_code", "error_message", "updated_at"])
        await sync_to_async(task.transition_to)(TaskStatus.CANCELLED)
        await self.publisher.publish(
            task,
            "task_failed",
            {
                "speak": format_task_cancelled(language=self.lang),
                "error_code": ErrorCode.CANCELLED_BY_USER.value,
                "error_message": task.error_message,
            },
        )

    async def _complete(self, task: AgentTask, result_text: str, final_url: str) -> None:
        await task.arefresh_from_db()
        if task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            return
        task.result_text = result_text
        task.final_url = final_url or task.final_url
        await task.asave(update_fields=["result_text", "final_url", "updated_at"])
        await sync_to_async(task.transition_to)(TaskStatus.COMPLETED)
        await self.publisher.publish(
            task,
            "task_completed",
            {
                "speak": "",
                "silent": True,
                "result": result_text,
                "final_url": final_url,
                "final_title": "",
            },
        )

    async def _fail(self, task: AgentTask, error_code: ErrorCode, detail: str) -> None:
        logger.error("Perception task failed", task_id=str(task.id), error_code=error_code.value, detail=detail)
        try:
            await task.arefresh_from_db()
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                return
            task.error_code = error_code.value
            task.error_message = USER_MESSAGES.get(error_code, "Task execution failed.")
            await task.asave(update_fields=["error_code", "error_message", "updated_at"])
            await sync_to_async(task.transition_to)(TaskStatus.FAILED)
            await self.publisher.publish(
                task,
                "task_failed",
                {
                    "speak": task.error_message,
                    "error_code": error_code.value,
                    "error_message": task.error_message,
                },
            )
        except Exception as err:
            logger.error("Error inside PerceptionRunner._fail suppressed", error=str(err))
