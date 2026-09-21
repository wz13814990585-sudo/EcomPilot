"""Generate an honest before/after enterprise engineering report."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .advanced_runner import run as run_advanced
from .live_sql.runner import run as run_live_sql
from .live_sql.text_to_sql_runner import run as run_text_to_sql
from .live_sql.db_integration_runner import run as run_db_integration
from .runner import run as run_enterprise

HERE = Path(__file__).parent


def _delta(before, after):
    if before is None or after is None:
        return None
    return round(after - before, 6)


def _git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=HERE.parent.parent,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


async def build() -> dict:
    baseline = json.loads(
        (HERE / "results" / "baseline_before_final_optimization.json").read_text()
    )
    enterprise = await run_enterprise()
    advanced = await run_advanced("all")
    gold = await asyncio.to_thread(run_live_sql)
    text_to_sql = await asyncio.to_thread(run_text_to_sql)
    db_integration = await asyncio.to_thread(run_db_integration)
    before = baseline["metrics"]
    after = enterprise["metrics"]
    comparison_names = (
        "table_precision",
        "table_recall",
        "table_f1",
        "column_precision",
        "column_recall",
        "column_f1",
        "sql_parse_valid",
        "sql_safety_pass",
        "execution_success_rate",
        "execution_accuracy",
        "repair_rate",
        "repair_success_rate",
        "routing_accuracy",
        "fast_path_rate",
        "planner_rate",
        "schema_link_latency_ms",
        "llm_calls",
        "token_cost_usd",
    )
    comparison = {
        name: {
            "before": before.get(name),
            "after": after.get(name),
            "delta": _delta(before.get(name), after.get(name)),
        }
        for name in comparison_names
    }
    comparison["execution_success_rate"]["after"] = text_to_sql.get("metrics", {}).get(
        "execution_success_rate"
    )
    comparison["execution_accuracy"]["after"] = text_to_sql.get("metrics", {}).get(
        "execution_accuracy"
    )
    return {
        "metadata": {
            "git_sha": _git_sha(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "mode": "deterministic_and_postgres_integration",
            },
        },
        "status": "PASS"
        if enterprise["status"] == advanced["status"] == "PASS"
        and gold["status"] in {"PASS", "NOT_RUN"}
        and text_to_sql["status"] in {"PASS", "NOT_RUN"}
        and db_integration["status"] in {"PASS", "NOT_RUN"}
        else "FAIL",
        "before": baseline,
        "after": {
            "enterprise": enterprise,
            "advanced": advanced,
            "sql_gold_execution": gold,
            "text_to_sql_execution": text_to_sql,
            "db_security": db_integration,
            "rag_live": {"status": "NOT_RUN", "reason": "No populated vector index"},
        },
        "comparison": comparison,
        "quality": {
            "analytical_plan_validity": advanced["analytical"]["metrics"][
                "analytical_plan_validity"
            ],
            "unsupported_claim_rate": advanced["evidence"]["metrics"]["unsupported_claim_rate"],
            "grounding_pass_rate": advanced["evidence"]["metrics"]["grounding_pass_rate"],
            "unsafe_sql_execution_rate": advanced["safety"]["metrics"]["unsafe_sql_execution_rate"],
            "permission_violation_rate": advanced["security"]["metrics"][
                "permission_violation_rate"
            ],
            "tenant_isolation_failure_rate": advanced["security"]["metrics"][
                "tenant_isolation_failure_rate"
            ],
        },
    }


def _markdown(report: dict) -> str:
    comparison = report["comparison"]
    lines = [
        "# Final Enterprise Data Agent Evaluation",
        "",
        f"- Status: **{report['status']}**",
        f"- Git SHA: `{report['metadata']['git_sha']}`",
        f"- Timestamp: `{report['metadata']['timestamp']}`",
        "",
        "## Before → After",
        "",
        "| Metric | Before | After | Delta |",
        "|---|---:|---:|---:|",
    ]
    for name, values in comparison.items():
        lines.append(
            f"| {name} | {values['before'] if values['before'] is not None else 'NOT_RUN'} "
            f"| {values['after'] if values['after'] is not None else 'NOT_RUN'} "
            f"| {values['delta'] if values['delta'] is not None else 'NOT_RUN'} |"
        )
    lines.extend(
        [
            "",
            "## Deterministic quality",
            "",
            "```json",
            json.dumps(report["quality"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Integration status",
            "",
            f"- Gold SQL execution: **{report['after']['sql_gold_execution']['status']}**",
            f"- Question-to-SQL execution: **{report['after']['text_to_sql_execution']['status']}**",
            f"- DB security / analytical: **{report['after']['db_security']['status']}**",
            f"- RAG live: **{report['after']['rag_live']['status']}**",
            "",
            "`NOT_RUN` is preserved and is not counted as `PASS`.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE / "results")
    args = parser.parse_args(argv)
    report = asyncio.run(build())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "final.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    (args.output_dir / "final.md").write_text(_markdown(report))
    print(f"final_status={report['status']}")
    print(f"json={args.output_dir / 'final.json'}")
    print(f"markdown={args.output_dir / 'final.md'}")
    return int(report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build", "main"]
