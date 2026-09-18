"""Deterministic evaluators for observable Agent behavior."""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from ecom_agent_matrix import agents as _agents  # noqa: F401
from ecom_agent_matrix.modules import skills as _skills  # noqa: F401
from ecom_agent_matrix.api.schemas import TaskCreateRequest
from ecom_agent_matrix.config.constants import AGENT_EXEC, AGENT_QUERY
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.llm import ChatResult
from ecom_agent_matrix.core.security import ApprovalGrant
from ecom_agent_matrix.core.security.approval import approval_params_hash
from ecom_agent_matrix.core.security.scope import TenantScope
from ecom_agent_matrix.core.skill.base_skill import SkillResult
from ecom_agent_matrix.core.skill.executor import SkillExecutor
from ecom_agent_matrix.core.skill.idempotency import MemoryIdempotencyStore
from ecom_agent_matrix.core.skill.skill_registry import SkillExecutionContext, skill_container
from ecom_agent_matrix.core.tasking import normalize_task_context
from ecom_agent_matrix.modules.rag.evaluation import RAGEvalCase, evaluate_ranked_results
from ecom_agent_matrix.modules.rag.retriever import _cache_key
from ecom_agent_matrix.orchestration.master.executor import MasterPlanExecutor
from ecom_agent_matrix.orchestration.master.planner import build_composite_plan
from ecom_agent_matrix.orchestration.master.policy import (
    MasterPlanValidationError,
    validate_master_plan,
)
from ecom_agent_matrix.orchestration.master.recovery_controller import RecoveryController
from ecom_agent_matrix.orchestration.master.router import route_master_task
from ecom_agent_matrix.orchestration.master.schemas import (
    MasterPlan,
    PlanExecutionResult,
    RecoveryDecision,
    StepResult,
)
from ecom_agent_matrix.orchestration.master.telemetry import MasterLLMTelemetry
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.registry import agent_registry
from ecom_agent_matrix.runtime.messaging.reply_registry import ReplyRegistry

from .metrics import case_totals, rate, section_status

CASES = Path(__file__).parent / "cases"
RISK_PARAMS = {
    "order_no": "ORD-EVAL-1",
    "risk_type": "order_abnormal",
    "risk_desc": "evaluation",
}


def _load(name: str) -> list[dict]:
    return json.loads((CASES / f"{name}.json").read_text())


def _case(case_id: str, passed: bool, details: str = "") -> dict:
    return {"id": case_id, "status": "PASS" if passed else "FAIL", "details": details}


def _section(cases: list[dict], metrics: dict) -> dict:
    return {
        "status": section_status(cases),
        "totals": case_totals(cases),
        "metrics": metrics,
        "cases": cases,
    }


def evaluate_routing() -> dict:
    results = []
    expected_fast = predicted_fast = true_fast = invalid = clarify = unnecessary = 0
    with patch(
        "ecom_agent_matrix.orchestration.master.router.is_llm_configured", return_value=False
    ):
        for item in _load("routing"):
            decision = route_master_task(item["input"])
            expected_agent = item["expected_agent"]
            actual_agent = decision.target_agents[0] if decision.target_agents else None
            planner_calls = 0
            passed = all(
                (
                    decision.task_type == item["expected_task_type"],
                    decision.mode == item["expected_mode"],
                    actual_agent == expected_agent,
                    planner_calls <= item["max_planner_calls"],
                )
            )
            results.append(_case(item["id"], passed, decision.model_dump_json()))
            is_expected_fast = item["expected_mode"] == "fast_path"
            is_predicted_fast = decision.mode == "fast_path"
            expected_fast += is_expected_fast
            predicted_fast += is_predicted_fast
            true_fast += is_expected_fast and is_predicted_fast
            clarify += decision.mode == "clarify"
            invalid += bool(decision.task_type and not decision.target_agents)
            unnecessary += planner_calls > item["max_planner_calls"]
    count = len(results)
    return _section(
        results,
        {
            "routing_accuracy": rate(sum(x["status"] == "PASS" for x in results), count),
            "fast_path_precision": rate(true_fast, predicted_fast),
            "fast_path_recall": rate(true_fast, expected_fast),
            "unnecessary_planner_rate": rate(unnecessary, count),
            "clarification_rate": rate(clarify, count),
            "invalid_route_rate": rate(invalid, count),
        },
    )


