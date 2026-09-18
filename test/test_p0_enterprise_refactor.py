"""第一轮 P0 企业级重构回归测试。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.config.constants import AGENT_EXEC, AGENT_MASTER, AGENT_QUERY, AGENT_RAG
from ecom_agent_matrix.core.llm import ChatResult, available_providers, get_llm_provider
from ecom_agent_matrix.core.llm.providers.openai import OpenAIProvider
from ecom_agent_matrix.runtime.messaging.message import AgentMessage
from ecom_agent_matrix.runtime.messaging.reply import build_reply
from ecom_agent_matrix.runtime.messaging.replies import resolve_task_reply, task_replies
from ecom_agent_matrix.core.skill.skill_registry import exec_skill, skill_execution_context
from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.orchestration.master.orchestrator import _react_call_one, process_master_task
from ecom_agent_matrix.orchestration.master.schemas import (
    MasterPlan,
    PlanExecutionResult,
    PlanStep,
    StepResult,
)
from ecom_agent_matrix.orchestration.master.planner import TypedMasterPlanner
from ecom_agent_matrix.orchestration.master.router import route_master_task
from ecom_agent_matrix.orchestration.master.telemetry import MasterLLMTelemetry
from ecom_agent_matrix.agents.query.agent import run_query


def _request(root_id: str, correlation_id: str) -> AgentMessage:
    return AgentMessage(
        task_id=root_id,
        correlation_id=correlation_id,
        sender=AGENT_MASTER,
        target=AGENT_QUERY,
        content={"query": "test"},
    )


def test_same_root_task_different_correlations_do_not_cross_replies():
    async def scenario():
        root_id = "root-shared"
        task_replies.create("corr-a")
        task_replies.create("corr-b")

        reply_b = build_reply(_request(root_id, "corr-b"), AGENT_QUERY, success=True)
        reply_a = build_reply(_request(root_id, "corr-a"), AGENT_QUERY, success=True)
        assert resolve_task_reply(reply_b) is True
        assert resolve_task_reply(reply_a) is True

        got_a, got_b = await asyncio.gather(
            task_replies.wait("corr-a", 0.1),
            task_replies.wait("corr-b", 0.1),
        )
        assert got_a and got_a.correlation_id == "corr-a"
        assert got_b and got_b.correlation_id == "corr-b"
        assert got_a.task_id == root_id and got_b.task_id == root_id
        assert not task_replies.contains("corr-a")
        assert not task_replies.contains("corr-b")

    asyncio.run(scenario())


def test_late_timed_out_reply_is_not_consumed_by_next_react_step():
    async def scenario():
        root_id = "root-timeout"
        task_replies.create("corr-old")
        assert await task_replies.wait("corr-old", 0.001) is None
        assert not task_replies.contains("corr-old")

        task_replies.create("corr-new")
        late = build_reply(_request(root_id, "corr-old"), AGENT_QUERY, success=True)
        current = build_reply(_request(root_id, "corr-new"), AGENT_QUERY, success=True)
        assert resolve_task_reply(late) is False
        assert resolve_task_reply(current) is True
        reply = await task_replies.wait("corr-new", 0.1)
        assert reply and reply.correlation_id == "corr-new"

    asyncio.run(scenario())


def test_waiter_cleans_pending_when_wait_is_cancelled():
    async def scenario():
        correlation_id = "corr-cancelled-wait"
        task_replies.create(correlation_id)
        task = asyncio.create_task(task_replies.wait(correlation_id, 60))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
            raise AssertionError("CancelledError expected")
        except asyncio.CancelledError:
            pass
        assert not task_replies.contains(correlation_id)

    asyncio.run(scenario())


def test_react_call_cleans_pending_on_dispatch_exception_and_cancellation():
    async def scenario():
        with (
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.uuid.uuid4",
                return_value="corr-dispatch-error",
            ),
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator._dispatch_subtask",
                new=AsyncMock(side_effect=RuntimeError("dispatch failed")),
            ),
        ):
            try:
                await _react_call_one("root", AGENT_QUERY, {}, 1)
                raise AssertionError("RuntimeError expected")
            except RuntimeError as exc:
                assert str(exc) == "dispatch failed"
        assert not task_replies.contains("corr-dispatch-error")

        blocker = asyncio.Event()

        async def blocked_dispatch(*args, **kwargs):
            await blocker.wait()

        with (
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.uuid.uuid4",
                return_value="corr-react-cancelled",
            ),
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator._dispatch_subtask",
                new=AsyncMock(side_effect=blocked_dispatch),
            ),
        ):
            task = asyncio.create_task(_react_call_one("root", AGENT_QUERY, {}, 1))
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
                raise AssertionError("CancelledError expected")
            except asyncio.CancelledError:
                pass
        assert not task_replies.contains("corr-react-cancelled")

    asyncio.run(scenario())


def test_each_react_call_agent_creates_new_correlation_id():
    async def scenario():
        seen: list[str] = []

        async def fake_dispatch(task_id, correlation_id, target_agent, payload, priority):
            seen.append(correlation_id)
            reply = build_reply(
                _request(task_id, correlation_id),
                target_agent,
                success=True,
                data={"answer": "ok"},
            )
            resolve_task_reply(reply)

        with patch(
            "ecom_agent_matrix.orchestration.master.orchestrator._dispatch_subtask",
            new=AsyncMock(side_effect=fake_dispatch),
        ):
            await _react_call_one("root", AGENT_QUERY, {}, 1)
            await _react_call_one("root", AGENT_QUERY, {}, 1)
        assert len(seen) == 2
        assert seen[0] != seen[1]
        assert all(not task_replies.contains(correlation_id) for correlation_id in seen)

    asyncio.run(scenario())


def test_unknown_request_returns_clarify_without_rag_dispatch():
    with patch(
        "ecom_agent_matrix.orchestration.master.router.is_llm_configured",
        return_value=False,
    ):
        route = route_master_task({"query": "随便说点什么 xyz"})
    assert route.mode == "clarify"
    assert route.target_agents == []

    async def scenario():
        request = AgentMessage(
            task_id="root-clarify",
            sender="api_gateway",
            target=AGENT_MASTER,
            content={"query": "随便说点什么 xyz"},
        )
        long_mem = AsyncMock()
        long_mem.recall.return_value = []
        clarify = MasterPlan(
            decision="clarify",
            steps=[],
            confidence=0.3,
            reason_code="UNKNOWN",
            clarification_question="请补充具体需求。",
            planner_source="test",
        )
        with (
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.typed_master_planner.plan",
                new=AsyncMock(return_value=clarify),
            ),
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator._dispatch_subtask",
                new=AsyncMock(),
            ) as dispatch,
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.message_bus.send",
                new=AsyncMock(return_value=True),
            ) as send,
        ):
            await process_master_task(request, long_mem)
        dispatch.assert_not_awaited()
        sent = send.await_args.args[0]
        assert sent.content["data"]["mode"] == "clarify"
        assert sent.content["data"]["summary"] == "请补充具体需求。"

    asyncio.run(scenario())


def test_unknown_request_uses_planner_only_when_llm_is_configured():
    with patch(
        "ecom_agent_matrix.orchestration.master.router.is_llm_configured",
        return_value=True,
    ):
        route = route_master_task({"query": "??? xyz"})
    assert route.mode == "planner"
    assert route.target_agents == []


def test_refund_rules_route_rag_and_refund_reply_routes_exec_crm():
    rules = route_master_task({"query": "退款规则是什么"})
    reply = route_master_task({"query": "帮我回复退款客户"})
    order = route_master_task({"query": "查询订单数据"})
    assert rules.target_agents == [AGENT_RAG]
    assert reply.target_agents == [AGENT_EXEC]
    assert order.target_agents == [AGENT_QUERY]
    assert reply.task_type == "customer_service"


def test_query_context_rejects_write_skill():
    async def scenario():
        with skill_execution_context(AGENT_QUERY):
            result = await exec_skill(
                "record_competitor_price",
                {"target_sku": "SKU-1", "competitor": "Temu", "compete_price": 80},
            )
        assert result.success is False
        assert "无权执行非只读" in result.error_msg

    asyncio.run(scenario())


def test_skill_execution_context_is_fail_closed_and_exec_can_write():
    async def scenario():
        write_params = {
            "target_sku": "SKU-1",
            "competitor": "Temu",
            "compete_price": 80,
        }
        with patch(
            "ecom_agent_matrix.modules.skills.price_monitor.AsyncPGClient.execute_write",
            new=AsyncMock(return_value=[[123]]),
        ) as execute_write:
            no_context_write = await exec_skill("record_competitor_price", write_params)
            assert no_context_write.success is False
            execute_write.assert_not_awaited()

            no_context_read = await exec_skill(
                "profit_calc",
                {"cost": 10, "shipping": 2, "commission_rate": 0.1, "sell_price": 20},
            )
            assert no_context_read.success is True

            with skill_execution_context("unknown_agent"):
                unknown_agent = await exec_skill(
                    "profit_calc",
                    {"cost": 10, "shipping": 2, "commission_rate": 0.1, "sell_price": 20},
                )
            assert unknown_agent.success is False
            assert "未授权" in unknown_agent.error_msg

            security = SecurityContext(
                subject="subject",
                user_id="user",
                tenant_id="tenant",
                store_id="store",
                roles=frozenset({"operator"}),
                auth_type="jwt",
                authenticated=True,
            )
            with skill_execution_context(AGENT_EXEC, security=security, task_id="write-price-p0"):
                exec_write = await exec_skill("record_competitor_price", write_params)
            assert exec_write.success is True
            assert exec_write.data["record_id"] == 123
            assert execute_write.await_count == 1
            assert "INSERT INTO competitor_price" in execute_write.await_args.args[0]

    asyncio.run(scenario())


def test_deepseek_and_openai_provider_regression():
    names = available_providers()
    assert "deepseek" in names and "openai" in names
    assert get_llm_provider("deepseek").resolve_mode("r1") == "reasoner"

    provider = OpenAIProvider()
    reasoner_payload = provider.build_payload(
        model="o4-mini",
        mode="reasoner",
        user_prompt="hi",
        system_prompt="sys",
        temperature=0.9,
        max_tokens=256,
    )
    assert reasoner_payload["max_completion_tokens"] == 256
    assert "max_tokens" not in reasoner_payload
    assert "temperature" not in reasoner_payload


def test_query_competitor_workflow_is_read_only_and_calculates_warning():
    async def scenario():
        long_mem = AsyncMock()
        long_mem.recall.return_value = []
        with (
            patch(
                "ecom_agent_matrix.workflows.competitor.workflow._mem",
                return_value=long_mem,
            ),
            patch(
                "ecom_agent_matrix.workflows.competitor.workflow.llm_explain",
                new=AsyncMock(return_value=("建议关注", "rules", "")),
            ),
            patch(
                "ecom_agent_matrix.modules.skills.price_monitor.AsyncPGClient.execute_read",
                new=AsyncMock(return_value=[[100]]),
            ) as execute_read,
        ):
            ok, err, data = await run_query(
                {
                    "task_type": "competitor_watch",
                    "query": "监控 Temu 上 SKU-1 的价格",
                    "sku": "SKU-1",
                    "target_sku": "SKU-1",
                    "competitor": "Temu",
                    "compete_price": 80,
                    "warn_threshold": -10,
                }
            )

        assert ok is True
        assert err == ""
        assert data["monitor_data"]["history_min_compete_price"] == 100
        assert data["monitor_data"]["current_price_offset"] == -20
        assert data["is_trigger_warn"] is True
        assert execute_read.await_count == 1
        sql = execute_read.await_args.args[0].strip().upper()
        assert sql.startswith("SELECT")
        assert "INSERT" not in sql and "UPDATE" not in sql and "DELETE" not in sql
        long_mem.safe_save_memory.assert_not_awaited()

    asyncio.run(scenario())


def test_plan_reason_never_contains_internal_reasoning_content():
    async def scenario():
        model_result = ChatResult(
            content=json.dumps(
                {
                    "decision": "execute",
                    "steps": [
                        {
                            "step_id": "ad_optimize",
                            "agent": AGENT_EXEC,
                            "task_type": "ad_optimize",
                        }
                    ],
                    "confidence": 0.95,
                    "reason_code": "AD_OPTIMIZE",
                }
            ),
            reasoning_content="TOP SECRET INTERNAL CHAIN",
        )
        with (
            patch(
                "ecom_agent_matrix.orchestration.master.planner.is_llm_configured",
                return_value=True,
            ),
            patch(
                "ecom_agent_matrix.core.llm.structured.llm_chat",
                new=AsyncMock(return_value=model_result),
            ),
        ):
            plan = await TypedMasterPlanner().plan({"query": "优化广告投放"}, MasterLLMTelemetry())
        assert plan.reason_code == "AD_OPTIMIZE"
        assert "TOP SECRET" not in plan.model_dump_json()

    asyncio.run(scenario())


def test_master_react_trace_does_not_persist_reasoning_content():
    async def scenario():
        request = AgentMessage(
            task_id="root-reasoning",
            sender="api_gateway",
            target=AGENT_MASTER,
            content={"query": "查订单"},
        )
        plan = MasterPlan(
            decision="execute",
            confidence=0.95,
            reason_code="ORDER_QUERY",
            planner_source="test",
            steps=[PlanStep(step_id="order_context", agent=AGENT_QUERY, task_type="order_query")],
        )
        execution = PlanExecutionResult(
            all_success=True,
            partial_success=False,
            timed_out=False,
            step_results={
                "order_context": StepResult(
                    step_id="order_context",
                    agent=AGENT_QUERY,
                    task_type="order_query",
                    status="SUCCESS",
                    success=True,
                    data={"answer": "完成"},
                )
            },
        )
        long_mem = AsyncMock()
        long_mem.recall.return_value = []
        with (
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.typed_master_planner.plan",
                new=AsyncMock(return_value=plan),
            ),
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.MasterPlanExecutor.execute",
                new=AsyncMock(return_value=execution),
            ),
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.polish_final_output",
                new=AsyncMock(return_value="完成"),
            ),
            patch(
                "ecom_agent_matrix.orchestration.master.orchestrator.message_bus.send",
                new=AsyncMock(return_value=True),
            ) as send,
        ):
            await process_master_task(request, long_mem)

        persisted_reply = send.await_args_list[0].args[0].model_dump(mode="json")
        assert "reasoning_content" not in json.dumps(persisted_reply, ensure_ascii=False)
        if long_mem.safe_save_memory.await_count:
            saved_content = long_mem.safe_save_memory.await_args.kwargs["content"]
            assert "reasoning_content" not in saved_content
            assert "NEVER STORE" not in saved_content

    asyncio.run(scenario())
