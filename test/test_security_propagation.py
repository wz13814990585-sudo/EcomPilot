from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ecom_agent_matrix.config.constants import AGENT_EXEC, AGENT_MASTER, AGENT_QUERY, AGENT_RAG
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply import build_reply
from ecom_agent_matrix.runtime.messaging.replies import resolve_task_reply
from ecom_agent_matrix.core.security import ApprovalGrant, SecurityContext
from ecom_agent_matrix.core.security.errors import AuthorizationError
from ecom_agent_matrix.application import AgentApplicationService
from ecom_agent_matrix.runtime.messaging.replies import gateway_replies
from ecom_agent_matrix.orchestration.master.schemas import (
    PlanExecutionResult,
    StepResult,
)
from ecom_agent_matrix.orchestration.master.executor import MasterPlanExecutor
from ecom_agent_matrix.orchestration.master.schemas import MasterPlan, PlanStep
from ecom_agent_matrix.orchestration.master.orchestrator import execute_fast_path
from ecom_agent_matrix.orchestration.master.router import MasterRouteDecision


def _admin() -> SecurityContext:
    return SecurityContext(
        subject="s",
        user_id="u",
        tenant_id="t",
        store_id="store",
        roles=frozenset({"admin"}),
        scopes=frozenset(),
        auth_type="jwt",
        authenticated=True,
    )


def _root(security=None) -> AgentMessage:
    return AgentMessage(
        task_id="root",
        correlation_id="gateway",
        sender="api_gateway",
        target=AGENT_MASTER,
        content={"query": "q"},
        security=security,
    )


def _approval() -> ApprovalGrant:
    return ApprovalGrant(
        approval_id="00000000-0000-0000-0000-000000000001",
        task_id="root",
        tenant_id="t",
        store_id="store",
        requester_user_id="u",
        approver_user_id="approver",
        skill_name="record_order_risk",
        params_hash="a" * 64,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


def test_reply_inherits_envelope_security_but_not_business_data():
    security = _admin()
    reply = build_reply(_root(security), AGENT_MASTER, success=True, data={"ok": True})
    assert reply.security is security
    assert "security" not in reply.content["data"]
    assert "tenant_id" not in reply.content["data"]


def test_application_service_places_security_on_root_agent_message():
    security = _admin()
    captured = []

    async def send(message):
        captured.append(message)
        gateway_replies.resolve(
            message.task_id,
            AgentMessage(
                task_id=message.task_id,
                sender=AGENT_MASTER,
                target="api_gateway",
                content={"success": True, "data": {"summary": "ok"}, "type": "result"},
            ),
        )
        return True

    service = AgentApplicationService(
        message_bus=SimpleNamespace(send=send),
        agent_registry=SimpleNamespace(definitions={AGENT_MASTER: object()}),
    )
    asyncio.run(
        service.execute(
            target=AGENT_MASTER,
            content={"query": "q"},
            priority=1,
            security=security,
        )
    )
    assert captured[0].security is security


def test_application_service_places_verified_approval_on_trusted_envelope():
    security = _admin()
    grant = _approval()
    captured = []

    async def send(message):
        captured.append(message)
        gateway_replies.resolve(
            message.task_id,
            AgentMessage(
                task_id=message.task_id,
                sender=AGENT_MASTER,
                target="api_gateway",
                content={"success": True, "data": {}, "type": "result"},
            ),
        )
        return True

    service = AgentApplicationService(
        message_bus=SimpleNamespace(send=send),
        agent_registry=SimpleNamespace(definitions={AGENT_MASTER: object()}),
    )
    asyncio.run(
        service.execute(
            target=AGENT_MASTER,
            content={"approval_id": "fake"},
            priority=1,
            security=security,
            approval=grant,
        )
    )
    assert captured[0].approval is grant
    assert captured[0].content["approval_id"] == "fake"  # payload cannot replace envelope


def test_fast_path_child_preserves_security():
    security = _admin()
    captured = []

    async def dispatch(task_id, correlation_id, target, payload, priority, child_security):
        captured.append(child_security)
        request = AgentMessage(
            task_id=task_id,
            correlation_id=correlation_id,
            sender=AGENT_MASTER,
            target=target,
            content=payload,
            security=child_security,
        )
        resolve_task_reply(build_reply(request, target, success=True, data={"answer": "ok"}))

    route = MasterRouteDecision(
        mode="fast_path",
        task_type="knowledge_qa",
        target_agents=[AGENT_RAG],
        confidence=1,
        reason_code="test",
    )
    with patch(
        "ecom_agent_matrix.orchestration.master.orchestrator._dispatch_subtask",
        new=AsyncMock(side_effect=dispatch),
    ):
        asyncio.run(execute_fast_path(_root(security), route))
    assert captured == [security]


def test_dag_query_rag_exec_children_all_preserve_security():
    security = _admin()
    captured = []
    plan = MasterPlan(
        decision="execute",
        confidence=1,
        reason_code="test",
        planner_source="test",
        steps=[
            PlanStep(step_id="query_data", agent=AGENT_QUERY, task_type="order_query"),
            PlanStep(step_id="policy_data", agent=AGENT_RAG, task_type="knowledge_qa"),
            PlanStep(step_id="reply_customer", agent=AGENT_EXEC, task_type="customer_service"),
        ],
    )

    async def send(child):
        captured.append(child.security)
        resolve_task_reply(build_reply(child, child.target, success=True, data={}))
        return True

    with patch(
        "ecom_agent_matrix.orchestration.master.executor.message_bus.send",
        new=AsyncMock(side_effect=send),
    ):
        result = asyncio.run(MasterPlanExecutor().execute(plan, _root(security)))
    assert result.all_success and captured == [security, security, security]


def test_planner_step_cannot_elevate_viewer_permissions():
    viewer = _admin().model_copy(update={"roles": frozenset({"viewer"})})
    plan = MasterPlan(
        decision="execute",
        confidence=1,
        reason_code="test",
        planner_source="llm",
        steps=[PlanStep(step_id="write_risk", agent=AGENT_EXEC, task_type="risk_control")],
    )
    with patch(
        "ecom_agent_matrix.orchestration.master.executor.message_bus.send",
        new=AsyncMock(),
    ) as send:
        with pytest.raises(AuthorizationError):
            asyncio.run(MasterPlanExecutor().execute(plan, _root(viewer)))
    send.assert_not_awaited()


def test_recovery_resume_child_preserves_root_security():
    security = _admin()
    plan = MasterPlan(
        decision="execute",
        confidence=1,
        reason_code="test",
        planner_source="test",
        steps=[PlanStep(step_id="query_data", agent=AGENT_QUERY, task_type="order_query")],
    )
    previous = PlanExecutionResult(
        step_results={
            "query_data": StepResult(
                step_id="query_data",
                agent=AGENT_QUERY,
                task_type="order_query",
                status="FAILED",
                error_code="AGENT_TIMEOUT",
            )
        },
        all_success=False,
        partial_success=False,
        timed_out=True,
    )
    captured = []

    async def send(child):
        captured.append(child.security)
        resolve_task_reply(build_reply(child, child.target, success=True, data={}))
        return True

    with patch(
        "ecom_agent_matrix.orchestration.master.executor.message_bus.send",
        new=AsyncMock(side_effect=send),
    ):
        result = asyncio.run(
            MasterPlanExecutor().resume(
                plan,
                _root(security),
                previous,
                retry_step_ids={"query_data"},
            )
        )
    assert result.all_success and captured == [security]
