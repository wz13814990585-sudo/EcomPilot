"""CLI entry point for deterministic and optional Agent evaluations."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .evaluator import (
    architecture_snapshot,
    evaluate_execution,
    evaluate_planning,
    evaluate_rag,
    evaluate_recovery,
    evaluate_routing,
    evaluate_safety,
)
from .report import write_report

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "routing": evaluate_routing,
    "planning": evaluate_planning,
    "execution": evaluate_execution,
    "safety": evaluate_safety,
    "recovery": evaluate_recovery,
    "rag": evaluate_rag,
}
DETERMINISTIC = ("routing", "planning", "safety", "recovery")


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run(suite: str) -> dict:
    selected = (
        list(SUITES)
        if suite == "all"
        else list(DETERMINISTIC)
        if suite == "deterministic"
        else [suite]
    )
    sections = {
        name: SUITES[name]() if name in selected else _not_selected(name) for name in SUITES
    }
    gate_failed = any(
        case["status"] == "FAIL"
        for name in DETERMINISTIC
        if name in selected
        for case in sections[name]["cases"]
        if case["status"] != "NOT_RUN"
    )
    gate_executed = any(name in selected for name in DETERMINISTIC)
    return {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_sha": _git_sha(),
            "environment": os.getenv("APP_ENV", "development"),
            "suite": suite,
            "architecture": architecture_snapshot(),
        },
        **sections,
        "cost": {
            "status": "NOT_RUN",
            "metrics": {
                "llm_calls": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "estimated_cost": None,
            },
        },
        "deterministic_gate": ("FAIL" if gate_failed else "PASS" if gate_executed else "NOT_RUN"),
    }


def _not_selected(name: str) -> dict:
    return {
        "status": "NOT_RUN",
        "totals": {"pass": 0, "fail": 0, "not_run": 0, "degraded": 0},
        "metrics": {},
        "cases": [],
        "reason": f"{name} suite not selected",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=[*SUITES, "deterministic", "all"], default="all")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval" / "results")
    args = parser.parse_args(argv)
    report = run(args.suite)
    json_path, markdown_path = write_report(report, args.output_dir)
    print(f"deterministic_gate={report['deterministic_gate']}")
    for name in SUITES:
        print(f"{name}={report[name]['status']}")
    print(f"json={json_path}")
    print(f"markdown={markdown_path}")
    if args.fail_on_regression and report["deterministic_gate"] == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
