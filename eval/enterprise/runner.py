"""Run the 50-case deterministic Enterprise Data Agent benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ecom_agent_matrix.core.security import SecurityContext, TenantScope
from ecom_agent_matrix.modules.business_api import DemoBusinessAPIClient
from ecom_agent_matrix.modules.data_intelligence import (
    HybridSchemaLinker,
    SQLGenerationRequest,
    SQLGenerator,
    SQLSafetyValidator,
    SQLValidationError,
    SchemaCatalog,
    default_catalog,
    filter_catalog_for_security,
)
from ecom_agent_matrix.orchestration.master.router import route_master_task

from .metrics import mean, precision_recall
from .report import write_report

CASES = Path(__file__).parent / "cases"
ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).parent / "baselines" / "current.json"
CATEGORIES = ("simple_sql", "complex_sql", "rag", "sql_rag", "api", "permission", "safety")


def _security(roles: list[str] | None = None, *, authenticated: bool = True) -> SecurityContext:
    return SecurityContext(
        subject="benchmark",
        user_id="benchmark-user",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset(roles if roles is not None else ["viewer"]),
        auth_type="system",
        authenticated=authenticated,
    )


def _catalog_for(item: dict) -> SchemaCatalog:
    return filter_catalog_for_security(default_catalog(), _security(item.get("roles")))


async def _evaluate_case(category: str, item: dict) -> tuple[dict, dict[str, float]]:
    case_id = item["id"]
    mode = item["mode"]
    metrics: dict[str, float] = {}
    try:
        if mode == "route":
            decision = route_master_task({"query": item["question"]})
            passed = decision.mode == item["expected_mode"]
            if "expected_task_type" in item:
                passed = passed and decision.task_type == item["expected_task_type"]
            if "expected_reason" in item:
                passed = passed and decision.reason_code == item["expected_reason"]
            detail = f"{decision.mode}:{decision.task_type or decision.reason_code}"
            metrics = {
                "routing_accuracy": float(passed),
                "fast_path_rate": float(decision.mode == "fast_path"),
                "planner_rate": float(decision.mode == "planner"),
                "unnecessary_planner_rate": float(
                    decision.mode == "planner" and item.get("expected_mode") != "planner"
                ),
            }
        elif mode in {"schema", "sql"}:
            catalog = _catalog_for(item)
            linked = await HybridSchemaLinker().link(item["question"], catalog, top_k=6)
            actual_tables = set(linked.table_names)
            expected_tables = set(item["expected_tables"])
            optional_tables = set(item.get("optional_tables") or [])
            table_precision, _ = precision_recall(
                actual_tables, expected_tables.union(optional_tables)
            )
            _, table_recall = precision_recall(actual_tables, expected_tables)
            actual_columns = {column.name for table in linked.tables for column in table.columns}
            expected_columns = set(
                item.get("required_columns") or item.get("expected_columns") or []
            )
            optional_columns = set(item.get("optional_columns") or [])
            column_precision, _ = precision_recall(
                actual_columns, expected_columns.union(optional_columns)
            )
            _, column_recall = precision_recall(actual_columns, expected_columns)
            metrics = {
                "table_precision": table_precision,
                "table_recall": table_recall,
                "column_precision": column_precision,
                "column_recall": column_recall,
                "schema_link_latency_ms": linked.latency_ms,
            }
            passed = expected_tables.issubset(actual_tables) and expected_columns.issubset(
                actual_columns
            )
            detail = f"tables={sorted(actual_tables)}, columns={sorted(actual_columns)}"
            if passed and mode == "sql":
                selected = tuple(table for table in catalog.tables if table.name in actual_tables)
                generated = await SQLGenerator().generate(
                    SQLGenerationRequest(
                        question=item["question"],
                        tables=selected,
                        relations=linked.relations,
                        max_rows=200,
                    )
                )
                validated = SQLSafetyValidator().validate(
                    generated.sql,
                    catalog=SchemaCatalog(
                        tables=selected, relations=linked.relations, version=catalog.version
                    ),
                    scope=TenantScope(
                        tenant_id="tenant-a", store_id="store-a", identity_trusted=True
                    ),
                )
                metrics["sql_parse_valid"] = 1.0
                metrics["sql_safety_pass"] = 1.0
                detail += f", sql={validated.sql}"
        elif mode == "api":
            response = await getattr(DemoBusinessAPIClient(), item["operation"])(
                item["resource_id"]
            )
            passed = response.found is item["expected_found"] and response.demo
            detail = f"provider={response.provider}, found={response.found}, demo={response.demo}"
        elif mode == "catalog":
            catalog = _catalog_for(item)
            names = {table.name for table in catalog.tables}
            passed = set(item["expected_tables"]).issubset(names) and names.isdisjoint(
                item["forbidden_tables"]
            )
            detail = f"tables={sorted(names)}"
        elif mode == "safety":
            security = _security(item.get("roles"))
            catalog = filter_catalog_for_security(default_catalog(), security)
            scope = TenantScope(
                tenant_id="tenant-a",
                store_id="store-a",
                identity_trusted=item.get("trusted", True),
            )
            actual = "PASS"
            limit = None
            try:
                validated = SQLSafetyValidator().validate(item["sql"], catalog=catalog, scope=scope)
                limit = validated.applied_limit
            except SQLValidationError as exc:
                actual = exc.code
            passed = actual == item["expected_code"]
            if "expected_limit" in item:
                passed = passed and limit == item["expected_limit"]
            detail = f"result={actual}, limit={limit}"
            if item["expected_code"] != "PASS":
                metrics["unsafe_sql_blocked"] = float(passed)
        else:
            passed, detail = False, f"unknown mode {mode}"
    except Exception as exc:
        passed, detail = False, f"{type(exc).__name__}: {exc}"
    return {
        "id": case_id,
        "category": category,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }, metrics


async def run(selected: tuple[str, ...] = CATEGORIES) -> dict:
    results: list[dict] = []
    metric_values: dict[str, list[float]] = {}
    for category in selected:
        items = json.loads((CASES / f"{category}.json").read_text())
        for item in items:
            result, values = await _evaluate_case(category, item)
            results.append(result)
            for name, value in values.items():
                metric_values.setdefault(name, []).append(value)
    passed = sum(case["status"] == "PASS" for case in results)
    failed = len(results) - passed
    metrics = {name: mean(values) for name, values in sorted(metric_values.items())}
    for prefix in ("table", "column"):
        precision = metrics.get(f"{prefix}_precision")
        recall = metrics.get(f"{prefix}_recall")
        metrics[f"{prefix}_f1"] = (
            round(2 * precision * recall / (precision + recall), 6)
            if precision is not None and recall is not None and precision + recall
            else None
        )
    metrics.update(
        {
            "task_success_rate": round(passed / len(results), 6) if results else None,
            "execution_success_rate": None,
            "execution_accuracy": None,
            "repair_rate": None,
            "repair_success_rate": None,
            "live_sql_status": "NOT_RUN",
            "rag_generation_status": "NOT_RUN",
            "external_api_status": "NOT_RUN",
            "unsafe_sql_execution_rate": 0.0 if metrics.get("unsafe_sql_blocked") == 1.0 else None,
            "llm_calls": 0,
            "token_cost_usd": 0.0,
        }
    )
    policy = json.loads(BASELINE.read_text())["policy"] if BASELINE.exists() else {}
    regressions = []
    for name, rule in policy.items():
        value = metrics.get(name)
        if value is None:
            continue
        if "minimum" in rule and value < rule["minimum"]:
            regressions.append(f"{name}={value} below {rule['minimum']}")
        if "maximum" in rule and value > rule["maximum"]:
            regressions.append(f"{name}={value} above {rule['maximum']}")
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        git_sha = "unknown"
    return {
        "metadata": {
            "git_sha": git_sha,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": os.getenv("APP_ENV", "development"),
            "deterministic": True,
        },
        "status": "PASS" if not failed and not regressions else "FAIL",
        "regression": {"status": "PASS" if not regressions else "FAIL", "issues": regressions},
        "totals": {"cases": len(results), "pass": passed, "fail": failed},
        "metrics": metrics,
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", *CATEGORIES], default="all")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)
    selected = CATEGORIES if args.suite == "all" else (args.suite,)
    report = asyncio.run(run(selected))
    json_path, markdown_path = write_report(report, args.output_dir)
    print(f"enterprise_status={report['status']}")
    print(f"cases={report['totals']['cases']}")
    print(f"json={json_path}")
    print(f"markdown={markdown_path}")
    return int(args.fail_on_regression and report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
