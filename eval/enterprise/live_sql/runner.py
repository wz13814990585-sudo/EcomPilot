"""Run gold SQL through AST safety and compare seeded PostgreSQL results."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlglot import parse
from sqlglot.errors import ParseError

from ecom_agent_matrix.core.security import TenantScope
from ecom_agent_matrix.modules.data_intelligence import (
    SQLSafetyValidator,
    SQLValidationError,
    default_catalog,
)

from .database import connect_admin, connect_read, execute_scoped, seed_database
from .dataset_sanity import run_dataset_sanity
from .normalizer import compare_rows, normalize_rows

HERE = Path(__file__).parent
DIAGNOSIS = {
    "original_ci_failure": "SQLGlot boolean AND nodes were misclassified as executable functions",
    "classification": "VALIDATOR_BUG",
    "fix": "Function allowlisting now excludes Binary AST syntax while remaining fail-closed for executable functions",
}


def _not_run(reason: str) -> dict:
    return {
        "benchmark_type": "SQL_EXECUTION_GOLD",
        "diagnosis": DIAGNOSIS,
        "status": "NOT_RUN",
        "reason": reason,
        "totals": {"cases": 0, "pass": 0, "fail": 0},
        "dataset_sanity": {"status": "NOT_RUN", "cases": []},
        "metrics": {
            "sql_parse_valid_rate": None,
            "sql_safety_pass_rate": None,
            "execution_success_rate": None,
            "execution_accuracy": None,
            "repair_rate": None,
            "repair_success_rate": None,
            "average_sql_attempts": None,
            "average_latency_ms": None,
        },
        "cases": [],
    }


def _failed_case(
    item: dict,
    *,
    stage: str,
    parse_valid: bool,
    safety_pass: bool,
    execution_success: bool,
    error: Exception | None = None,
    actual=None,
    expected=None,
) -> dict:
    return {
        "id": item["id"],
        "question": item["question"],
        "sql": item["sql"],
        "status": "FAIL",
        "stage": stage,
        "error_type": type(error).__name__ if error else "ResultMismatch",
        "error_message": str(error) if error else "Actual result does not match gold result",
        "sql_parse_valid": parse_valid,
        "sql_safety_pass": safety_pass,
        "execution_success": execution_success,
        "execution_accurate": False,
        "actual": actual,
        "expected": expected,
        "sql_attempts": 1,
    }


def _evaluate_case(connection, item: dict) -> dict:
    started = time.perf_counter()
    expected = normalize_rows(
        item["expected"], ordered=item.get("comparison", {}).get("ordered", True)
    )
    try:
        statements = parse(item["sql"], read="postgres")
        if len(statements) != 1 or statements[0] is None:
            raise ParseError("Exactly one SQL statement is required")
    except Exception as exc:
        result = _failed_case(
            item,
            stage="PARSE",
            parse_valid=False,
            safety_pass=False,
            execution_success=False,
            error=exc,
            expected=expected,
        )
    else:
        try:
            validated = SQLSafetyValidator().validate(
                item["sql"],
                catalog=default_catalog(),
                scope=TenantScope(tenant_id="tenant-a", store_id="store-a", identity_trusted=True),
                max_rows=200,
            )
        except SQLValidationError as exc:
            result = _failed_case(
                item,
                stage="SAFETY",
                parse_valid=True,
                safety_pass=False,
                execution_success=False,
                error=exc,
                expected=expected,
            )
        else:
            try:
                actual = normalize_rows(
                    execute_scoped(connection, validated.sql),
                    ordered=item.get("comparison", {}).get("ordered", True),
                )
            except Exception as exc:
                result = _failed_case(
                    item,
                    stage="EXECUTION",
                    parse_valid=True,
                    safety_pass=True,
                    execution_success=False,
                    error=exc,
                    expected=expected,
                )
            else:
                accurate = compare_rows(
                    actual,
                    expected,
                    float_tolerance=item.get("comparison", {}).get("float_tolerance", 0.000001),
                )
                if not accurate:
                    result = _failed_case(
                        item,
                        stage="COMPARISON",
                        parse_valid=True,
                        safety_pass=True,
                        execution_success=True,
                        actual=actual,
                        expected=expected,
                    )
                else:
                    result = {
                        "id": item["id"],
                        "question": item["question"],
                        "sql": item["sql"],
                        "status": "PASS",
                        "stage": "COMPLETE",
                        "error_type": "",
                        "error_message": "",
                        "sql_parse_valid": True,
                        "sql_safety_pass": True,
                        "execution_success": True,
                        "execution_accurate": True,
                        "actual": actual,
                        "expected": expected,
                        "sql_attempts": 1,
                    }
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


def run() -> dict:
    try:
        admin = connect_admin()
        admin.close()
        seed_database()
        connection = connect_read()
    except Exception as exc:
        return _not_run(f"PostgreSQL unavailable: {type(exc).__name__}: {exc}")

    try:
        sanity = run_dataset_sanity(connection)
        items = json.loads((HERE / "cases.json").read_text())
        results = [_evaluate_case(connection, item) for item in items]
    finally:
        connection.close()
    total = len(results)
    passed = sum(item["status"] == "PASS" for item in results)
    parse_valid = sum(item["sql_parse_valid"] for item in results)
    safety_pass = sum(item["sql_safety_pass"] for item in results)
    execution_success = sum(item["execution_success"] for item in results)
    accurate = sum(item["execution_accurate"] for item in results)
    status = "PASS" if passed == total and sanity["status"] == "PASS" else "FAIL"
    return {
        "benchmark_type": "SQL_EXECUTION_GOLD",
        "diagnosis": DIAGNOSIS,
        "status": status,
        "totals": {"cases": total, "pass": passed, "fail": total - passed},
        "dataset_sanity": sanity,
        "metrics": {
            "sql_parse_valid_rate": round(parse_valid / total, 6),
            "sql_safety_pass_rate": round(safety_pass / total, 6),
            "execution_success_rate": round(execution_success / total, 6),
            "execution_accuracy": round(accurate / total, 6),
            "repair_rate": 0.0,
            "repair_success_rate": None,
            "average_sql_attempts": 1.0,
            "average_latency_ms": round(sum(item["latency_ms"] for item in results) / total, 3),
        },
        "cases": results,
    }


def _print_failures(report: dict) -> None:
    for case in report.get("cases", []):
        if case["status"] != "FAIL":
            continue
        print(f"FAIL {case['id']}")
        print(f"question: {case['question']}")
        print(f"stage: {case['stage']}")
        print(f"sql: {case['sql']}")
        print(f"error_type: {case['error_type']}")
        print(f"error_message: {case['error_message']}")
        print(f"actual: {json.dumps(case['actual'], ensure_ascii=False)}")
        print(f"expected: {json.dumps(case['expected'], ensure_ascii=False)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE.parent / "results" / "sql_gold_execution.json",
    )
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--require-postgres", action="store_true")
    args = parser.parse_args(argv)
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _print_failures(report)
    print(f"gold_sql_status={report['status']}")
    print(f"cases={report['totals']['cases']}")
    print(f"json={args.output}")
    if args.require_postgres and report["status"] == "NOT_RUN":
        return 1
    return int(args.fail_on_regression and report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
