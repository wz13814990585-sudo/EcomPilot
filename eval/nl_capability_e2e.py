"""Live HTTP natural-language capability acceptance suite for the local demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from ecom_agent_matrix.config.settings import settings

CASES = (
    ("data_analysis", "2026年8月销售额是多少？"),
    ("knowledge_qa", "退款政策是什么？"),
    ("goods_search", "帮我找防水户外背包。"),
    ("goods_catalog", "现在店里都有哪些商品？"),
    ("stock_analysis", "哪些商品库存不足，需要优先补货？"),
    ("competitor_watch", "BAG-001 在 Temu 上最近卖多少钱？和我们比呢？"),
    ("order_query", "ORD-DEMO-001 现在什么状态？"),
    ("ad_query", "目前哪个广告活动 ROAS 最低？"),
    ("ad_optimize", "帮我暂停表现最差的广告活动。"),
    ("data_check", "检查一下当前电商数据有没有异常。"),
    ("ops_report", "给我生成今天的运营报告。"),
    ("social_marketing", "给 BAG-001 写一条 TikTok 推广文案。"),
    ("customer_service", "客户说 BAG-002 拉链坏了而且想退款，应该怎么回复？"),
    ("risk_control", "把 ORD-DEMO-RISK 标记为高风险订单。"),
)
PROTECTED = frozenset({"ad_optimize", "risk_control"})


def _find(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if value.get(key):
            return value[key]
        for child in value.values():
            found = _find(child, key)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find(child, key)
            if found:
                return found
    return None


def run(base_url: str, *, approve_writes: bool = False) -> dict[str, Any]:
    headers = {"X-API-Key": settings.API_KEY, "Content-Type": "application/json"}
    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url, headers=headers, timeout=120) as client:
        for capability, query in CASES:
            body = {"query": query}
            response = client.post("/api/v1/tasks", json=body)
            payload = response.json()
            route = _find(payload.get("data"), "route") or {}
            observed = route.get("task_type")
            approval_id = _find(payload, "approval_id")
            awaiting = bool(approval_id) and not payload.get("success")
            approval_after = None
            final_success = bool(payload.get("success"))
            if capability in PROTECTED and awaiting and approve_writes:
                approved = client.post(f"/api/v1/approvals/{approval_id}/approve")
                retried = client.post(
                    "/api/v1/tasks",
                    json=body,
                    headers={**headers, "X-Approval-Id": str(approval_id)},
                )
                retry_payload = retried.json()
                approval_after = {
                    "approve_http": approved.status_code,
                    "retry_http": retried.status_code,
                    "retry_success": bool(retry_payload.get("success")),
                }
                final_success = approval_after["retry_success"]
            route_ok = observed == capability
            behavior_ok = awaiting if capability in PROTECTED else final_success
            presentation = payload.get("presentation") or {}
            results.append(
                {
                    "capability": capability,
                    "query": query,
                    "http_status": response.status_code,
                    "observed_route": observed,
                    "route_ok": route_ok,
                    "initial_success": bool(payload.get("success")),
                    "awaiting_approval": awaiting,
                    "approval_after": approval_after,
                    "answer_nonempty": bool(presentation.get("answer") or payload.get("summary")),
                    "evidence_present": bool(
                        presentation.get("evidence_summary")
                        or _find(payload.get("data"), "evidence")
                    ),
                    "pass": bool(response.is_success and route_ok and behavior_ok),
                    "summary": str(payload.get("summary") or "")[:300],
                }
            )
    total = len(results)
    report = {
        "suite": "NL_CAPABILITY_E2E",
        "base_url": base_url,
        "routing_accuracy": sum(item["route_ok"] for item in results) / total,
        "task_execution_success_rate": sum(item["pass"] for item in results) / total,
        "answer_nonempty_rate": sum(item["answer_nonempty"] for item in results) / total,
        "evidence_presence_rate": sum(item["evidence_present"] for item in results) / total,
        "approval_behavior_accuracy": sum(
            item["awaiting_approval"] for item in results if item["capability"] in PROTECTED
        )
        / len(PROTECTED),
        "passed": sum(item["pass"] for item in results),
        "total": total,
        "results": results,
    }
    output = Path("eval/results/nl_capability_e2e.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument(
        "--approve-writes",
        action="store_true",
        help="Actually approve and execute protected demo mutations; opt in explicitly",
    )
    args = parser.parse_args()
    report = run(args.base_url, approve_writes=args.approve_writes)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    for item in report["results"]:
        print(item["capability"], "PASS" if item["pass"] else "FAIL", item["summary"][:100])
    if args.fail_on_regression and report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
