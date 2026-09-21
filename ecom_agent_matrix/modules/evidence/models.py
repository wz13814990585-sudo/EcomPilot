"""Unified evidence, claims and grounded-analysis contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceType(StrEnum):
    SQL = "sql"
    DOCUMENT = "document"
    API = "api"
    COMPUTED = "computed"


class ClaimType(StrEnum):
    FACT = "fact"
    CO_OCCURRENCE = "co_occurrence"
    CORRELATION = "correlation"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    source_type: EvidenceType
    source_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = Field(default=1.0, ge=0, le=1)
    task_id: str = ""
    tenant_id: str
    store_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SQLEvidence(EvidenceRecord):
    source_type: EvidenceType = EvidenceType.SQL
    sql: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    truncated: bool = False
    lineage: dict[str, Any] = Field(default_factory=dict)


class DocumentEvidence(EvidenceRecord):
    source_type: EvidenceType = EvidenceType.DOCUMENT
    document_id: str
    chunk_id: str
    citation_id: str
    content_preview: str
    retrieval_score: float | None = None
    rerank_score: float | None = None


class APIEvidence(EvidenceRecord):
    source_type: EvidenceType = EvidenceType.API
    provider: str
    operation: str
    resource_id: str
    response_fields: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ComputedEvidence(EvidenceRecord):
    source_type: EvidenceType = EvidenceType.COMPUTED
    formula: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0, le=1)
    claim_type: ClaimType


class GroundingIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    claim_index: int | None = None
    detail: str = ""


class GroundingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[GroundingIssue] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    claims: list[Claim] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    grounding: GroundingReport


__all__ = [
    "APIEvidence",
    "AnalysisResult",
    "Claim",
    "ClaimType",
    "ComputedEvidence",
    "DocumentEvidence",
    "EvidenceRecord",
    "EvidenceType",
    "GroundingIssue",
    "GroundingReport",
    "SQLEvidence",
]
