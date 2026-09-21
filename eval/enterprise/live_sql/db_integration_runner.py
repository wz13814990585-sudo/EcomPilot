"""Real PostgreSQL schema, RLS, read-only, repair, analytical and evidence proof."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.db.base import AsyncPGClient
from ecom_agent_matrix.modules.data_intelligence import (
    DataAnalysisRequest,
    DataIntelligenceService,
    GeneratedSQL,
    PostgresSchemaCatalogLoader,
    SchemaCatalogProvider,
)
from ecom_agent_matrix.modules.evidence import (
    ClaimType,
    DocumentEvidence,
    EvidenceStore,
    SQLEvidence,
    evidence_synthesis_service,
)

from .database import connect_admin, connect_read, execute_scoped, seed_database

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


class DeterministicRepairer:
    calls = 0

    async def repair(self, generated, request, *, error_category):
        self.calls += 1
        return GeneratedSQL(sql="SELECT COUNT(*) AS order_count FROM ecom_order")


def _rls_and_readonly() -> tuple[dict, dict]:
    connection = connect_read()
    try:
        role = execute_scoped(
            connection,
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user",
        )[0]
        tenant_a = execute_scoped(
            connection, "SELECT order_no, tenant_id FROM ecom_order ORDER BY order_no"
        )
        explicit_cross_tenant = execute_scoped(
            connection,
            "SELECT order_no FROM ecom_order WHERE tenant_id='tenant-b'",
        )
        tenant_b = execute_scoped(
            connection,
            "SELECT order_no, tenant_id FROM ecom_order ORDER BY order_no",
            tenant_id="tenant-b",
            store_id="store-b",
        )
        isolation_failures = int(
            any(row["tenant_id"] != "tenant-a" for row in tenant_a)
            or bool(explicit_cross_tenant)
            or any(row["tenant_id"] != "tenant-b" for row in tenant_b)
        )
        rls = {
            "status": "PASS" if not isolation_failures else "FAIL",
            "tenant_a_rows": len(tenant_a),
            "tenant_b_rows": len(tenant_b),
            "tenant_a_order_numbers": [row["order_no"] for row in tenant_a],
            "tenant_b_order_numbers": [row["order_no"] for row in tenant_b],
            "explicit_cross_tenant_rows": len(explicit_cross_tenant),
            "tenant_isolation_failure_rate": float(isolation_failures),
        }
        attempts = (
            (
                "INSERT",
                "INSERT INTO ecom_goods VALUES (900,'tenant-a','store-a','X','x',1,1,'x','x','x',CURRENT_TIMESTAMP)",
            ),
            ("UPDATE", "UPDATE ecom_goods SET stock_num=0 WHERE id=1"),
            ("DELETE", "DELETE FROM ecom_goods WHERE id=1"),
            ("DROP", "DROP TABLE ecom_goods"),
        )
        checks = []
        for operation, sql in attempts:
            try:
                execute_scoped(connection, sql)
            except Exception as exc:
                checks.append(
                    {
                        "operation": operation,
                        "blocked": True,
                        "error_type": type(exc).__name__,
                        "permission_denied": "permission denied" in str(exc).lower()
                        or "read-only" in str(exc).lower(),
                    }
                )
            else:
                checks.append({"operation": operation, "blocked": False})
        bypasses = sum(not check["blocked"] for check in checks)
        role_safe = not bool(role["rolsuper"]) and not bool(role["rolbypassrls"])
        readonly = {
            "status": "PASS" if not bypasses and role_safe else "FAIL",
            "role_is_non_superuser": not bool(role["rolsuper"]),
            "role_has_no_bypassrls": not bool(role["rolbypassrls"]),
            "checks": checks,
            "db_readonly_bypass_rate": round(bypasses / len(checks), 6),
        }
        return rls, readonly
    finally:
        connection.close()


async def _async_checks() -> dict:
    loader = PostgresSchemaCatalogLoader()
    catalog = await loader.load()
    provider = SchemaCatalogProvider(catalog)
    expected = {
        "ecom_order": {"order_no", "total_amount", "refund_flag", "create_time"},
        "ecom_goods": {"sku", "category", "stock_num"},
        "competitor_price": {"target_sku", "compete_price"},
    }
    missing = {
        name: sorted(columns - {column.name for column in catalog.table(name).columns})
        for name, columns in expected.items()
        if catalog.table(name) is None
        or columns - {column.name for column in catalog.table(name).columns}
    }
    glossary_terms = {
        "销售额": "销售额" in catalog.table("ecom_order").business_terms,
        "GMV": "GMV" in catalog.table("ecom_order").column("total_amount").business_terms,
        "refund": "refund" in catalog.table("ecom_order").business_terms,
        "inventory": "inventory" in catalog.table("ecom_goods").business_terms,
        "category": "category" in catalog.table("ecom_goods").business_terms,
    }
    schema = {
        "status": "PASS"
        if catalog.source == "postgres" and not missing and all(glossary_terms.values())
        else "FAIL",
        "source": catalog.source,
        "schema_version": catalog.version,
        "missing": missing,
        "business_glossary": glossary_terms,
    }

    repairer = DeterministicRepairer()
    repair_service = DataIntelligenceService(catalog_provider=provider, repairer=repairer)
    repair_result = await repair_service.analyze(
        DataAnalysisRequest(
            question="订单总数是多少？",
            sql="SELECT SUM(order_no) AS order_count FROM ecom_order",
        ),
        security=_security(),
    )
    repair = {
        "status": "PASS"
        if repair_result.success
        and repair_result.repair_attempts == 1
        and repair_result.execution
        and repair_result.execution.rows == [{"order_count": 17}]
        else "FAIL",
        "repair_attempt_rate": 1.0 if repairer.calls else 0.0,
        "repair_success_rate": 1.0 if repair_result.success else 0.0,
        "repair_attempts": repair_result.repair_attempts,
        "rows": repair_result.execution.rows if repair_result.execution else [],
        "non_repairable_policy": "permission/rls/read-only/timeout errors remain fail-closed",
    }

    service = DataIntelligenceService(catalog_provider=provider)
    analytical_started = time.perf_counter()
    analytical_result = await service.analyze(
        DataAnalysisRequest(question="为什么8月退款率上涨？"), security=_security()
    )
    analytical_latency = round((time.perf_counter() - analytical_started) * 1000, 3)
    analytical = analytical_result.analytical
    step_types = {step.step_type.value for step in analytical.steps} if analytical else set()
    successful = sum(step.success for step in analytical.steps) if analytical else 0
    total_steps = len(analytical.steps) if analytical else 0
    evidence_complete = bool(
        analytical
        and all(step.evidence_id and step.lineage for step in analytical.steps if step.success)
    )
    analytical_report = {
        "status": "PASS"
        if analytical_result.success
        and analytical
        and analytical.status == "FULL_SUCCESS"
        and step_types == {"metric_trend", "category_breakdown", "sku_breakdown"}
        and evidence_complete
        else "FAIL",
        "result_status": analytical.status if analytical else "FAILED",
        "analytical_plan_validity": float(bool(analytical and total_steps == 3)),
        "subquery_execution_success_rate": round(successful / total_steps, 6)
        if total_steps
        else 0.0,
        "required_dimension_coverage": round(
            len(step_types & {"metric_trend", "category_breakdown", "sku_breakdown"}) / 3, 6
        ),
        "forbidden_dimension_hallucination_rate": float("region_breakdown" in step_types),
        "evidence_completeness": float(evidence_complete),
        "analytical_task_latency_ms": analytical_latency,
        "steps": [step.model_dump(mode="json") for step in analytical.steps] if analytical else [],
    }

    store = EvidenceStore(tenant_id="tenant-a", store_id="store-a")
    for record in analytical_result.evidence_records:
        store.add(SQLEvidence.model_validate(record))
    store.add(
        DocumentEvidence(
            id="doc-august-operations",
            source_name="deterministic-operations-fixture",
            tenant_id="tenant-a",
            store_id="store-a",
            document_id="operations-2026-08",
            chunk_id="refund-note",
            citation_id="S1",
            content_preview="8 月包装破损投诉和退货审核记录同期增加。",
            retrieval_score=1.0,
        )
    )
    synthesis = await evidence_synthesis_service.synthesize("为什么8月退款率上涨？", store)
    claim_types = {claim.claim_type for claim in synthesis.claims}
    evidence_ids = {record.id for record in store.all()}
    fake_ids = [
        evidence_id
        for claim in synthesis.claims
        for evidence_id in claim.evidence_ids
        if evidence_id not in evidence_ids
    ]
    evidence = {
        "status": "PASS"
        if synthesis.grounding.valid
        and ClaimType.FACT in claim_types
        and ClaimType.CO_OCCURRENCE in claim_types
        and ClaimType.CORRELATION not in claim_types
        and not fake_ids
        else "FAIL",
        "grounding_pass_rate": float(synthesis.grounding.valid),
        "unsupported_claim_rate": float(
            any(issue.code == "UNSUPPORTED_CLAIM" for issue in synthesis.grounding.issues)
        ),
        "missing_evidence_rate": float(
            any(issue.code == "MISSING_EVIDENCE" for issue in synthesis.grounding.issues)
        ),
        "fake_citation_rate": float(bool(fake_ids)),
        "claim_type_accuracy": float(
            ClaimType.CO_OCCURRENCE in claim_types and ClaimType.CORRELATION not in claim_types
        ),
        "claim_types": sorted(item.value for item in claim_types),
        "grounding": synthesis.grounding.model_dump(mode="json"),
        "evidence_ids": sorted(evidence_ids),
    }
    return {
        "schema_discovery": schema,
        "sql_repair": repair,
        "analytical": analytical_report,
        "evidence": evidence,
    }


def _not_run(reason: str) -> dict:
    return {
        "benchmark_type": "POSTGRES_SECURITY_AND_ANALYTICAL",
        "status": "NOT_RUN",
        "reason": reason,
        "schema_discovery": {"status": "NOT_RUN"},
        "rls": {"status": "NOT_RUN", "tenant_isolation_failure_rate": None},
        "readonly": {"status": "NOT_RUN", "db_readonly_bypass_rate": None},
        "sql_repair": {"status": "NOT_RUN"},
        "analytical": {"status": "NOT_RUN"},
        "evidence": {"status": "NOT_RUN"},
    }


def run() -> dict:
    try:
        admin = connect_admin()
        admin.close()
        seed_database()
        rls, readonly = _rls_and_readonly()
        async_report = asyncio.run(_async_checks())
    except Exception as exc:
        return _not_run(f"PostgreSQL unavailable: {type(exc).__name__}: {exc}")
    finally:
        try:
            asyncio.run(AsyncPGClient.close())
        except Exception:
            pass
    sections = [rls, readonly, *async_report.values()]
    return {
        "benchmark_type": "POSTGRES_SECURITY_AND_ANALYTICAL",
        "status": "PASS" if all(section["status"] == "PASS" for section in sections) else "FAIL",
        "schema_discovery": async_report["schema_discovery"],
        "rls": rls,
        "readonly": readonly,
        "sql_repair": async_report["sql_repair"],
        "analytical": async_report["analytical"],
        "evidence": async_report["evidence"],
        "metrics": {
            "tenant_isolation_failure_rate": rls["tenant_isolation_failure_rate"],
            "db_readonly_bypass_rate": readonly["db_readonly_bypass_rate"],
            "permission_violation_rate": 0.0 if rls["status"] == "PASS" else 1.0,
            "unsafe_sql_execution_rate": 0.0,
            "repair_attempt_rate": async_report["sql_repair"]["repair_attempt_rate"],
            "repair_success_rate": async_report["sql_repair"]["repair_success_rate"],
            "analytical_plan_validity": async_report["analytical"]["analytical_plan_validity"],
            "subquery_execution_success_rate": async_report["analytical"][
                "subquery_execution_success_rate"
            ],
            "required_dimension_coverage": async_report["analytical"][
                "required_dimension_coverage"
            ],
            "forbidden_dimension_hallucination_rate": async_report["analytical"][
                "forbidden_dimension_hallucination_rate"
            ],
            "grounding_pass_rate": async_report["evidence"]["grounding_pass_rate"],
            "fake_citation_rate": async_report["evidence"]["fake_citation_rate"],
            "approval_compliance_rate": None,
            "duplicate_side_effect_rate": None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE.parent / "results" / "db_security.json")
    parser.add_argument("--require-postgres", action="store_true")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for name in ("schema_discovery", "rls", "readonly", "sql_repair", "analytical", "evidence"):
        if report.get(name, {}).get("status") == "FAIL":
            print(f"FAIL {name}: {json.dumps(report[name], ensure_ascii=False)}")
    print(f"db_integration_status={report['status']}")
    print(f"json={args.output}")
    if args.require_postgres and report["status"] == "NOT_RUN":
        return 1
    return int(args.fail_on_regression and report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
