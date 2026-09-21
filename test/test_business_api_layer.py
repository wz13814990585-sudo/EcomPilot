from __future__ import annotations

import asyncio

from ecom_agent_matrix.agents.query.agent import execute_query
from ecom_agent_matrix.config.constants import AGENT_QUERY
from ecom_agent_matrix.core.errors import ErrorCode
from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.core.skill.executor import SkillExecutor
from ecom_agent_matrix.core.skill.skill_registry import (
    SkillExecutionContext,
    skill_execution_context,
)
from ecom_agent_matrix.core.tasking import normalize_task_context
from ecom_agent_matrix.modules.business_api import DemoBusinessAPIClient
from ecom_agent_matrix.modules.skills.business_api import BusinessAPIWriteTool


def _security() -> SecurityContext:
    return SecurityContext(
        subject="subject",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        auth_type="jwt",
        authenticated=True,
    )


def test_demo_adapter_is_explicit_and_does_not_fabricate_unknown_resources():
    client = DemoBusinessAPIClient()
    known = asyncio.run(client.get_order("ORD-20260301-001"))
    missing = asyncio.run(client.get_order("ORD-NOT-THERE"))
    assert known.demo is True
    assert known.provider == "demo-business-api"
    assert known.fields["status"] == "shipped"
    assert missing.found is False
    assert missing.fields == {}


def test_order_query_uses_read_business_api_and_returns_api_evidence():
    security = _security()
    ctx = normalize_task_context(
        {"task_type": "order_query", "query": "查看 ORD-20260301-001 当前状态"},
        task_id="task-api-read",
        security=security,
    )
    with skill_execution_context(AGENT_QUERY, task_context=ctx, security=security):
        result = asyncio.run(execute_query(ctx, security=security))
    assert result.success is True
    assert result.data["provider"] == "demo-business-api"
    assert result.data["demo"] is True
    assert result.data["evidence"]["source_type"] == "api"
    assert result.data["evidence"]["tenant_id"] == "tenant-a"


def test_query_agent_cannot_invoke_business_api_write():
    context = SkillExecutionContext(
        agent_id=AGENT_QUERY,
        task_id="task-write",
        tenant_id="tenant-a",
        store_id="store-a",
        user_id="user-a",
        roles=frozenset({"admin"}),
        identity_trusted=True,
    )
    result = asyncio.run(
        SkillExecutor().execute(
            "business_api_write",
            {
                "operation": "mark_order_risk",
                "resource_id": "ORD-20260301-001",
                "fields": {"risk_status": "flagged"},
            },
            context=context,
        )
    )
    assert result.success is False
    assert result.error_code == ErrorCode.PERMISSION_DENIED


def test_business_api_write_contract_requires_exec_approval_and_idempotency():
    spec = BusinessAPIWriteTool.spec()
    assert spec.read_only is False
    assert spec.side_effect is True
    assert spec.approval_required is True
    assert spec.idempotent is True
    assert spec.required_scopes == frozenset({"risk:write"})
