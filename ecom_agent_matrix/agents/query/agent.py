"""Query agent adapter and typed workflow dispatch."""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy

from ...config.constants import AGENT_QUERY
from ...config.settings import settings
from ...core.logging_config import setup_logger
from ...core.errors import ErrorCode
from ...runtime.messaging.bus import message_bus
from ...runtime.messaging.message import AgentMessage
from ...runtime.messaging.registry import register_agent
from ...runtime.messaging.reply import build_reply
from ...core.skill.skill_registry import skill_execution_context
from ...core.tasking import (
    TaskContext,
    ensure_task_context,
    normalize_task_context,
)
from ...core.security import SecurityContext
from ...core.security import ApprovalGrant
from ...core.security import require_trusted_ingress
from ...core.tasking import WorkflowResult
from ...workflows.data_check import run_data_check_workflow
from ...workflows.goods import run_goods_workflow
from ...workflows.competitor import run_competitor_workflow
from ...workflows.stock import run_stock_workflow
from ...modules.parsers.stock import extract_stock_sku
from ...platform.observability.context import TraceContext, set_trace_context
from ...platform.observability.metrics import metrics

logger = setup_logger("agent.query")

_task_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _task_semaphore
    if _task_semaphore is None:
        _task_semaphore = asyncio.Semaphore(int(settings.QUERY_MAX_CONCURRENT))
    return _task_semaphore


async def _ensure_sku(ctx: TaskContext) -> tuple[TaskContext, WorkflowResult | None]:
    """缺 SKU 时先走商品检索，并返回新的 TaskContext。"""
    parsed_sku = extract_stock_sku(ctx)
    if parsed_sku:
        return (ctx if ctx.sku == parsed_sku else ctx.with_updates(sku=parsed_sku)), None
    goods = await run_goods_workflow(ctx)
    goods_data = goods.data
    if not goods.success or not goods_data.get("best_sku"):
        return ctx, WorkflowResult(
            success=False,
            error_code=goods.error_code or ErrorCode.SKILL_FAILED.value,
            error_msg=goods.error_msg or "未找到匹配商品，无法继续查询",
            data={**goods_data, "query_kind": goods_data.get("query_kind") or "goods"},
            metadata=goods.metadata,
        )
    sku = goods_data["best_sku"]
    new_params = deepcopy(ctx.params)
    new_params.update(
        {
            "candidates": goods_data.get("candidates") or [],
            "_goods": goods_data,
        }
    )
    return ctx.with_updates(sku=sku, params=new_params), None


async def run_query(
    task: dict | TaskContext,
    *,
    security: SecurityContext | None = None,
    approval: ApprovalGrant | None = None,
) -> tuple[bool, str, dict]:
    """执行一次只读查询（可供单测直接调用）。"""
    started = time.perf_counter()
    ctx = ensure_task_context(task)
    set_trace_context(
        TraceContext.from_identity(
            task_id=ctx.task_id,
            correlation_id=ctx.correlation_id,
            agent_id=AGENT_QUERY,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
    )
    with skill_execution_context(
        AGENT_QUERY, task_context=ctx, security=security, approval=approval
    ):
        typed = await execute_query(ctx)
        result = typed.as_legacy_tuple()  # Deprecated compatibility API; workers stay typed.
    metrics.observe_agent(AGENT_QUERY, result[0], time.perf_counter() - started)
    return result


async def execute_query(ctx: TaskContext) -> WorkflowResult:
    """Query workflow 实现；调用的所有 Skill 继承统一只读上下文。"""
    task_type = str(ctx.task_type or "").strip()
    kind = {
        "goods_catalog": "goods",
        "goods_search": "goods",
        "stock_analysis": "stock",
        "competitor_watch": "competitor",
        "data_check": "data_check",
        "order_query": "data_check",
        "ad_query": "data_check",
    }.get(task_type)
    if kind is None:
        return WorkflowResult(
            success=False,
            error_code=ErrorCode.UNSUPPORTED_TASK.value,
            error_msg="Unsupported query task",
        )
    if kind == "goods":
        return await run_goods_workflow(ctx)

    if kind == "stock":
        enriched, early = await _ensure_sku(ctx)
        if early:
            return early
        return await run_stock_workflow(enriched)

    if kind == "competitor":
        enriched, early = await _ensure_sku(ctx)
        if early:
            return early
        if not enriched.competitor and not enriched.params.get("multi_compare"):
            new_params = deepcopy(enriched.params)
            new_params["multi_compare"] = True
            enriched = enriched.with_updates(params=new_params)
        return await run_competitor_workflow(enriched)

    return await run_data_check_workflow(ctx)


@register_agent(AGENT_QUERY)
async def query_agent(msg_queue: asyncio.Queue, *, bus=message_bus):
    """数据查询：广告/订单/库存/竞品/商品目录，只调只读 Skill。"""
    logger.info(
        "query_agent_started",
        extra={"event": "query_agent_started", "agent": AGENT_QUERY},
    )
    sem = _get_semaphore()

    while True:
        msg: AgentMessage = await msg_queue.get()
        started = time.perf_counter()
        set_trace_context(
            TraceContext.from_identity(
                task_id=msg.task_id,
                correlation_id=msg.correlation_id,
                agent_id=AGENT_QUERY,
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
                    source_agent=AGENT_QUERY,
                    security=msg.security,
                )
                with skill_execution_context(
                    AGENT_QUERY, task_context=ctx, security=msg.security, approval=msg.approval
                ):
                    result = await asyncio.wait_for(
                        execute_query(ctx), timeout=float(settings.QUERY_SKILL_TIMEOUT)
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
                    sender=AGENT_QUERY,
                    success=ok,
                    error_msg=err or "",
                    data=data,
                    status=result.status.value,
                )
                await bus.send(reply)
                logger.info(
                    "query_task_done",
                    extra={
                        "event": "query_task_done",
                        "task_id": msg.task_id,
                        "agent": AGENT_QUERY,
                        "workflow": data.get("query_kind") or "",
                        "latency_ms": round(elapsed_ms, 2),
                    },
                )
        except asyncio.TimeoutError:
            reply = build_reply(
                msg,
                sender=AGENT_QUERY,
                success=False,
                error_msg=f"data_query 超时（>{settings.QUERY_SKILL_TIMEOUT}s）",
                data={"error_code": ErrorCode.AGENT_TIMEOUT.value},
            )
            await bus.send(reply)
        except Exception as exc:
            logger.exception(
                "query_task_failed",
                extra={
                    "event": "query_task_failed",
                    "task_id": msg.task_id,
                    "agent": AGENT_QUERY,
                    "error_type": type(exc).__name__,
                },
            )
            reply = build_reply(
                msg,
                sender=AGENT_QUERY,
                success=False,
                error_msg="data_query 内部执行失败",
                data={"error_code": ErrorCode.SKILL_EXECUTION_ERROR.value},
            )
            await bus.send(reply)
        finally:
            msg_queue.task_done()
