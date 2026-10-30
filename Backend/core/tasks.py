"""Celery asynchronous tasks for CIGHT-BROWSER (CON-01).

CON-01: Celery runs all long browser/AI work (never inside HTTP views or Channels consumers).
"""
import asyncio

import structlog
from celery import shared_task

from core.agent.browser import BrowserUseGateway
from core.agent.events import ChannelsEventPublisher
from core.agent.llm import GeminiClient
from core.agent.perception import PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.enums import TaskStatus
from core.models import AgentTask

logger = structlog.get_logger(__name__)


@shared_task(bind=True, acks_late=True)
def run_agent_task(self, task_id: str) -> None:
    """Execute autonomous browser task inside background Celery worker."""
    logger.info("Executing Celery agent task", task_id=task_id, celery_id=self.request.id)

    try:
        task = AgentTask.objects.get(pk=task_id)
    except AgentTask.DoesNotExist:
        logger.error("AgentTask not found", task_id=task_id)
        return

    # Verify task is still in PENDING state
    if task.status != TaskStatus.PENDING:
        logger.warning("Task is not in PENDING status, skipping execution", status=task.status)
        return

    # Atomic transition to RUNNING per FR-09
    task.transition_to(TaskStatus.RUNNING)

    llm = GeminiClient()
    browser = BrowserUseGateway()
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = ChannelsEventPublisher()

    runner = TaskRunner(
        task_id=task.id,
        llm=llm,
        browser=browser,
        policy=policy,
        perception=perception,
        publisher=publisher,
    )

    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    asyncio.run(runner.run())
