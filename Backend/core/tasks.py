"""Celery asynchronous tasks for CIGHT-BROWSER (CON-01).

CON-01: Celery runs all long browser/AI work (never inside HTTP views or Channels consumers).
"""
import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings

from core.agent.browser import FakeBrowserGateway
from core.agent.browser_host import get_browser_host
from core.agent.events import ChannelsEventPublisher, EventPublisher
from core.agent.llm import GeminiClient
from core.agent.perception import PerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.agent.worker_lock import WORKER_BUSY_MESSAGE, browser_worker_available
from core.enums import TaskMode, TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask

logger = structlog.get_logger(__name__)


async def execute_on_host(
    task: AgentTask,
    host,
    publisher: EventPublisher,
    *,
    llm: GeminiClient | None = None,
    perception: PerceptionAgent | None = None,
) -> None:
    """Acquire the hosted browser (or skip if no page) and run Task or Perception runner."""
    session = task.session
    profile_dir = host._profile_dir(session)
    last_url = session.last_url or ""
    session_id = str(session.id)
    perception = perception or PerceptionAgent()
    llm = llm or GeminiClient()
    policy = PlaceholderSafetyPolicy()

    if task.mode == TaskMode.PERCEPTION:
        from core.agent.perception_runner import PerceptionRunner

        was_open = host.is_open(session_id)
        if not was_open and not last_url.strip():
            runner = PerceptionRunner(
                task_id=task.id,
                browser=FakeBrowserGateway(),
                publisher=publisher,
                perception=perception,
                browser_was_open=False,
            )
            await runner.run()
            return
        acquired = await host.acquire_async(session_id, profile_dir, last_url)
        runner = PerceptionRunner(
            task_id=task.id,
            browser=acquired.gateway,
            publisher=publisher,
            perception=perception,
            reopened_page=acquired.restored,
            browser_was_open=was_open,
        )
        await runner.run()
        return

    acquired = await host.acquire_async(session_id, profile_dir, last_url)
    runner = TaskRunner(
        task_id=task.id,
        llm=llm,
        browser=acquired.gateway,
        policy=policy,
        perception=perception,
        publisher=publisher,
        reopened_page=acquired.restored,
    )
    await runner.run()


def _fail_busy_worker(task: AgentTask) -> None:
    task.error_code = ErrorCode.TASK_INTERRUPTED.value
    task.error_message = WORKER_BUSY_MESSAGE
    task.result_text = WORKER_BUSY_MESSAGE
    task.save(update_fields=["error_code", "error_message", "result_text", "updated_at"])
    try:
        task.transition_to(TaskStatus.FAILED)
    except Exception as err:
        logger.error("busy_worker_fail_transition", error=str(err))
    try:
        async_to_sync(ChannelsEventPublisher().publish)(
            task,
            "task_failed",
            {
                "speak": WORKER_BUSY_MESSAGE,
                "error_code": ErrorCode.TASK_INTERRUPTED.value,
                "message": WORKER_BUSY_MESSAGE,
            },
        )
    except Exception as err:
        logger.warning("busy_worker_event_failed", error=str(err))


def _execute_agent_task(task: AgentTask) -> None:
    """Run the task on the process-wide BrowserHost loop so Chromium stays open."""
    host = get_browser_host()
    publisher = ChannelsEventPublisher()
    timeout = float(getattr(settings, "BROWSER_TASK_TIMEOUT_SECONDS", 1800))
    try:
        host.submit(execute_on_host(task, host, publisher), timeout=timeout)
    finally:
        host.release(str(task.session_id))


@shared_task(bind=True, acks_late=True)
def run_agent_task(self, task_id: str) -> None:
    """Execute autonomous browser or perception task inside background Celery worker."""
    logger.info("Executing Celery agent task", task_id=task_id, celery_id=self.request.id)

    try:
        task = AgentTask.objects.select_related("session", "session__profile", "user").get(pk=task_id)
    except AgentTask.DoesNotExist:
        logger.error("AgentTask not found", task_id=task_id)
        return

    if task.status != TaskStatus.PENDING:
        logger.warning("Task is not in PENDING status, skipping execution", status=task.status)
        return

    if not browser_worker_available():
        logger.error("browser_worker_lock_held", task_id=task_id)
        _fail_busy_worker(task)
        return

    task.transition_to(TaskStatus.RUNNING)

    try:
        _execute_agent_task(task)
    except Exception as err:
        logger.exception("Escaped exception in Celery task", task_id=str(task.id), error=str(err))
        task.refresh_from_db()
        if task.status not in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            task.error_code = ErrorCode.INTERNAL_ERROR.value
            task.error_message = USER_MESSAGES.get(ErrorCode.INTERNAL_ERROR, "An internal error occurred.")
            task.save(update_fields=["error_code", "error_message", "updated_at"])
            try:
                task.transition_to(TaskStatus.FAILED)
            except Exception as trans_err:
                logger.error("Failed transition to FAILED in Celery safety net", error=str(trans_err))


@shared_task(acks_late=True)
def close_browser(session_id: str) -> None:
    """Kill the live Chromium instance for a closed session (FR-02)."""
    logger.info("Closing hosted browser", session_id=session_id)
    host = get_browser_host()
    host.close(session_id)