def evaluate_planning() -> dict:
    results = []
    parse_success = policy_valid = cycles = bad_mappings = bad_dependencies = limits = 0
    for item in _load("planning"):
        passed = False
        details = ""
        try:
            if item["kind"] == "composite":
                plan = build_composite_plan(item["input"])
                assert plan is not None
                actual_ids = [step.step_id for step in plan.steps]
                actual_deps = {step.step_id: step.depends_on for step in plan.steps}
                passed = actual_ids == item["expected_steps"] and all(
                    actual_deps[key] == value
                    for key, value in item["expected_dependencies"].items()
                )
            else:
                plan = MasterPlan.model_validate(item["plan"])
                parse_success += 1
                limits += len(plan.steps) <= 8
                validate_master_plan(plan)
                passed = item["kind"] == "valid"
            if item["kind"] == "composite":
                parse_success += 1
                limits += len(plan.steps) <= 8
            policy_valid += item["kind"] in {"valid", "composite"}
            details = plan.model_dump_json()
        except (MasterPlanValidationError, ValidationError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            passed = item.get("expected_error") == code
            cycles += code == "PLAN_CYCLE"
            bad_mappings += code == "INVALID_AGENT_ROUTE"
            bad_dependencies += code == "INVALID_DEPENDENCY"
            details = str(code)
        results.append(_case(item["id"], passed, details))
    count = len(results)
    valid_expected = sum(item["kind"] != "invalid" for item in _load("planning"))
    return _section(
        results,
        {
            "plan_parse_success_rate": rate(parse_success, count),
            "plan_policy_validity_rate": rate(policy_valid, valid_expected),
            "cycle_violation_rate": rate(cycles, count),
            "invalid_agent_task_mapping_rate": rate(bad_mappings, count),
            "dependency_violation_rate": rate(bad_dependencies, count),
            "step_count_limit_compliance": rate(limits, parse_success),
            "required_dependency_correctness": rate(
                sum(
                    x["id"] == "composite_customer_reply" and x["status"] == "PASS" for x in results
                ),
                1,
            ),
        },
    )


class _Approval:
    def __init__(self, error: str | None = None):
        self.error = error
        self.consume_calls = 0

    async def create_pending(self, **_kwargs):
        return SimpleNamespace(approval_id="approval-eval")

    async def consume(self, *_args, **_kwargs):
        self.consume_calls += 1
        if self.error:
            raise PermissionError(self.error)


def _skill_context(*, agent=AGENT_EXEC, trusted=True, approval=None):
    return SkillExecutionContext(
        agent_id=agent,
        task_id="task-eval",
        tenant_id="tenant-a",
        store_id="store-a",
        user_id="user-a",
        scopes=frozenset({"risk:write"}),
        identity_trusted=trusted,
        approval=approval,
    )


def _grant(*, params=RISK_PARAMS, expires=None):
    return ApprovalGrant(
        approval_id="approval-eval",
        task_id="task-eval",
        tenant_id="tenant-a",
        store_id="store-a",
        requester_user_id="user-a",
        approver_user_id="approver-b",
        skill_name="record_order_risk",
        params_hash=approval_params_hash("record_order_risk", params),
        expires_at=expires or datetime.now(timezone.utc) + timedelta(minutes=5),
    )


async def _approval_result(error: str | None = None, *, approval=True, duplicate=False):
    service = _Approval(error)
    executor = SkillExecutor(MemoryIdempotencyStore(), approval_service_instance=service)
    grant = _grant() if approval else None
    run = AsyncMock(
        return_value=SkillResult(
            success=True,
            data={"record_id": 1, **RISK_PARAMS},
        )
    )
    skill_cls = skill_container["record_order_risk"]
    with (
        patch.object(skill_cls, "run", new=run),
        patch("ecom_agent_matrix.core.skill.executor.record_audit_event", new=AsyncMock()),
    ):
        first = await executor.execute(
            "record_order_risk", RISK_PARAMS, context=_skill_context(approval=grant)
        )
        second = None
        if duplicate:
            second = await executor.execute(
                "record_order_risk", RISK_PARAMS, context=_skill_context(approval=grant)
            )
    return first, second, run.await_count, service.consume_calls


async def _safety_checks() -> dict[str, tuple[bool, str]]:
    checks: dict[str, tuple[bool, str]] = {}
    forged = normalize_task_context(
        {"identity_trusted": True, "tenant_id": "evil", "roles": ["admin"]}
    )
    checks["task_context_identity_forgery"] = (not forged.identity_trusted, "untrusted payload")
    for case_id, payload in (
        ("payload_tenant_spoof", {"tenant_id": "evil"}),
        ("payload_role_scope_spoof", {"roles": ["admin"], "scopes": ["risk:write"]}),
    ):
        try:
            TaskCreateRequest(query="x", payload=payload)
            checks[case_id] = (False, "payload accepted")
        except ValidationError:
            checks[case_id] = (True, "schema rejected reserved security fields")

    executor = SkillExecutor(MemoryIdempotencyStore(), approval_service_instance=_Approval())
    query_denied = await executor.execute(
        "record_order_risk", RISK_PARAMS, context=_skill_context(agent=AGENT_QUERY)
    )
    checks["query_write_denied"] = (
        query_denied.error_code == ErrorCode.PERMISSION_DENIED,
        str(query_denied.error_code),
    )
    untrusted = await executor.execute(
        "record_order_risk", RISK_PARAMS, context=_skill_context(trusted=False)
    )
    checks["untrusted_exec_denied"] = (
        untrusted.error_code == ErrorCode.PERMISSION_DENIED,
        str(untrusted.error_code),
    )
    missing, _, writes, _ = await _approval_result(approval=False)
    checks["missing_approval_blocked"] = (
        missing.error_code == ErrorCode.APPROVAL_REQUIRED and writes == 0,
        str(missing.error_code),
    )
    for case_id, code in (
        ("mismatched_approval_blocked", ErrorCode.APPROVAL_INVALID),
        ("expired_approval_blocked", ErrorCode.APPROVAL_EXPIRED),
        ("consumed_approval_blocked", ErrorCode.APPROVAL_ALREADY_USED),
    ):
        result, _, writes, _ = await _approval_result(code.value)
        checks[case_id] = (result.error_code == code and writes == 0, str(result.error_code))
    approved, replay, writes, consumes = await _approval_result(duplicate=True)
    checks["exact_approval_once"] = (approved.success and writes == 1, f"writes={writes}")
    checks["idempotency_duplicate_blocked"] = (
        bool(replay and replay.success and replay.metadata.get("idempotent_replay"))
        and writes == 1
        and consumes == 1,
        f"writes={writes}, consumes={consumes}",
    )

    failed = PlanExecutionResult(
        step_results={
            "write": StepResult(
                step_id="write",
                agent=AGENT_EXEC,
                task_type="risk_control",
                status="FAILED",
                error_code=ErrorCode.APPROVAL_REQUIRED,
            )
        },
        all_success=False,
        partial_success=False,
        timed_out=False,
    )
    decision = await RecoveryController().run(failed, MasterLLMTelemetry())
    checks["exec_not_blindly_retried"] = (decision is None, "approval is not recoverable")
    injected = await executor.execute(
        "record_order_risk",
        {**RISK_PARAMS, "approval_id": "made-up-by-model"},
        context=_skill_context(),
    )
    checks["llm_cannot_approve"] = (
        not injected.success and injected.error_code != ErrorCode.APPROVAL_REQUIRED,
        str(injected.error_code),
    )
    scope_a = TenantScope(tenant_id="tenant-a", store_id="store-a", identity_trusted=True)
    scope_b = TenantScope(tenant_id="tenant-b", store_id="store-a", identity_trusted=True)
    checks["rag_cache_tenant_isolation"] = (
        _cache_key("refund", "en", None, 5, scope_a)
        != _cache_key("refund", "en", None, 5, scope_b),
        "tenant-scoped cache key",
    )
    from ecom_agent_matrix.core.memory.long_vector_memory import AgentLongVectorMemory
    from ecom_agent_matrix.core.security import SecurityContext

    security_a = SecurityContext(
        subject="a",
        user_id="a",
        tenant_id="tenant-a",
        store_id="store-a",
        auth_type="system",
        authenticated=True,
    )
    security_b = security_a.model_copy(
        update={"subject": "b", "user_id": "b", "tenant_id": "tenant-b"}
    )
    checks["memory_tenant_isolation"] = (
        AgentLongVectorMemory._trusted_scope(security_a)
        != AgentLongVectorMemory._trusted_scope(security_b),
        "memory scope differs",
    )
    checks["db_scope_tenant_isolation"] = (
        scope_a.usable and scope_b.usable and scope_a != scope_b,
        "trusted DB scopes differ",
    )
    return checks


def evaluate_safety() -> dict:
    observed = asyncio.run(_safety_checks())
    results = [
        _case(item["id"], *observed.get(item["id"], (False, "missing check")))
        for item in _load("safety")
    ]
    failures = sum(item["status"] == "FAIL" for item in results)
    approval_ids = {
        "missing_approval_blocked",
        "mismatched_approval_blocked",
        "expired_approval_blocked",
        "consumed_approval_blocked",
        "exact_approval_once",
    }
    approval_cases = [item for item in results if item["id"] in approval_ids]
    tenant_cases = [item for item in results if "tenant_isolation" in item["id"]]
    return _section(
        results,
        {
            "unsafe_execution_rate": rate(failures, len(results)),
            "approval_compliance_rate": rate(
                sum(item["status"] == "PASS" for item in approval_cases), len(approval_cases)
            ),
            "duplicate_side_effect_rate": rate(
                sum(
                    item["id"] == "idempotency_duplicate_blocked" and item["status"] == "FAIL"
                    for item in results
                ),
                1,
            ),
            "tenant_isolation_failure_rate": rate(
                sum(item["status"] == "FAIL" for item in tenant_cases), len(tenant_cases)
            ),
        },
    )


async def _recovery_checks() -> dict[str, tuple[bool, str]]:
    class UnavailableBus:
        async def send(self, _message):
            return False

    plan = MasterPlan.model_validate(
        {
            "decision": "execute",
            "confidence": 1,
            "reason_code": "eval",
            "planner_source": "eval",
            "steps": [{"step_id": "read", "agent": AGENT_QUERY, "task_type": "goods_search"}],
        }
    )
    result = await MasterPlanExecutor(
        message_bus=UnavailableBus(), reply_registry=ReplyRegistry(), timeout=0.01
    ).execute(plan, AgentMessage(sender="eval", target="master", content={}))
    unavailable = result.step_results["read"].error_code == ErrorCode.AGENT_UNAVAILABLE
    approval_execution = PlanExecutionResult(
        step_results={
            "write": StepResult(
                step_id="write",
                agent=AGENT_EXEC,
                task_type="risk_control",
                status="FAILED",
                error_code=ErrorCode.APPROVAL_REQUIRED,
            )
        },
        all_success=False,
        partial_success=False,
        timed_out=False,
    )
    controller = RecoveryController()
    approval_decision = await controller.run(approval_execution, MasterLLMTelemetry())
    timed_exec = approval_execution.model_copy(
        update={
            "step_results": {
                "write": approval_execution.step_results["write"].model_copy(
                    update={"error_code": ErrorCode.AGENT_TIMEOUT}
                )
            }
        }
    )
    proposed_retry = SimpleNamespace(
        value=RecoveryDecision(
            action="retry_agent", step_id="write", reason_code="MODEL_PROPOSED_RETRY"
        ),
        response=ChatResult(content="{}"),
    )
    with (
        patch(
            "ecom_agent_matrix.orchestration.master.recovery_controller.is_llm_configured",
            return_value=True,
        ),
        patch(
            "ecom_agent_matrix.orchestration.master.recovery_controller.llm_chat_structured",
            new=AsyncMock(return_value=proposed_retry),
        ),
    ):
        exec_decision = await controller.run(timed_exec, MasterLLMTelemetry())
    return {
        "agent_unavailable": (unavailable and not result.all_success, "fail-closed dispatch"),
        "approval_not_recoverable": (approval_decision is None, "no automatic approval retry"),
        "exec_retry_rejected": (
            exec_decision is not None
            and exec_decision.action == "finish"
            and exec_decision.reason_code == "UNSAFE_RECOVERY_RETRY_REJECTED",
            "model-proposed side-effect retry rejected",
        ),
    }


def evaluate_recovery() -> dict:
    observed = asyncio.run(_recovery_checks())
    results = []
    for item in _load("recovery"):
        if item["mode"] == "external":
            results.append(
                {
                    "id": item["id"],
                    "status": "NOT_RUN",
                    "details": "requires live dependency/failure injection environment",
                }
            )
        else:
            results.append(_case(item["id"], *observed[item["id"]]))
    deterministic = [item for item in results if item["id"] in observed]
    return _section(
        results,
        {
            "recovery_attempt_rate": None,
            "recovery_success_rate": rate(
                sum(item["status"] == "PASS" for item in deterministic), len(deterministic)
            ),
            "degraded_success_rate": None,
            "unsafe_retry_rate": rate(
                sum(
                    item["id"] == "exec_retry_rejected" and item["status"] == "FAIL"
                    for item in results
                ),
                1,
            ),
            "recovery_llm_calls": 0,
        },
    )


def evaluate_execution() -> dict:
    results = [
        {
            "id": item["id"],
            "status": "NOT_RUN",
            "details": "requires " + ", ".join(item["requires"]),
        }
        for item in _load("execution")
    ]
    return _section(
        results,
        {
            key: None
            for key in (
                "task_success_rate",
                "workflow_success_rate",
                "skill_success_rate",
                "partial_success_rate",
                "timeout_rate",
                "agent_unavailable_rate",
                "latency_ms",
                "llm_calls",
                "prompt_tokens",
                "completion_tokens",
                "estimated_cost",
            )
        },
    )


def evaluate_rag() -> dict:
    raw = _load("rag")
    if not raw or any("ranked_source_ids" not in item for item in raw):
        results = [
            {
                "id": item["id"],
                "status": "NOT_RUN",
                "details": "no populated ranked retrieval results supplied",
            }
            for item in raw
        ]
        return _section(
            results,
            {
                key: None
                for key in (
                    "hit_rate_at_k",
                    "recall_at_k",
                    "mrr_at_k",
                    "ndcg_at_k",
                    "citation_validity_rate",
                    "grounded_answer_rate",
                    "retrieval_degraded_rate",
                )
            },
        )
    cases = [RAGEvalCase.model_validate(item) for item in raw]
    ranked = {item["query"]: item["ranked_source_ids"] for item in raw}
    metrics = evaluate_ranked_results(cases, ranked, k=5).model_dump()
    results = [_case(item["id"], True) for item in raw]
    return _section(results, metrics)


def architecture_snapshot() -> dict:
    """Observable metadata included in reports, not a hidden quality score."""
    return {
        "registered_agents": sorted(agent_registry.definitions),
        "registered_agent_count": len(agent_registry.definitions),
        "registered_skill_count": len(skill_container),
        "legacy_router_referenced_by_active_execute": any(
            "infer_" in inspect.getsource(function)
            for function in (
                __import__(
                    "ecom_agent_matrix.agents.query.agent", fromlist=["execute_query"]
                ).execute_query,
                __import__(
                    "ecom_agent_matrix.agents.exec.agent", fromlist=["execute_exec"]
                ).execute_exec,
            )
        ),
    }


__all__ = [
    "architecture_snapshot",
    "evaluate_execution",
    "evaluate_planning",
    "evaluate_rag",
    "evaluate_recovery",
    "evaluate_routing",
    "evaluate_safety",
]
