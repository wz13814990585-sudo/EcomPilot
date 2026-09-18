from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from ecom_agent_matrix.api.route_warn import competitor_warn
from ecom_agent_matrix.api.schemas import CompetitorWarnRequest
from ecom_agent_matrix.core.security import SecurityContext, authorize_task
from ecom_agent_matrix.core.security.errors import AuthorizationError
from ecom_agent_matrix.config.constants import AGENT_MASTER
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.orchestration.master.orchestrator import process_master_task


def _security(role: str) -> SecurityContext:
    return SecurityContext(
        subject="s",
        user_id="u",
        tenant_id="t",
        store_id="store",
        roles=frozenset({role}),
        scopes=frozenset(),
        auth_type="jwt",
        authenticated=True,
    )


def test_role_task_matrix_and_unknown_fail_closed():
    viewer = _security("viewer")
    authorize_task(viewer, "knowledge_qa")
    authorize_task(viewer, "order_query")
    with pytest.raises(AuthorizationError):
        authorize_task(viewer, "ad_optimize")

    operator = _security("operator")
    authorize_task(operator, "ad_optimize")
    with pytest.raises(AuthorizationError):
        authorize_task(operator, "risk_control")

    authorize_task(_security("risk_operator"), "risk_control")
    admin = _security("admin")
    for task_type in (
        "knowledge_qa",
        "goods_search",
        "stock_analysis",
        "competitor_watch",
        "order_query",
        "social_marketing",
        "customer_service",
        "ad_optimize",
        "ops_report",
        "risk_control",
        "data_check",
    ):
        authorize_task(admin, task_type)
    with pytest.raises(AuthorizationError):
        authorize_task(admin, "unknown_task")


def test_direct_query_route_cannot_bypass_rbac():
    unauthorized = _security("custom")
    body = CompetitorWarnRequest(sku="SKU-1", competitor="Temu", via_master=False)
    with patch("ecom_agent_matrix.api.route_warn.dispatch_and_wait", new=AsyncMock()) as dispatch:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(competitor_warn(body, security=unauthorized))
    assert exc.value.status_code == 403
    dispatch.assert_not_awaited()


def test_direct_competitor_route_sets_explicit_task_type_without_query():
    body = CompetitorWarnRequest(sku="SKU-BAG-001", competitor="Temu", via_master=False)
    response = {
        "task_id": "task-1",
        "target": "data_query",
        "reply_from": "data_query",
        "success": True,
        "data": {},
        "error_code": None,
    }
    with patch(
        "ecom_agent_matrix.api.route_warn.dispatch_and_wait",
        new=AsyncMock(return_value=response),
    ) as dispatch:
        result = asyncio.run(competitor_warn(body, security=_security("admin"), approval=None))

    assert result.success
    assert dispatch.await_args.kwargs["content"]["task_type"] == "competitor_watch"


def test_master_fast_path_denies_before_agent_dispatch():
    viewer = _security("viewer")
    request = AgentMessage(
        task_id="root",
        sender="api_gateway",
        target=AGENT_MASTER,
        content={"task_type": "ad_optimize", "query": "optimize ads"},
        security=viewer,
    )
    sent = []

    async def send(message):
        sent.append(message)
        return True

    with (
        patch(
            "ecom_agent_matrix.orchestration.master.orchestrator._react_call_one",
            new=AsyncMock(),
        ) as dispatch,
        patch(
            "ecom_agent_matrix.orchestration.master.orchestrator.message_bus.send",
            new=AsyncMock(side_effect=send),
        ),
    ):
        asyncio.run(process_master_task(request, AsyncMock()))
    dispatch.assert_not_awaited()
    assert sent[0].content["success"] is False
    assert sent[0].content["data"]["error_code"] == "PERMISSION_DENIED"
