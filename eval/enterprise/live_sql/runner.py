"""Run deterministic SQL through AST safety against seeded PostgreSQL."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.security import TenantScope
from ecom_agent_matrix.modules.data_intelligence import SQLSafetyValidator, default_catalog

from .normalizer import normalize_rows

HERE = Path(__file__).parent


def _connect():
    return psycopg2.connect(
        host=settings.PG_HOST,
        port=settings.PG_PORT,
        user=settings.PG_USER,
        password=settings.PG_PWD,
        dbname=settings.PG_DB,
        connect_timeout=2,
    )


def run() -> dict:
    try:
        connection = _connect()
    except Exception as exc:
        return {
            "status": "NOT_RUN",
            "reason": f"PostgreSQL unavailable: {type(exc).__name__}",
            "totals": {"cases": 0, "pass": 0, "fail": 0},
            "metrics": {
                "execution_success_rate": None,
                "execution_accuracy": None,
                "sql_parse_valid_rate": None,
                "sql_safety_pass_rate": None,
                "repair_rate": None,
                "repair_success_rate": None,
                "average_sql_attempts": None,
                "average_latency_ms": None,
            },
            "cases": [],
        }

    cases = json.loads((HERE / "cases.json").read_text())
    results = []
    latencies = []
    validator = SQLSafetyValidator()
    scope = TenantScope(tenant_id="tenant-a", store_id="store-a", identity_trusted=True)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute((HERE / "seed.sql").read_text())
        for item in cases:
            started = time.perf_counter()
            try:
                validated = validator.validate(
                    item["sql"], catalog=default_catalog(), scope=scope, max_rows=200
                )
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(validated.sql)
                    actual = normalize_rows([dict(row) for row in cursor.fetchall()])
                expected = normalize_rows(item["expected"])
                accurate = actual == expected
                status = "PASS" if accurate else "FAIL"
                detail = {"actual": actual, "expected": expected}
                execution_success = True
                safety_pass = True
            except Exception as exc:
                status = "FAIL"
                detail = {"error": f"{type(exc).__name__}: {exc}"}
                execution_success = False
                safety_pass = False
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            latencies.append(latency_ms)
            results.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "status": status,
                    "parse_valid": safety_pass,
                    "safety_pass": safety_pass,
                    "execution_success": execution_success,
                    "execution_accurate": status == "PASS",
                    "sql_attempts": 1,
                    "latency_ms": latency_ms,
                    "detail": detail,
                }
            )
    finally:
        connection.close()
    passed = sum(item["status"] == "PASS" for item in results)
    total = len(results)
    execution_successes = sum(item["execution_success"] for item in results)
    safety_passes = sum(item["safety_pass"] for item in results)
    return {
        "status": "PASS" if passed == total else "FAIL",
        "totals": {"cases": total, "pass": passed, "fail": total - passed},
        "metrics": {
            "execution_success_rate": round(execution_successes / total, 6),
            "execution_accuracy": round(passed / total, 6),
            "sql_parse_valid_rate": round(safety_passes / total, 6),
            "sql_safety_pass_rate": round(safety_passes / total, 6),
            "repair_rate": 0.0,
            "repair_success_rate": None,
            "average_sql_attempts": 1.0,
            "average_latency_ms": round(sum(latencies) / total, 3),
        },
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE.parent / "results" / "live_sql.json")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--require-postgres", action="store_true")
    args = parser.parse_args(argv)
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"live_sql_status={report['status']}")
    print(f"cases={report['totals']['cases']}")
    print(f"json={args.output}")
    if args.require_postgres and report["status"] == "NOT_RUN":
        return 1
    return int(args.fail_on_regression and report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
