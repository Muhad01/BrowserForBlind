"""CLI command to trigger and test agent tasks end-to-end (NFR-MAINT-03)."""
import asyncio
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.agent.browser import BrowserUseGateway
from core.agent.events import EventPublisher
from core.agent.llm import GeminiClient
from core.agent.perception import PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.enums import TaskStatus
from core.models import AgentTask
from core.services.tasks import create_task

User = get_user_model()


class ConsolePublisher(EventPublisher):
    """Event publisher that prints spoken announcements and status updates to stdout."""

    def __init__(self, stdout, style):
        self.stdout = stdout
        self.style = style

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        speak_text = payload.get("speak") or payload.get("text") or payload.get("message") or ""
        if event == "browser_action":
            self.stdout.write(self.style.SUCCESS(f">> [SPEAK] {speak_text}"))
        elif event == "task_started":
            self.stdout.write(self.style.NOTICE(f">> [SPEAK] {speak_text}"))
        elif event == "task_completed":
            self.stdout.write(self.style.SUCCESS(f">> [SPEAK] {speak_text}"))
        elif event == "task_failed":
            self.stdout.write(self.style.ERROR(f">> [SPEAK] {speak_text}"))
        elif event == "agent_status" or event == "perception_result":
            self.stdout.write(self.style.MIGRATE_HEADING(f">> [SPEAK] {speak_text}"))
        else:
            self.stdout.write(f"   [{event}] {speak_text or payload}")


class Command(BaseCommand):
    help = "Run an agent task via Celery worker or inline synchronously."

    def add_arguments(self, parser):
        parser.add_argument("goal", type=str, help="Goal for the browser agent to accomplish")
        parser.add_argument("--user", type=str, default="demo", help="Username to own the task (default: demo)")
        parser.add_argument("--sync", action="store_true", help="Run inline synchronously without Celery")

    def handle(self, *args, **options):
        from core.services.recovery import reap_stale_tasks
        reaped = reap_stale_tasks()
        if reaped > 0:
            self.stdout.write(self.style.NOTICE(f"Reaped {reaped} stale task(s)."))

        goal = options["goal"]
        username = options["user"]
        is_sync = options["sync"]

        user = User.objects.filter(username=username).first()
        if not user:
            if not settings.DEBUG:
                raise CommandError("User creation via run_task is disallowed in production mode.")
            user = User.objects.create_user(username=username, password="devpassword123")
            self.stdout.write(self.style.NOTICE(f"Created dev user '{username}'"))

        self.stdout.write(self.style.MIGRATE_HEADING(f"Creating task for '{username}': \"{goal}\""))

        # For sync mode, don't dispatch to Celery
        task = create_task(user, goal=goal, dispatch=not is_sync)
        self.stdout.write(f"Created AgentTask id: {task.id} (Status: {task.status})")

        if is_sync:
            self.stdout.write(self.style.WARNING("Running task synchronously (inline)..."))
            task.transition_to(TaskStatus.RUNNING)

            llm = GeminiClient()
            browser = BrowserUseGateway()
            policy = PlaceholderSafetyPolicy()
            perception = PlaceholderPerceptionAgent()
            publisher = ConsolePublisher(self.stdout, self.style)

            runner = TaskRunner(
                task_id=task.id,
                llm=llm,
                browser=browser,
                policy=policy,
                perception=perception,
                publisher=publisher,
            )

            try:
                import sys
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                asyncio.run(runner.run())
            except KeyboardInterrupt:
                self.stdout.write(self.style.ERROR("Execution interrupted by user."))
            finally:
                task.refresh_from_db()
                self.stdout.write(f"Final task status: {task.status}")
                if task.result_text:
                    self.stdout.write(self.style.SUCCESS(f"Final Result: {task.result_text}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Dispatched task to Celery worker (Task ID: {task.id})"))
            self.stdout.write("Monitor celery worker logs to view task execution.")

