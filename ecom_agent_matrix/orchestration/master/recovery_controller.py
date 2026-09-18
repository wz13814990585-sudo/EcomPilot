"""One-state/one-decision recovery controller."""

from __future__ import annotations

from pydantic import ValidationError

from ...config.settings import settings
from ...core.errors import ErrorCode
from ...core.llm import is_llm_configured, llm_chat_structured, resolve_mode
from .prompts import RECOVERY_SYSTEM_PROMPT
from .schemas import (
    PlanExecutionResult,
    RecoveryDecision,
)
from .telemetry import MasterLLMTelemetry
from ...platform.observability.context import trace_context

_RECOVERABLE = frozenset(
    {
        ErrorCode.AGENT_TIMEOUT.value,
        ErrorCode.AGENT_FAILED.value,
        ErrorCode.STEP_EXECUTION_ERROR.value,
    }
)


class RecoveryController:
    async def run(
        self,
        execution: PlanExecutionResult,
        telemetry: MasterLLMTelemetry,
    ) -> RecoveryDecision | None:
        if execution.all_success:
            return None
        failed = [
            result
            for result in execution.step_results.values()
            if result.status == "FAILED" and result.error_code in _RECOVERABLE
        ]
        if not failed:
            return None
        if not is_llm_configured():
            return RecoveryDecision(action="finish", reason_code="RECOVERY_LLM_UNAVAILABLE")

        compact = [
            {
                "step_id": result.step_id,
                "agent": result.agent,
                "task_type": result.task_type,
                "error_code": result.error_code,
            }
            for result in failed
        ]
        if not telemetry.start_call("recovery"):
            return RecoveryDecision(action="finish", reason_code="LLM_BUDGET_EXCEEDED")
        try:
            with trace_context(workflow="recovery"):
                structured = await llm_chat_structured(
                    response_model=RecoveryDecision,
                    repair_attempts=0,
                    user_prompt=f"Failed plan steps:\n{compact}",
                    system_prompt=RECOVERY_SYSTEM_PROMPT,
                    temperature=0.1,
                    max_tokens=int(settings.MASTER_REACT_MAX_TOKENS),
                    mode=resolve_mode(settings.MASTER_REACT_MODE),
                )
            telemetry.add_result("recovery", structured.response)
            decision = structured.value
            if decision.action == "retry_agent":
                target = execution.step_results.get(decision.step_id)
                if target is None or target.agent == "biz_exec":
                    return RecoveryDecision(
                        action="finish", reason_code="UNSAFE_RECOVERY_RETRY_REJECTED"
                    )
            return decision
        except (ValidationError, TypeError, ValueError):
            return RecoveryDecision(action="finish", reason_code="INVALID_RECOVERY_DECISION")
        except Exception:
            return RecoveryDecision(action="finish", reason_code="RECOVERY_PROVIDER_ERROR")


recovery_controller = RecoveryController()
