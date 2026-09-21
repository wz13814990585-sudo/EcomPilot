"""Live retrieval and grounded-answer evaluation over bootstrapped demo knowledge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.modules.rag.evaluation import RAGEvalCase, evaluate_ranked_results

CASES = (
    RAGEvalCase(query="退货窗口期是多少天？", relevant_source_ids=["01_return_refund_policy"]),
    RAGEvalCase(query="BAG-001 应该怎么清洁？", relevant_source_ids=["04_product_backpack_bag001"]),
    RAGEvalCase(
        query="2026年8月发生了什么运营事件？", relevant_source_ids=["15_august_operations_incident"]
    ),
    RAGEvalCase(query="高风险订单怎么处理？", relevant_source_ids=["09_high_risk_order_sop"]),
)


def _find(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find(child, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find(child, key)
            if found is not None:
                return found
    return None


def run(base_url: str = "http://127.0.0.1:8002") -> dict:
    ranked = {}
    details = []
    grounded = citation_valid = 0
    modes: set[str] = set()
    headers = {"X-API-Key": settings.API_KEY}
    with httpx.Client(base_url=base_url, headers=headers, timeout=120) as client:
        for case in CASES:
            response = client.post(
                "/api/v1/customer/chat",
                json={"query": case.query, "lang": "zh", "use_rag": True},
            )
            payload = response.json()
            docs = _find(payload.get("data"), "docs") or []
            answer = str(_find(payload.get("data"), "answer") or payload.get("summary") or "")
            citation_status = str(_find(payload.get("data"), "citation_status") or "none")
            mode = str(_find(payload.get("data"), "retrieval_mode") or "none")
            is_grounded = bool(_find(payload.get("data"), "grounded"))
            ranked[case.query] = docs
            grounded += int(is_grounded)
            citation_valid += int(citation_status == "valid")
            modes.add(mode)
            details.append(
                {
                    "query": case.query,
                    "expected": case.relevant_source_ids,
                    "ranked": [doc.get("source_id") for doc in docs],
                    "success": bool(payload.get("success")),
                    "answer_nonempty": bool(answer),
                    "grounded": is_grounded,
                    "citation_status": citation_status,
                    "retrieval_mode": mode,
                }
            )
    metrics = evaluate_ranked_results(CASES, ranked, k=5).model_dump()
    report = {
        "suite": "RAG_DEMO_LIVE",
        **metrics,
        "citation_validity": citation_valid / len(CASES),
        "grounded_answer_rate": grounded / len(CASES),
        "retrieval_modes": sorted(modes),
        "details": details,
    }
    output = Path("eval/results/rag_demo_live.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    report = run()
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))


if __name__ == "__main__":
    main()
