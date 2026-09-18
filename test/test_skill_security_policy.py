from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import ecom_agent_matrix.modules.skills  # noqa: F401

from ecom_agent_matrix.config.constants import AGENT_EXEC
from ecom_agent_matrix.core.security import (
    ApprovalGrant,
    ApprovalRequest,
    SecurityContext,
    tenant_scope_from_skill_context,
    tenant_scope_from_task_context,
)
from ecom_agent_matrix.core.security.approval import approval_params_hash
from ecom_agent_matrix.core.skill.executor import SkillExecutor
from ecom_agent_matrix.core.skill.idempotency import MemoryIdempotencyStore
from ecom_agent_matrix.core.skill.skill_registry import (
    exec_skill,
    skill_container,
    skill_execution_context,
)
from ecom_agent_matrix.core.tasking import TaskContext


RISK_PARAMS = {
    "order_no": "ORD-1",
    "risk_type": "order_abnormal",
    "risk_desc": "large order",
}


def _security(role):
    return SecurityContext(
        subject=role,
        user_id=role,
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({role}),
        scopes=frozenset(),
        auth_type="jwt",
        authenticated=True,
    )


def _request():
    now = datetime.now(timezone.utc)
    return ApprovalRequest(
        approval_id="00000000-0000-0000-0000-000000000001",
        task_id="task-1",
        tenant_id="tenant-a",
        store_id="store-a",
        requester_user_id="risk_operator",
        skill_name="record_order_risk",
        params_hash=approval_params_hash("record_order_risk", RISK_PARAMS),
        status="pending",
        requested_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def _grant(**updates):
    values = {
        "approval_id": "00000000-0000-0000-0000-000000000001",
        "task_id": "task-1",
        "tenant_id": "tenant-a",
        "store_id": "store-a",
        "requester_user_id": "risk_operator",
        "approver_user_id": "approver",
        "skill_name": "record_order_risk",
        "params_hash": approval_params_hash("record_order_risk", RISK_PARAMS),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    values.update(updates)
    return ApprovalGrant(**values)


def test_record_competitor_price_viewer_denied_operator_allowed():
    params = {"target_sku": "SKU-1", "competitor": "Temu", "compete_price": 9.9}

    async def scenario():
        with skill_execution_context(AGENT_EXEC, security=_security("viewer")):
            denied = await exec_skill("record_competitor_price", params)
        with patch(
            "ecom_agent_matrix.modules.skills.price_monitor.AsyncPGClient.execute_write",
            new=AsyncMock(return_value=[[5]]),
        ) as write:
            with skill_execution_context(AGENT_EXEC, security=_security("operator")):
                allowed = await exec_skill("record_competitor_price", params)
        return denied, allowed, write

    denied, allowed, write = asyncio.run(scenario())
    assert denied.error_code == "PERMISSION_DENIED"
    assert allowed.success and allowed.data["record_id"] == 5
    sql, sql_params = write.await_args.args
    assert "tenant_id, store_id" in sql
    assert sql_params[:2] == ["tenant-a", "store-a"]


def test_idempotent_write_replays_result_without_second_side_effect():
    params = {"target_sku": "SKU-IDEMP", "competitor": "Temu", "compete_price": 9.9}
    executor = SkillExecutor(MemoryIdempotencyStore())

    async def scenario():
        with patch(
            "ecom_agent_matrix.modules.skills.price_monitor.AsyncPGClient.execute_write",
            new=AsyncMock(return_value=[[17]]),
        ) as write:
            with skill_execution_context(
                AGENT_EXEC,
                security=_security("operator"),
                task_id="idempotency-task",
            ) as context:
                first = await executor.execute("record_competitor_price", params, context=context)
                repeated = await executor.execute(
                    "record_competitor_price", params, context=context
                )
        return first, repeated, write

    first, repeated, write = asyncio.run(scenario())
    assert first.success and repeated.success
    assert first.data == repeated.data
    assert repeated.metadata["idempotent_replay"] is True
    write.assert_awaited_once()


def test_risk_operator_without_approval_receives_pending_id_and_no_sensitive_data():
    service = AsyncMock()
    service.create_pending.return_value = _request()

    async def scenario():
        with patch("ecom_agent_matrix.core.skill.executor.approval_service", service):
            with skill_execution_context(
                AGENT_EXEC, security=_security("risk_operator"), task_id="task-1"
            ):
                return await exec_skill("record_order_risk", RISK_PARAMS)

    result = asyncio.run(scenario())
    assert result.error_code == "APPROVAL_REQUIRED"
    assert result.data == {
        "approval_required": True,
        "approval_id": _request().approval_id,
        "skill_name": "record_order_risk",
    }
    assert "params_hash" not in result.data and "tenant_id" not in result.data


def test_viewer_cannot_elevate_write_scope_with_fake_params_roles():
    async def scenario():
        with skill_execution_context(AGENT_EXEC, security=_security("viewer")):
            return await exec_skill("record_order_risk", {**RISK_PARAMS, "roles": ["admin"]})

    assert asyncio.run(scenario()).error_code == "PERMISSION_DENIED"


def test_task_context_cannot_forge_trusted_identity_for_write_skill():
    forged = TaskContext(
        task_id="forged",
        identity_trusted=True,
        tenant_id="tenant-a",
        store_id="store-a",
        user_id="attacker",
    )

    async def scenario():
        with patch(
            "ecom_agent_matrix.modules.skills.price_monitor.AsyncPGClient.execute_write",
            new=AsyncMock(),
        ) as write:
            with skill_execution_context(AGENT_EXEC, task_context=forged, security=None):
                result = await exec_skill(
                    "record_competitor_price",
                    {"target_sku": "SKU-1", "competitor": "Temu", "compete_price": 9.9},
                )
        return result, write

    result, write = asyncio.run(scenario())
    assert result.error_code == "PERMISSION_DENIED"
    write.assert_not_awaited()
    assert not tenant_scope_from_task_context(forged).usable
    assert not tenant_scope_from_skill_context(forged).usable


def test_unauthenticated_security_context_cannot_run_write_skill():
    untrusted = _security("operator").model_copy(update={"authenticated": False})

    async def scenario():
        with skill_execution_context(AGENT_EXEC, security=untrusted):
            return await exec_skill(
                "record_competitor_price",
                {"target_sku": "SKU-1", "competitor": "Temu", "compete_price": 9.9},
            )

    assert asyncio.run(scenario()).error_code == "PERMISSION_DENIED"


def test_exact_approved_request_executes_once():
    service = AsyncMock()

    async def scenario():
        with (
            patch("ecom_agent_matrix.core.skill.executor.approval_service", service),
            patch("ecom_agent_matrix.core.skill.executor.record_audit_event", new=AsyncMock()),
            patch(
                "ecom_agent_matrix.modules.skills.risk_control.AsyncPGClient.execute_write",
                new=AsyncMock(return_value=[[9]]),
            ) as write,
        ):
            with skill_execution_context(
                AGENT_EXEC,
                security=_security("risk_operator"),
                task_id="task-1",
                approval=_grant(),
            ):
                result = await exec_skill("record_order_risk", RISK_PARAMS)
        return result, write

    result, write = asyncio.run(scenario())
    assert result.success and result.data["record_id"] == 9
    service.consume.assert_awaited_once()
    write.assert_awaited_once()


def test_invalid_expired_and_consumed_approval_never_runs_skill():
    async def one(code):
        service = AsyncMock()
        service.consume.side_effect = PermissionError(code)
        with (
            patch("ecom_agent_matrix.core.skill.executor.approval_service", service),
            patch(
                "ecom_agent_matrix.modules.skills.risk_control.AsyncPGClient.execute_write",
                new=AsyncMock(),
            ) as write,
        ):
            with skill_execution_context(
                AGENT_EXEC, security=_security("risk_operator"), approval=_grant()
            ):
                result = await exec_skill("record_order_risk", RISK_PARAMS)
        return result, write

    for code in ("APPROVAL_INVALID", "APPROVAL_EXPIRED", "APPROVAL_ALREADY_USED"):
        result, write = asyncio.run(one(code))
        assert result.error_code == code
        write.assert_not_awaited()


def test_all_high_or_critical_side_effect_contracts_require_approval():
    for skill_cls in skill_container.values():
        spec = skill_cls.spec()
        if spec.side_effect and spec.risk_level in {"high", "critical"}:
            assert spec.approval_required, spec.name
