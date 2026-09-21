from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from ecom_agent_matrix.core.security import SecurityContext
from ecom_agent_matrix.modules.evidence import (
    Claim,
    ClaimType,
    DocumentEvidence,
    EvidenceStore,
    SQLEvidence,
    evidence_synthesis_service,
    validate_claims,
)
from ecom_agent_matrix.orchestration.master.orchestrator import _synthesize_composite_evidence
from ecom_agent_matrix.orchestration.master.planner import build_composite_plan
from ecom_agent_matrix.orchestration.master.router import route_master_task
from ecom_agent_matrix.orchestration.master.schemas import PlanExecutionResult, StepResult


def _sql_evidence() -> SQLEvidence:
    return SQLEvidence(
        id="sql-1",
        source_name="postgres-read-role",
        tenant_id="tenant-a",
        store_id="store-a",
        sql="SELECT refund_rate FROM monthly_metrics",
        tables=("monthly_metrics",),
        columns=("monthly_metrics.refund_rate",),
        rows=[{"month": "2026-08", "refund_rate": 0.12}],
        row_count=1,
        lineage={"query_id": "sql-1"},
    )


def _document_evidence() -> DocumentEvidence:
    return DocumentEvidence(
        id="doc-1",
        source_name="operations-report",
        tenant_id="tenant-a",
        store_id="store-a",
        document_id="report-august",
        chunk_id="chunk-7",
        citation_id="S1",
        content_preview="8 月华东配送延迟投诉增加。",
        retrieval_score=0.8,
    )


def _security() -> SecurityContext:
    return SecurityContext(
        subject="subject",
        user_id="user-a",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset({"viewer"}),
        auth_type="jwt",
        authenticated=True,
    )


def test_evidence_store_is_bounded_and_tenant_isolated():
    store = EvidenceStore(tenant_id="tenant-a", store_id="store-a", max_records=2)
    store.add(_sql_evidence())
    assert store.get("sql-1") is not None
    foreign = _document_evidence().model_copy(update={"tenant_id": "tenant-b"})
    with pytest.raises(PermissionError, match="CROSS_TENANT_EVIDENCE"):
        store.add(foreign)
    assert len(store.bounded_package(max_chars=500)) == 1


def test_grounding_detects_missing_evidence_and_fake_citations():
    store = EvidenceStore(tenant_id="tenant-a", store_id="store-a")
    report = validate_claims(
        [
            Claim(
                text="退款率为 12% [S9]",
                evidence_ids=["missing"],
                citation_ids=["S9"],
                claim_type=ClaimType.FACT,
            )
        ],
        store,
    )
    assert report.valid is False
    assert {issue.code for issue in report.issues} >= {
        "MISSING_EVIDENCE",
        "INVALID_CITATION",
        "UNSUPPORTED_CLAIM",
        "UNSUPPORTED_NUMERIC_CLAIM",
    }


def test_synthesis_distinguishes_correlation_from_causation():
    store = EvidenceStore(tenant_id="tenant-a", store_id="store-a")
    store.add(_sql_evidence())
    store.add(_document_evidence())
    result = asyncio.run(evidence_synthesis_service.synthesize("为什么退款率上涨？", store))
    assert result.grounding.valid is True
    assert any(claim.claim_type == ClaimType.CO_OCCURRENCE for claim in result.claims)
    assert not any(claim.claim_type == ClaimType.CORRELATION for claim in result.claims)
    assert "不支持相关性或确定因果结论" in result.summary
    assert result.citations == ["S1"]


def test_refund_why_routes_to_deterministic_sql_rag_plan():
    decision = route_master_task({"query": "为什么 8 月退款率上涨？"})
    assert decision.mode == "planner"
    assert decision.reason_code == "COMPOSITE_DATA_ANALYSIS"
    plan = build_composite_plan({"query": "为什么 8 月退款率上涨？"})
    assert plan.reason_code == "COMPOSITE_DATA_ANALYSIS"
    assert {(step.agent, step.task_type) for step in plan.steps} == {
        ("data_query", "data_analysis"),
        ("knowledge_rag", "knowledge_qa"),
    }
    assert all(not step.depends_on for step in plan.steps)
    assert "monthly refund rate" in plan.steps[0].payload["query"]
    assert "shipping incidents" in plan.steps[1].payload["query"]


def test_master_collects_query_and_rag_evidence_for_grounded_synthesis():
    sql = (
        _sql_evidence()
        .model_copy(update={"timestamp": datetime.now(timezone.utc)})
        .model_dump(mode="json")
    )
    execution = PlanExecutionResult(
        all_success=True,
        partial_success=False,
        timed_out=False,
        step_results={
            "structured_analysis": StepResult(
                step_id="structured_analysis",
                agent="data_query",
                task_type="data_analysis",
                status="SUCCESS",
                success=True,
                data={"evidence": sql},
            ),
            "document_context": StepResult(
                step_id="document_context",
                agent="knowledge_rag",
                task_type="knowledge_qa",
                status="SUCCESS",
                success=True,
                data={
                    "docs": [
                        {
                            "source_id": "report-august",
                            "citation_id": "S1",
                            "chunk_text": "8 月华东配送延迟投诉增加。",
                            "relevance_score": 0.8,
                            "meta": {"document_id": "report-august", "chunk_id": "chunk-7"},
                        }
                    ]
                },
            ),
        },
    )
    analysis, package = asyncio.run(
        _synthesize_composite_evidence(
            question="为什么 8 月退款率上涨？",
            execution=execution,
            security=_security(),
        )
    )
    assert analysis["grounding"]["valid"] is True
    assert len(package) == 2
    assert {item["source_type"] for item in package} == {"sql", "document"}
