from __future__ import annotations

import asyncio
import json
from pathlib import Path

from eval.enterprise.runner import CASES, CATEGORIES, run


def test_enterprise_benchmark_has_exactly_fifty_high_quality_cases():
    counts = {
        category: len(json.loads((CASES / f"{category}.json").read_text()))
        for category in CATEGORIES
    }
    assert counts == {
        "simple_sql": 8,
        "complex_sql": 8,
        "rag": 6,
        "sql_rag": 6,
        "api": 6,
        "permission": 8,
        "safety": 8,
    }
    assert sum(counts.values()) == 50


def test_enterprise_deterministic_benchmark_passes(tmp_path: Path):
    report = asyncio.run(run())
    assert report["status"] == "PASS", [
        case for case in report["cases"] if case["status"] == "FAIL"
    ]
    assert report["totals"] == {"cases": 50, "pass": 50, "fail": 0}
    assert report["metrics"]["task_success_rate"] == 1.0
    assert report["metrics"]["live_sql_status"] == "NOT_RUN"
