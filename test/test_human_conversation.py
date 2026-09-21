from ecom_agent_matrix.api.conversation import remembered_context
from ecom_agent_matrix.modules.presentation import build_presentation
from ecom_agent_matrix.orchestration.master.router import route_master_task


def test_social_presentation_shows_generated_copy_instead_of_generic_success():
    presentation = build_presentation(
        success=True,
        data={
            "exec_kind": "social",
            "platform": "tiktok",
            "lang": "zh",
            "social_copy": {
                "copy_draft": "🎒 轻装出发，BAG-001 陪你走得更远！",
                "platform": "tiktok",
                "lang": "zh",
            },
            "ai_image_prompt": {"positive_prompt": "outdoor backpack on a mountain trail"},
        },
    )
    assert presentation["answer"].startswith("🎒 轻装出发")
    assert "配图提示词" in presentation["recommendations"][0]


def test_refund_analysis_answer_contains_evidence_based_reason_and_uncertainty():
    presentation = build_presentation(
        success=True,
        data={
            "analytical": {
                "plan": {"question": "为什么2026年8月退款率上涨？"},
                "metric_trend": [
                    {
                        "month": "2026-07-01",
                        "order_count": 80,
                        "refund_count": 8,
                        "refund_rate": 0.1,
                    },
                    {
                        "month": "2026-08-01",
                        "order_count": 80,
                        "refund_count": 24,
                        "refund_rate": 0.3,
                    },
                ],
                "segment_contributions": {
                    "category_breakdown": [
                        {"category": "electronics", "refund_count": 16, "refund_rate": 0.6154}
                    ],
                    "sku_breakdown": [
                        {"sku": "CHARGER-001", "refund_count": 13, "refund_rate": 0.8667}
                    ],
                },
            },
            "analysis": {
                "claims": [
                    {
                        "text": "CHARGER-001 某批次接头松动，BAG-002 拉链客诉增多，同期存在物流延迟。",
                        "citation_ids": ["S1"],
                        "claim_type": "fact",
                    }
                ],
                "uncertainties": ["只能确认共现。"],
                "recommended_next_steps": ["核对问题批次。"],
                "citations": ["S1"],
            },
        },
    )
    assert "CHARGER-001 退款 13 单" in presentation["answer"]
    assert "接头松动" in presentation["answer"]
    assert "不能当作单一因果" in presentation["answer"]


def test_human_product_queries_route_without_llm_guessing():
    assert route_master_task({"query": "商店的鞋子是多少钱的"}).task_type == "goods_search"
    assert route_master_task({"query": "鞋子现在处于什么库存状态"}).task_type == "stock_analysis"
    assert route_master_task({"query": "查看背包的竞品价格"}).task_type == "competitor_watch"


def test_short_follow_up_reuses_latest_visible_sku_only():
    history = [
        {"role": "user", "content": "我想看店里的鞋子"},
        {"role": "assistant", "content": "最相关的是 TrailForge 防水徒步鞋（SHOE-001）。"},
    ]
    assert remembered_context("多少钱？", history) == {"sku": "SHOE-001"}
    assert remembered_context("那库存呢？", history) == {"sku": "SHOE-001"}
    assert remembered_context("查 BAG-002 库存", history) == {}
