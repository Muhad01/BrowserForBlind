"""Autonomous Task Runner executing the observe-propose-validate-safety-execute loop (FR-10..18)."""
import hashlib
import uuid

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings

from core.agent.browser import BrowserGateway
from core.agent.events import EventPublisher, format_spoken_action
from core.agent.llm import HistoryItem, LLMBadOutput, LLMClient, LLMUnavailable, Proposal
from core.agent.perception import PerceptionPort
from core.agent.safety import SafetyPolicy, SafetyVerdict
from core.agent.schema import NormalizedAction
from core.agent.validator import ActionValidator, ValidationFailure
from core.enums import ActionStatus, ActionType, SafetyDecision, TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentAction, AgentTask, PageState

logger = structlog.get_logger(__name__)


class TaskRunner:
    """Manages the lifecycle and execution loop of a single AgentTask."""

    def __init__(
        self,
        task_id: str | uuid.UUID,
        llm: LLMClient,
        browser: BrowserGateway,
        policy: SafetyPolicy,
        perception: PerceptionPort,
        publisher: EventPublisher,
    ):
        self.task_id = task_id
        self.llm = llm
        self.browser = browser
        self.policy = policy
        self.perception = perception
        self.publisher = publisher

    async def run(self) -> None:
        """Execute the main agent loop (FR-10)."""
        task = await AgentTask.objects.select_related("user", "session", "session__profile").aget(pk=self.task_id)

        # Server-side resolved profile path (FR-53)
        profile_dir = task.session.profile.path if task.session.profile else settings.BROWSER_PROFILE_ROOT / str(task.user_id) / "default"

        # FR-19, FR-59: Announce task start
        await self.publisher.publish(task, "task_started", {"message": f"Starting: {task.goal}"})

        max_steps = getattr(settings, "TASK_MAX_STEPS", 50)
        failure_limit = getattr(settings, "CONSECUTIVE_FAILURE_LIMIT", 3)

        history: list[HistoryItem] = []
        step_count = task.step_count
        consecutive_failures = task.consecutive_failures

        await self.browser.start(profile_dir)
        try:
            while True:
                # FR-41/42: Check for cooperative cancellation
                await task.arefresh_from_db()
                if task.cancel_requested:
                    logger.info("Task cancellation detected", task_id=str(task.id))
                    await sync_to_async(task.transition_to)(TaskStatus.CANCELLED)
                    task.error_code = ErrorCode.CANCELLED_BY_USER.value
                    task.error_message = USER_MESSAGES[ErrorCode.CANCELLED_BY_USER]
                    await task.asave(update_fields=["error_code", "error_message", "updated_at"])
                    await self.publisher.publish(
                        task,
                        "task_failed",
                        {
                            "error_code": ErrorCode.CANCELLED_BY_USER.value,
                            "error_message": task.error_message,
                        },
                    )
                    return

                if step_count >= max_steps:
                    await self._fail_task(task, ErrorCode.MAX_STEPS_REACHED, detail=f"Step limit {max_steps} reached.")
                    return

                # Capture current page state
                obs = await self.browser.observe()
                state_hash = hashlib.sha256(f"{obs.url}{obs.title}".encode()).hexdigest()
                await PageState.objects.acreate(
                    task=task,
                    url=obs.url,
                    title=obs.title,
                    state_hash=state_hash,
                    summary="",
                )

                # Propose next single action from LLM
                try:
                    proposal = await self.llm.propose(task.goal, history, obs)
                    if isinstance(proposal, Proposal):
                        proposed = proposal.action
                        model_used = proposal.model
                    else:
                        proposed = proposal
                        model_used = getattr(proposal, "model_used", "")
                except (LLMUnavailable, LLMBadOutput):
                    raise
                except Exception as err:
                    raise LLMUnavailable(str(err)) from err

                sequence = step_count + 1

                # Validate raw action proposal (FR-14..16)
                validation = ActionValidator.validate(proposed, obs)
                if isinstance(validation, ValidationFailure):
                    logger.warning("Proposed action invalid", code=validation.error_code.value, reason=validation.reason)
                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=ActionType.WAIT,  # Fallback type for invalid actions
                        target=proposed.target[:255],
                        value=proposed.value[:500],
                        reason=proposed.reason,
                        status=ActionStatus.REJECTED_INVALID,
                        error_code=validation.error_code.value,
                        model_used=model_used,
                    )
                    consecutive_failures += 1
                    history.append(HistoryItem(
                        sequence=sequence,
                        action=f"{proposed.action} {proposed.target}".strip(),
                        result=f"rejected: {validation.reason}",
                    ))
                    if consecutive_failures >= failure_limit:
                        await self._fail_task(task, ErrorCode.TOO_MANY_FAILURES, detail=f"{consecutive_failures} failures.")
                        return

                    step_count += 1
                    task.consecutive_failures = consecutive_failures
                    task.step_count = step_count
                    await task.asave(update_fields=["consecutive_failures", "step_count", "updated_at"])
                    continue

                normalized: NormalizedAction = validation

                # Deterministic Safety Policy Check (FR-17, CON-03)
                verdict: SafetyVerdict = self.policy.classify(normalized, obs)

                # FR-35 combining rule: AI's requires_confirmation can only elevate to REQUIRE_CONFIRMATION
                decision = verdict.decision
                rule = verdict.rule
                if normalized.requires_confirmation and decision == SafetyDecision.ALLOW:
                    decision = SafetyDecision.REQUIRE_CONFIRMATION
                    rule = f"{rule}_elevated_by_ai"

                if decision == SafetyDecision.BLOCK:
                    logger.warning("Action blocked by SafetyPolicy", rule=rule)
                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=normalized.action,
                        target=normalized.target[:255],
                        value=normalized.value[:500],
                        reason=normalized.reason,
                        safety_decision=SafetyDecision.BLOCK,
                        safety_rule=rule,
                        status=ActionStatus.BLOCKED,
                        model_used=model_used,
                    )
                    consecutive_failures += 1
                    history.append(HistoryItem(
                        sequence=sequence,
                        action=f"{normalized.action.value} {normalized.target}".strip(),
                        result=f"blocked by safety policy rule: {rule}",
                    ))
                    if consecutive_failures >= failure_limit:
                        await self._fail_task(task, ErrorCode.TOO_MANY_FAILURES, detail=f"{consecutive_failures} failures.")
                        return

                    step_count += 1
                    task.consecutive_failures = consecutive_failures
                    task.step_count = step_count
                    await task.asave(update_fields=["consecutive_failures", "step_count", "updated_at"])
                    continue

                if decision == SafetyDecision.REQUIRE_CONFIRMATION:
                    # In M2, full confirmation workflow is staged for M3
                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=normalized.action,
                        target=normalized.target[:255],
                        value=normalized.value[:500],
                        reason=normalized.reason,
                        safety_decision=SafetyDecision.REQUIRE_CONFIRMATION,
                        safety_rule=rule,
                        status=ActionStatus.AWAITING_CONFIRMATION,
                        model_used=model_used,
                    )
                    await self._fail_task(task, ErrorCode.CONFIRMATION_UNAVAILABLE, detail=f"Confirmation required by {rule}.")
                    return

                if decision == SafetyDecision.REQUIRE_USER_INPUT:
                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=normalized.action,
                        target=normalized.target[:255],
                        value="",
                        reason=normalized.reason,
                        safety_decision=SafetyDecision.REQUIRE_USER_INPUT,
                        safety_rule=rule,
                        status=ActionStatus.BLOCKED,
                        redacted=True,
                        model_used=model_used,
                    )
                    await self._fail_task(task, ErrorCode.USER_INPUT_REQUIRED, detail=f"User input required by {rule}.")
                    return

                # ALLOW: Proceed with action execution
                if normalized.action == ActionType.STOP:
                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=ActionType.STOP,
                        target="",
                        value=normalized.value[:500],
                        reason=normalized.reason,
                        safety_decision=SafetyDecision.ALLOW,
                        safety_rule=rule,
                        status=ActionStatus.EXECUTED,
                        model_used=model_used,
                    )
                    task.result_text = normalized.value
                    await task.asave(update_fields=["result_text", "updated_at"])
                    await sync_to_async(task.transition_to)(TaskStatus.COMPLETED)
                    # FR-12, FR-22, FR-64
                    await self.publisher.publish(task, "task_completed", {
                        "result": normalized.value,
                        "reason": normalized.reason,
                    })
                    return

                if normalized.action == ActionType.DESCRIBE:
                    spoken_msg = format_spoken_action(normalized, obs)
                    await self.publisher.publish(task, "browser_action", {"text": spoken_msg})
                    description = await self.perception.describe(obs)
                    await self.publisher.publish(task, "perception_result", {"text": description})
                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=ActionType.DESCRIBE,
                        target="",
                        value=description[:500],
                        reason=normalized.reason,
                        safety_decision=SafetyDecision.ALLOW,
                        safety_rule=rule,
                        status=ActionStatus.EXECUTED,
                        model_used=model_used,
                    )
                    consecutive_failures = 0
                    history.append(HistoryItem(sequence=sequence, action="describe", result=f"observed: {description}"))

                else:
                    # Executing physical browser interaction
                    spoken_msg = format_spoken_action(normalized, obs)
                    await self.publisher.publish(task, "browser_action", {"text": spoken_msg})

                    # Handle password field redaction
                    is_redacted = False
                    stored_value = normalized.value
                    if normalized.action == ActionType.TYPE and "sensitive" in rule.lower():
                        is_redacted = True
                        stored_value = ""

                    exec_res = await self.browser.execute(normalized)
                    status = ActionStatus.EXECUTED if exec_res.ok else ActionStatus.FAILED
                    err_code = exec_res.error_code.value if exec_res.error_code else ""

                    await AgentAction.objects.acreate(
                        task=task,
                        sequence=sequence,
                        action_type=normalized.action,
                        target=normalized.target[:255],
                        value=stored_value[:500],
                        reason=normalized.reason,
                        safety_decision=SafetyDecision.ALLOW,
                        safety_rule=rule,
                        status=status,
                        error_code=err_code,
                        duration_ms=exec_res.duration_ms,
                        redacted=is_redacted,
                        model_used=model_used,
                    )

                    if exec_res.ok:
                        consecutive_failures = 0
                        history.append(HistoryItem(
                            sequence=sequence,
                            action=f"{normalized.action.value} {normalized.target}".strip(),
                            result="success",
                        ))
                    else:
                        consecutive_failures += 1
                        history.append(HistoryItem(
                            sequence=sequence,
                            action=f"{normalized.action.value} {normalized.target}".strip(),
                            result=f"failed: {exec_res.detail or err_code}",
                        ))

                if consecutive_failures >= failure_limit:
                    await self._fail_task(task, ErrorCode.TOO_MANY_FAILURES, detail=f"{consecutive_failures} failures.")
                    return

                step_count += 1
                task.consecutive_failures = consecutive_failures
                task.step_count = step_count
                await task.asave(update_fields=["consecutive_failures", "step_count", "updated_at"])
                await self.publisher.publish(
                    task,
                    "agent_status",
                    {"step": step_count, "message": f"Step {step_count} completed."},
                )

        except LLMUnavailable as err:
            await self._fail_task(task, ErrorCode.LLM_UNAVAILABLE, detail=str(err))
        except LLMBadOutput as err:
            await self._fail_task(task, ErrorCode.LLM_BAD_OUTPUT, detail=str(err))
        except Exception as err:
            err_str = str(err).lower()
            if "crash" in err_str or "disconnect" in err_str or "target closed" in err_str:
                await self._fail_task(task, ErrorCode.BROWSER_CRASHED, detail=str(err))
            else:
                logger.exception("Unexpected error in TaskRunner", task_id=str(task.id), error=str(err))
                await self._fail_task(task, ErrorCode.INTERNAL_ERROR, detail=str(err))
        finally:
            await self.browser.close()

    async def _fail_task(self, task: AgentTask, error_code: ErrorCode, detail: str = "") -> None:
        """Fail task with standardized code and user-safe spoken message (NFR-SEC-06)."""
        logger.error(
            "Task failed",
            task_id=str(task.id),
            error_code=error_code.value,
            detail=detail,
        )
        task.error_code = error_code.value
        task.error_message = USER_MESSAGES.get(error_code, "Task execution failed.")
        await task.asave(update_fields=["error_code", "error_message", "updated_at"])
        await sync_to_async(task.transition_to)(TaskStatus.FAILED)
        await self.publisher.publish(
            task,
            "task_failed",
            {
                "error_code": error_code.value,
                "error_message": task.error_message,
            },
        )
