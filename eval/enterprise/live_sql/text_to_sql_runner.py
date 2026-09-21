"""Evaluate question -> production DataIntelligenceService -> seeded PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from sqlglot import parse_one

from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.db.base import AsyncPGClient
from ecom_agent_matrix.modules.data_intelligence import (
    DataAnalysisRequest,
    DataIntelligenceService,
    PostgresSchemaCatalogLoader,
    SchemaCatalogProvider,
)

from .database import connect_admin, seed_database
from .normalizer import compare_rows, normalize_rows

HERE = Path(__file__).parent


def _security() -> SecurityContext:
    return SecurityContext(
        subject="enterprise-eval",
        user_id="enterprise-eval",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        scopes=frozenset({"commerce:read"}),
        auth_type="system",
        authenticated=True,
    )


def _not_run(reason: str) -> dict:
    return {
        "benchmark_type": "QUESTION_TO_SQL_EXECUTION",
        "status": "NOT_RUN",
        "reason": reason,
        "totals": {"cases": 0, "pass": 0, "fail": 0},
        "metrics": {
            "generation_success_rate": None,
            "sql_parse_valid_rate": None,
            "sql_safety_pass_rate": None,
            "execution_success_rate": None,
            "execution_accuracy": None,
            "repair_rate": None,
            "repair_success_rate": None,
            "average_sql_attempts": None,
            "schema_link_latency_ms": None,
            "sql_generation_latency_ms": None,
            "sql_execution_latency_ms": None,
            "total_llm_calls": 0,
            "token_usage": 0,
            "estimated_cost": 0.0,
        },
        "cases": [],
        "live_llm_text_to_sql": {"status": "NOT_RUN", "reason": "No external LLM in CI"},
    }


async def _evaluate(service: DataIntelligenceService, item: dict) -> dict:
    started = time.perf_counter()
    result = await service.analyze(
        DataAnalysisRequest(question=item["question"], max_rows=200), security=_security()
    )
    generated_sql = result.generated_sql.sql if result.generated_sql else ""
    parse_valid = False
    if generated_sql:
        try:
            parse_one(generated_sql, read="postgres")
            parse_valid = True
        except Exception:
            pass
    safety_pass = result.validated_sql is not None
    execution_success = result.execution is not None
    expected = normalize_rows(
        item["expected"], ordered=item.get("comparison", {}).get("ordered", True)
    )
    actual = (
        normalize_rows(
            result.execution.rows,
            ordered=item.get("comparison", {}).get("ordered", True),
        )
        if result.execution
        else None
    )
    accurate = bool(
        actual is not None
        and compare_rows(
            actual,
            expected,
            float_tolerance=item.get("comparison", {}).get("float_tolerance", 0.000001),
        )
    )
    stage = (
        "COMPLETE"
        if accurate
        else "COMPARISON"
        if execution_success
        else "EXECUTION"
        if safety_pass
        else "SAFETY"
        if parse_valid
        else "PARSE"
        if generated_sql
        else "GENERATION"
    )
    lineage = result.execution.lineage if result.execution else None
    evidence_id = str((result.evidence or {}).get("id") or "")
    return {
        "id": item["id"],
        "question": item["question"],
        "reference_sql": item.get("reference_sql"),
        "reference_sql_used": False,
        "status": "PASS" if accurate else "FAIL",
        "stage": stage,
        "error_code": result.error_code,
        "error_message": result.error_msg,
        "generation_success": bool(generated_sql),
        "sql_parse_valid": parse_valid,
        "sql_safety_pass": safety_pass,
        "execution_success": execution_success,
        "execution_accurate": accurate,
        "generated_sql": generated_sql,
        "validated_sql": result.validated_sql.sql if result.validated_sql else "",
        "actual": actual,
        "expected": expected,
        "repair_attempts": result.repair_attempts,
        "sql_attempts": 1 + result.repair_attempts,
        "catalog_source": result.catalog_source,
        "schema_version": result.schema_version,
        "retrieval_mode": result.schema_link.retrieval_mode if result.schema_link else None,
        "schema_link_latency_ms": result.schema_link.latency_ms if result.schema_link else None,
        "sql_execution_latency_ms": lineage.execution_latency_ms if lineage else None,
        "lineage_query_id": lineage.query_id if lineage else "",
        "referenced_tables": list(lineage.referenced_tables) if lineage else [],
        "referenced_columns": list(lineage.referenced_columns) if lineage else [],
        "evidence_id": evidence_id,
        "evidence_traceable": bool(lineage and evidence_id == lineage.query_id),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


async def _run_async() -> dict:
    provider = SchemaCatalogProvider()
    try:
        catalog = await provider.refresh(PostgresSchemaCatalogLoader().load)
        service = DataIntelligenceService(catalog_provider=provider)
        items = json.loads((HERE / "text_to_sql_cases.json").read_text())
        results = [await _evaluate(service, item) for item in items]
    finally:
        await AsyncPGClient.close()
    total = len(results)
    passed = sum(case["status"] == "PASS" for case in results)
    repairs = sum(case["repair_attempts"] > 0 for case in results)
    repaired = sum(case["repair_attempts"] > 0 and case["status"] == "PASS" for case in results)

    def average(key: str) -> float:
        return round(sum(float(case[key] or 0) for case in results) / total, 3)

    return {
        "benchmark_type": "QUESTION_TO_SQL_EXECUTION",
        "status": "PASS" if passed == total and catalog.source == "postgres" else "FAIL",
        "catalog_source": catalog.source,
        "schema_version": catalog.version,
        "totals": {"cases": total, "pass": passed, "fail": total - passed},
        "metrics": {
            "generation_success_rate": round(
                sum(c["generation_success"] for c in results) / total, 6
            ),
            "sql_parse_valid_rate": round(sum(c["sql_parse_valid"] for c in results) / total, 6),
            "sql_safety_pass_rate": round(sum(c["sql_safety_pass"] for c in results) / total, 6),
            "execution_success_rate": round(
                sum(c["execution_success"] for c in results) / total, 6
            ),
            "execution_accuracy": round(sum(c["execution_accurate"] for c in results) / total, 6),
            "repair_rate": round(repairs / total, 6),
            "repair_success_rate": round(repaired / repairs, 6) if repairs else None,
            "average_sql_attempts": average("sql_attempts"),
            "schema_link_latency_ms": average("schema_link_latency_ms"),
            "sql_generation_latency_ms": None,
            "sql_execution_latency_ms": average("sql_execution_latency_ms"),
            "total_llm_calls": 0,
            "token_usage": 0,
            "estimated_cost": 0.0,
        },
        "retrieval_mode_distribution": {
            mode: sum(case["retrieval_mode"] == mode for case in results)
            for mode in ("lexical_only", "hybrid")
        },
        "cases": results,
        "live_llm_text_to_sql": {"status": "NOT_RUN", "reason": "No external LLM in CI"},
    }


def run() -> dict:
    try:
        connection = connect_admin()
        connection.close()
        seed_database()
        return asyncio.run(_run_async())
    except Exception as exc:
        return _not_run(f"PostgreSQL unavailable: {type(exc).__name__}: {exc}")


def _print_failures(report: dict) -> None:
    for case in report.get("cases", []):
        if case["status"] == "PASS":
            continue
        print(f"FAIL {case['id']}")
        print(f"question: {case['question']}")
        print(f"stage: {case['stage']}")
        print(f"generated_sql: {case['generated_sql']}")
        print(f"error: {case['error_code']}: {case['error_message']}")
        print(f"actual: {json.dumps(case['actual'], ensure_ascii=False)}")
        print(f"expected: {json.dumps(case['expected'], ensure_ascii=False)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=HERE.parent / "results" / "text_to_sql_execution.json"
    )
    parser.add_argument("--require-postgres", action="store_true")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _print_failures(report)
    print(f"text_to_sql_status={report['status']}")
    print(f"cases={report['totals']['cases']}")
    print(f"json={args.output}")
    if args.require_postgres and report["status"] == "NOT_RUN":
        return 1
    return int(args.fail_on_regression and report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
