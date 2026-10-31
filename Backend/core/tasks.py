"""Celery asynchronous tasks for CIGHT-BROWSER (CON-01).

CON-01: Celery runs all long browser/AI work (never inside HTTP views or Channels consumers).
"""
import structlog
from celery import shared_task
from django.conf import settings

from core.agent.browser_host import get_browser_host
from core.agent.events import ChannelsEventPublisher
from core.agent.llm import GeminiClient
from core.agent.perception import PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.enums import TaskMode, TaskStatus
from core.models import AgentTask

logger = structlog.get_logger(__name__)


def _execute_agent_task(task: AgentTask) -> None:
    """Run the task on the process-wide BrowserHost loop so Chromium stays open."""
    host = get_browser_host()
    llm = GeminiClient()
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = ChannelsEventPublisher()
    timeout = float(getattr(settings, "BROWSER_TASK_TIMEOUT_SECONDS", 1800))

    session = task.session
    profile_dir = host._profile_dir(session)
    last_url = session.last_url or ""
    session_id = str(session.id)

    async def _run() -> None:
        acquired = await host.acquire_async(session_id, profile_dir, last_url)
        if task.mode == TaskMode.PERCEPTION:
            from core.agent.perception_runner import PerceptionRunner

            runner = PerceptionRunner(
                task_id=task.id,
                browser=acquired.gateway,
                publisher=publisher,
                reopened_page=acquired.restored,
            )
            await runner.run()
        else:
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

    try:
        host.submit(_run(), timeout=timeout)
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
            from core.errors import USER_MESSAGES, ErrorCode

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
