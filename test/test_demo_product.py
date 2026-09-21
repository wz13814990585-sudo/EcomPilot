from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ecom_agent_matrix.api.main import rag_status
from ecom_agent_matrix.modules.presentation import build_presentation
from ecom_agent_matrix.orchestration.master.router import route_master_task


@pytest.mark.parametrize(
    "query,expected",
    [
        ("2026年8月销售额是多少？", "data_analysis"),
        ("退款政策是什么？", "knowledge_qa"),
        ("帮我找防水户外背包。", "goods_search"),
        ("现在店里都有哪些商品？", "goods_catalog"),
        ("哪些商品库存不足，需要优先补货？", "stock_analysis"),
        ("BAG-001 在 Temu 上最近卖多少钱？", "competitor_watch"),
        ("ORD-DEMO-001 现在什么状态？", "order_query"),
        ("目前哪个广告活动 ROAS 最低？", "ad_query"),
        ("帮我暂停表现最差的广告活动。", "ad_optimize"),
        ("检查一下当前电商数据有没有异常。", "data_check"),
        ("给我生成今天的运营报告。", "ops_report"),
        ("给 BAG-001 写一条 TikTok 推广文案。", "social_marketing"),
        ("客户说 BAG-002 拉链坏了想退款，应该怎么回复？", "customer_service"),
        ("把 ORD-DEMO-RISK 标记为高风险订单。", "risk_control"),
    ],
)
def test_natural_language_capability_routes(query, expected):
    decision = route_master_task({"query": query})
    assert decision.task_type == expected
    assert decision.mode == "fast_path"


def test_demo_corpus_has_twenty_real_documents():
    root = Path(__file__).resolve().parents[1] / "demo" / "knowledge"
    documents = sorted(root.glob("*.md"))
    assert len(documents) == 20
    assert all(path.read_text(encoding="utf-8").startswith("# ") for path in documents)


def test_analytical_presentation_preserves_metrics_and_evidence():
    presentation = build_presentation(
        success=True,
        data={
            "query_kind": "data_analysis",
            "result": {"rows": [{"month": "2026-08", "refund_rate": 0.3}]},
            "analytical": {
                "status": "FULL_SUCCESS",
                "metric_trend": [{"month": "2026-08", "refund_rate": 0.3}],
                "segment_contributions": {
                    "sku_breakdown": [{"sku": "BAG-002", "refund_rate": 0.8}]
                },
                "warnings": [],
            },
            "evidence_records": [{"id": "sql:1"}, {"id": "sql:2"}],
        },
    )
    assert "0.3" in presentation["answer"]
    assert any("BAG-002" in item for item in presentation["highlights"])
    assert presentation["evidence_summary"] == "2 条 SQL 证据记录"


def test_rag_status_reports_demo_counts_and_lexical_fallback():
    execute = AsyncMock(
        side_effect=[[(20, 20, 0)], [(24, 240, 80, 8)]],
    )
    with patch("ecom_agent_matrix.api.main.AsyncPGClient.execute_sql", new=execute):
        result = asyncio.run(rag_status())
    assert result["documents"] == 20
    assert result["retrieval_mode"] == "lexical_only"
    assert result["demo_data"]["loaded"] is True


def test_frontend_is_chat_first_and_keeps_developer_details_collapsed():
    root = Path(__file__).resolve().parents[1] / "ecom_agent_matrix" / "api" / "frontend"
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    assert 'id="conversation"' in html
    assert "高级 / 开发者选项" in html
    assert "presentation?.answer" in script
    assert "approveAndRetry" in script
