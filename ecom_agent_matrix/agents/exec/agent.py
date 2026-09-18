"""Exec agent adapter and typed workflow dispatch."""

from __future__ import annotations

import asyncio
import time

from ecom_agent_matrix.config.constants import AGENT_EXEC
from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.logging_config import setup_logger
from ecom_agent_matrix.runtime.messaging.bus import message_bus
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.registry import register_agent
from ecom_agent_matrix.runtime.messaging.reply import build_reply
from ecom_agent_matrix.core.skill.skill_registry import skill_execution_context
from ecom_agent_matrix.core.tasking import (
    TaskContext,
    ensure_task_context,
    normalize_task_context,
)
from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.core.security import ApprovalGrant
from ecom_agent_matrix.core.security import require_trusted_ingress
from ecom_agent_matrix.core.tasking import WorkflowResult
from ecom_agent_matrix.workflows.advertising import run_ad_workflow
from ecom_agent_matrix.workflows.crm import run_crm_workflow
from ecom_agent_matrix.workflows.report import run_report_workflow
from ecom_agent_matrix.workflows.risk import run_risk_workflow
from ecom_agent_matrix.workflows.social import run_social_workflow
from ecom_agent_matrix.agents.legacy_routing import infer_exec_kind
from ecom_agent_matrix.platform.observability.context import TraceContext, set_trace_context
from ecom_agent_matrix.platform.observability.metrics import metrics

logger = setup_logger("agent.exec")

_task_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _task_semaphore
    if _task_semaphore is None:
        _task_semaphore = asyncio.Semaphore(int(settings.EXEC_MAX_CONCURRENT))
    return _task_semaphore


async def run_exec(
    task: dict | TaskContext,
    *,
    task_id: str = "",
    security: SecurityContext | None = None,
    approval: ApprovalGrant | None = None,
) -> tuple[bool, str, dict]:
    started = time.perf_counter()
    ctx = task if isinstance(task, TaskContext) else ensure_task_context(task)
    if task_id and not isinstance(task, TaskContext):
        ctx = ctx.with_updates(task_id=task_id.strip())
    set_trace_context(
        TraceContext.from_identity(
            task_id=ctx.task_id,
            correlation_id=ctx.correlation_id,
            agent_id=AGENT_EXEC,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
    )
    with skill_execution_context(
        AGENT_EXEC, task_context=ctx, security=security, approval=approval
    ):
        result = await execute_exec(ctx)
    legacy = result.as_legacy_tuple()
    metrics.observe_agent(AGENT_EXEC, result.success, time.perf_counter() - started)
    return legacy


async def execute_exec(ctx: TaskContext) -> WorkflowResult:
    task_type = str(ctx.task_type or "").strip()
    kind = {
        "ad_optimize": "ad",
        "ops_report": "report",
        "risk_control": "risk",
        "social_marketing": "social",
        "customer_service": "crm",
    }.get(task_type)
    if kind is None and not task_type:
        kind = infer_exec_kind(ctx)
    if kind is None:
        return WorkflowResult(
            success=False,
            error_code="UNSUPPORTED_TASK",
            error_msg="Unsupported execution task",
        )
    if kind == "ad":
        return await run_ad_workflow(ctx)
    if kind == "report":
        return await run_report_workflow(ctx)
    if kind == "risk":
        return await run_risk_workflow(ctx)
    if kind == "social":
        return await run_social_workflow(ctx)
    return await run_crm_workflow(ctx, task_id=ctx.task_id)


@register_agent(AGENT_EXEC)
async def exec_agent(msg_queue: asyncio.Queue):
    """业务执行：调出价、出报表、触发风控、生成文案/客服答复。"""
    logger.info(
        "exec_agent_started",
        extra={"event": "exec_agent_started", "agent": AGENT_EXEC},
    )
    sem = _get_semaphore()

    while True:
        msg: AgentMessage = await msg_queue.get()
        started = time.perf_counter()
        set_trace_context(
            TraceContext.from_identity(
                task_id=msg.task_id,
                correlation_id=msg.correlation_id,
                agent_id=AGENT_EXEC,
                tenant_id=getattr(msg.security, "tenant_id", ""),
                user_id=getattr(msg.security, "user_id", ""),
            )
        )
        try:
            require_trusted_ingress(msg.security, app_env=settings.APP_ENV)
            async with sem:
                ctx = normalize_task_context(
                    msg.content or {},
                    task_id=msg.task_id,
                    correlation_id=msg.correlation_id,
                    source_agent=AGENT_EXEC,
                    security=msg.security,
                )
                with skill_execution_context(
                    AGENT_EXEC, task_context=ctx, security=msg.security, approval=msg.approval
                ):
                    result = await asyncio.wait_for(
                        execute_exec(ctx), timeout=float(settings.EXEC_SKILL_TIMEOUT)
                    )
                ok, err = result.success, result.error_msg
                data = {
                    **result.data,
                    **({"error_code": str(result.error_code)} if result.error_code else {}),
                }
                elapsed_ms = (time.perf_counter() - started) * 1000
                data = {
                    **(data or {}),
                    "latency_ms": data.get("latency_ms") or round(elapsed_ms, 2),
                }
                reply = build_reply(
                    msg,
                    sender=AGENT_EXEC,
                    success=ok,
                    error_msg=err or "",
                    data=data,
                )
                await message_bus.send(reply)
                logger.info(
                    "exec_task_done",
                    extra={
                        "event": "exec_task_done",
                        "task_id": msg.task_id,
                        "agent": AGENT_EXEC,
                        "workflow": data.get("exec_kind") or "",
                        "latency_ms": round(elapsed_ms, 2),
                    },
                )
        except asyncio.TimeoutError:
            reply = build_reply(
                msg,
                sender=AGENT_EXEC,
                success=False,
                error_msg=f"biz_exec 超时（>{settings.EXEC_SKILL_TIMEOUT}s）",
                data={},
            )
            await message_bus.send(reply)
        except Exception as exc:
            logger.exception(
                "exec_task_failed",
                extra={
                    "event": "exec_task_failed",
                    "task_id": msg.task_id,
                    "agent": AGENT_EXEC,
                    "error_type": type(exc).__name__,
                },
            )
            reply = build_reply(
                msg,
                sender=AGENT_EXEC,
                success=False,
                error_msg="biz_exec 内部执行失败",
                data={"error_code": "EXECUTION_ERROR"},
            )
            await message_bus.send(reply)
        finally:
            msg_queue.task_done()
