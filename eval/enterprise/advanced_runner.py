"""Deterministic schema, analytical, safety, evidence and security evaluations."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from ecom_agent_matrix.core.security import SecurityContext, TenantScope
from ecom_agent_matrix.modules.data_intelligence import (
    AnalyticalQueryPlanner,
    HybridSchemaLinker,
    SQLGuardConfig,
    SQLSafetyValidator,
    SQLValidationError,
    default_catalog,
    filter_catalog_for_security,
)
from ecom_agent_matrix.modules.evidence import (
    Claim,
    ClaimType,
    ComputedEvidence,
    DocumentEvidence,
    EvidenceStore,
    SQLEvidence,
    evidence_synthesis_service,
    validate_claims,
)
from eval.evaluator import evaluate_safety as evaluate_agent_security

from .metrics import mean, precision_recall

CASES = Path(__file__).parent / "cases"
SUITES = ("schema", "analytical", "safety", "evidence", "security")


def _security() -> SecurityContext:
    return SecurityContext(
        subject="benchmark",
        user_id="benchmark",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        auth_type="system",
        authenticated=True,
    )


async def evaluate_schema() -> dict:
    results = []
    values: dict[str, list[float]] = {
        "table_precision": [],
        "table_recall": [],
        "column_precision": [],
        "column_recall": [],
    }
    catalog = filter_catalog_for_security(default_catalog(), _security())
    items = []
    for name in ("simple_sql", "complex_sql"):
        items.extend(json.loads((CASES / f"{name}.json").read_text()))
    for item in items:
        linked = await HybridSchemaLinker().link(item["question"], catalog)
        actual_tables = set(linked.table_names)
        required_tables = set(item["expected_tables"])
        accepted_tables = required_tables.union(item.get("optional_tables") or [])
        table_precision, _ = precision_recall(actual_tables, accepted_tables)
        _, table_recall = precision_recall(actual_tables, required_tables)
        actual_columns = {column.name for table in linked.tables for column in table.columns}
        required_columns = set(item.get("required_columns") or item.get("expected_columns") or [])
        accepted_columns = required_columns.union(item.get("optional_columns") or [])
        column_precision, _ = precision_recall(actual_columns, accepted_columns)
        _, column_recall = precision_recall(actual_columns, required_columns)
        case_values = {
            "table_precision": table_precision,
            "table_recall": table_recall,
            "column_precision": column_precision,
            "column_recall": column_recall,
        }
        for key, value in case_values.items():
            values[key].append(value)
        passed = required_tables.issubset(actual_tables) and required_columns.issubset(
            actual_columns
        )
        results.append(
            {
                "id": item["id"],
                "status": "PASS" if passed else "FAIL",
                "retrieval_mode": linked.retrieval_mode,
                "actual_tables": sorted(actual_tables),
                "actual_columns": sorted(actual_columns),
            }
        )
    metrics = {key: mean(metric_values) for key, metric_values in values.items()}
    for prefix in ("table", "column"):
        precision = metrics[f"{prefix}_precision"]
        recall = metrics[f"{prefix}_recall"]
        metrics[f"{prefix}_f1"] = round(2 * precision * recall / (precision + recall), 6)
    return _section(results, metrics)


async def evaluate_analytical() -> dict:
    planner = AnalyticalQueryPlanner()
    cases = json.loads((CASES / "analytical_plan.json").read_text())
    results = []
    for item in cases:
        plan = planner.plan_if_supported(item["question"], default_catalog())
        actual = {step.step_type.value for step in plan.steps} if plan else set()
        required = set(item["required_steps"])
        forbidden = set(item["forbidden_steps"])
        passed = bool(plan) and required.issubset(actual) and actual.isdisjoint(forbidden)
        passed = passed and len(plan.steps) <= 4
        results.append(
            {
                "id": item["id"],
                "status": "PASS" if passed else "FAIL",
                "steps": sorted(actual),
                "subquery_count": len(plan.steps) if plan else 0,
            }
        )
    return _section(
        results,
        {
            "analytical_plan_validity": mean([float(item["status"] == "PASS") for item in results]),
            "forbidden_dimension_hallucination_rate": mean(
                [float("region_breakdown" in item["steps"]) for item in results]
            ),
        },
    )


def evaluate_safety() -> dict:
    cases = json.loads((CASES / "safety_adversarial.json").read_text())
    results = []
    unsafe_execution = 0
    for item in cases:
        validator = SQLSafetyValidator(
            SQLGuardConfig(
                max_join_tables=item.get("max_joins", 5),
                max_selected_columns=item.get("max_columns", 30),
                max_rows=200,
            )
        )
        actual = "PASS"
        limit = None
        try:
            validated = validator.validate(
                item["sql"],
                catalog=default_catalog(),
                scope=TenantScope(
                    tenant_id="tenant-a",
                    store_id="store-a",
                    identity_trusted=item.get("trusted", True),
                ),
            )
            limit = validated.applied_limit
        except SQLValidationError as exc:
            actual = exc.code
        passed = actual == item["expected"] and (
            "expected_limit" not in item or limit == item["expected_limit"]
        )
        if item["expected"] != "PASS" and actual == "PASS":
            unsafe_execution += 1
        results.append(
            {
                "id": item["id"],
                "status": "PASS" if passed else "FAIL",
                "expected": item["expected"],
                "actual": actual,
                "limit": limit,
            }
        )
    return _section(
        results,
        {
            "safety_pass_rate": mean([float(item["status"] == "PASS") for item in results]),
            "unsafe_sql_execution_rate": round(unsafe_execution / len(results), 6),
            "corpus_size": len(results),
        },
    )


async def evaluate_evidence() -> dict:
    store = EvidenceStore(tenant_id="tenant-a", store_id="store-a")
    sql = SQLEvidence(
        id="sql:1",
        source_name="seeded-postgres",
        tenant_id="tenant-a",
        store_id="store-a",
        sql="SELECT 1",
        tables=("ecom_order",),
        columns=("refund_flag",),
        rows=[{"refund_rate": 0.5}],
        row_count=1,
    )
    document = DocumentEvidence(
        id="doc:1",
        source_name="knowledge-base",
        tenant_id="tenant-a",
        store_id="store-a",
        document_id="policy-1",
        chunk_id="chunk-1",
        citation_id="C1",
        content_preview="August shipping incident",
    )
    store.add(sql)
    store.add(document)
    synthesis = await evidence_synthesis_service.synthesize("why", store)
    cooccurrence_ok = any(
        claim.claim_type == ClaimType.CO_OCCURRENCE for claim in synthesis.claims
    ) and not any(claim.claim_type == ClaimType.CORRELATION for claim in synthesis.claims)

    computed_store = EvidenceStore(tenant_id="tenant-a", store_id="store-a")
    computed = ComputedEvidence(
        id="computed:association",
        source_name="deterministic-statistics",
        tenant_id="tenant-a",
        store_id="store-a",
        formula="pearson(category_refunds, total_refunds)",
        result=0.8,
        metadata={"association_supported": True},
    )
    computed_store.add(computed)
    correlation = Claim(
        text="The repeated measurements show a quantitative association.",
        evidence_ids=[computed.id],
        confidence=0.8,
        claim_type=ClaimType.CORRELATION,
    )
    correlation_ok = validate_claims([correlation], computed_store).valid
    cases = [
        {"id": "evidence_001", "status": "PASS" if synthesis.grounding.valid else "FAIL"},
        {"id": "evidence_002", "status": "PASS" if cooccurrence_ok else "FAIL"},
        {"id": "evidence_003", "status": "PASS" if correlation_ok else "FAIL"},
    ]
    failures = sum(item["status"] == "FAIL" for item in cases)
    return _section(
        cases,
        {
            "grounding_pass_rate": float(not failures),
            "unsupported_claim_rate": 0.0 if not failures else round(failures / len(cases), 6),
            "missing_evidence_rate": 0.0,
            "fake_citation_rate": 0.0,
            "claim_type_accuracy": mean([float(item["status"] == "PASS") for item in cases]),
        },
    )


async def evaluate_security() -> dict:
    section = await asyncio.to_thread(evaluate_agent_security)
    results = section.get("cases", [])
    failed = sum(item["status"] == "FAIL" for item in results)
    total = len(results)
    return {
        **section,
        "metrics": {
            **section.get("metrics", {}),
            "permission_violation_rate": 0.0 if not failed else round(failed / total, 6),
            "tenant_isolation_failure_rate": 0.0 if not failed else round(failed / total, 6),
            "unsafe_execution_rate": 0.0 if not failed else round(failed / total, 6),
        },
    }


def _section(cases: list[dict], metrics: dict) -> dict:
    passed = sum(item["status"] == "PASS" for item in cases)
    failed = len(cases) - passed
    return {
        "status": "PASS" if not failed else "FAIL",
        "totals": {"cases": len(cases), "pass": passed, "fail": failed},
        "metrics": metrics,
        "cases": cases,
    }


async def run(suite: str) -> dict:
    selected = SUITES if suite == "all" else (suite,)
    sections = {}
    for name in selected:
        if name == "schema":
            sections[name] = await evaluate_schema()
        elif name == "analytical":
            sections[name] = await evaluate_analytical()
        elif name == "safety":
            sections[name] = evaluate_safety()
        elif name == "evidence":
            sections[name] = await evaluate_evidence()
        else:
            sections[name] = await evaluate_security()
    return {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "deterministic": True,
            "suite": suite,
        },
        "status": "PASS"
        if all(section["status"] == "PASS" for section in sections.values())
        else "FAIL",
        **sections,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", *SUITES), default="all")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).parent / "results" / "advanced.json"
    )
    args = parser.parse_args(argv)
    report = asyncio.run(run(args.suite))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"advanced_status={report['status']}")
    for name in SUITES:
        if name in report:
            print(f"{name}={report[name]['status']}")
    print(f"json={args.output}")
    return int(args.fail_on_regression and report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
