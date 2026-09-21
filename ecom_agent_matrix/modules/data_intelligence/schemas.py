"""Typed contracts for permission-aware enterprise data analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class ColumnAccess(StrEnum):
    ALLOW = "allow"
    MASK = "mask"
    DENY = "deny"


class SchemaColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    data_type: str = "text"
    description: str = ""
    business_terms: tuple[str, ...] = ()
    primary_key: bool = False
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    access: ColumnAccess = ColumnAccess.ALLOW
    allowed_roles: frozenset[str] = frozenset()
    allowed_scopes: frozenset[str] = frozenset()

    @property
    def searchable_text(self) -> str:
        description = self.description or self.name.replace("_", " ")
        return " ".join((self.name, description, *self.business_terms)).lower()


class SchemaRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    description: str = ""


class SchemaTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    description: str = ""
    columns: tuple[SchemaColumn, ...]
    business_terms: tuple[str, ...] = ()
    tenant_scoped: bool = True
    allowed_roles: frozenset[str] = frozenset()
    allowed_scopes: frozenset[str] = frozenset()

    @property
    def searchable_text(self) -> str:
        description = self.description or self.name.replace("_", " ")
        column_text = " ".join(column.searchable_text for column in self.columns)
        return " ".join((self.name, description, *self.business_terms, column_text)).lower()

    def column(self, name: str) -> SchemaColumn | None:
        normalized = name.lower()
        return next((column for column in self.columns if column.name.lower() == normalized), None)


class SchemaCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tables: tuple[SchemaTable, ...]
    relations: tuple[SchemaRelation, ...] = ()
    version: str = "1"
    source: Literal["postgres", "static", "static_fallback"] = "static"
    loaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def table(self, name: str) -> SchemaTable | None:
        normalized = name.lower()
        return next((table for table in self.tables if table.name.lower() == normalized), None)


class LinkedColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    score: float = Field(ge=0)
    reason_codes: tuple[str, ...] = ()


class LinkedTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    score: float = Field(ge=0)
    reason_codes: tuple[str, ...] = ()
    columns: tuple[LinkedColumn, ...] = ()


class SchemaLinkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tables: tuple[LinkedTable, ...]
    relations: tuple[SchemaRelation, ...] = ()
    candidate_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    retrieval_mode: Literal["hybrid", "lexical_only"] = "lexical_only"

    @property
    def table_names(self) -> list[str]:
        return [table.name for table in self.tables]


class DataAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1)
    task_type: str = "data_analysis"
    max_rows: int = Field(default=200, ge=1, le=1000)
    dialect: str = "postgres"
    sql: str | None = None
    params: list[Any] | dict[str, Any] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class SQLGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    tables: tuple[SchemaTable, ...]
    relations: tuple[SchemaRelation, ...] = ()
    max_rows: int = Field(ge=1, le=1000)
    dialect: str = "postgres"
    metric_definitions: tuple[str, ...] = ()


class GeneratedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sql: str = Field(min_length=1)
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)


class ValidatedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sql: str
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    output_columns: tuple[str, ...] = ()
    masked_output_columns: tuple[str, ...] = ()
    applied_limit: int | None = None
    join_count: int = 0
    selected_column_count: int = 0


class SQLLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str
    generated_sql: str
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    timestamp: datetime
    tenant_id: str
    store_id: str
    row_count: int = Field(ge=0)
    truncated: bool = False
    execution_latency_ms: float = Field(ge=0)


class SQLExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    truncated: bool = False
    result_quality: str = "valid"
    warnings: list[str] = Field(default_factory=list)
    lineage: SQLLineage


class AnalyticalStepType(StrEnum):
    METRIC_TREND = "metric_trend"
    CATEGORY_BREAKDOWN = "category_breakdown"
    SKU_BREAKDOWN = "sku_breakdown"
    REGION_BREAKDOWN = "region_breakdown"
    CUSTOM_SEGMENT = "custom_segment"


class AnalyticalQueryStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    step_type: AnalyticalStepType
    question: str = Field(min_length=1)
    required_tables: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()


class AnalyticalQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1)
    metric: str
    steps: tuple[AnalyticalQueryStep, ...]
    planner_source: Literal["deterministic", "llm"] = "deterministic"
    warnings: tuple[str, ...] = ()


class AnalyticalStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    step_type: AnalyticalStepType
    success: bool
    rows: list[dict[str, Any]] = Field(default_factory=list)
    evidence_id: str = ""
    lineage: SQLLineage | None = None
    warnings: list[str] = Field(default_factory=list)
    error_code: str = ""


class AnalyticalAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: AnalyticalQueryPlan
    steps: list[AnalyticalStepResult] = Field(default_factory=list)
    metric_trend: list[dict[str, Any]] = Field(default_factory=list)
    segment_contributions: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    anomalies: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["FULL_SUCCESS", "PARTIAL", "FAILED"] = "FAILED"


class DataAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    question: str
    catalog_source: str = ""
    schema_version: str = ""
    schema_link: SchemaLinkResult | None = None
    generated_sql: GeneratedSQL | None = None
    validated_sql: ValidatedSQL | None = None
    execution: SQLExecutionResult | None = None
    evidence: dict[str, Any] | None = None
    evidence_records: list[dict[str, Any]] = Field(default_factory=list)
    analytical: AnalyticalAnalysisResult | None = None
    repair_attempts: int = Field(default=0, ge=0)
    error_code: str = ""
    error_msg: str = ""


__all__ = [
    "AnalyticalAnalysisResult",
    "AnalyticalQueryPlan",
    "AnalyticalQueryStep",
    "AnalyticalStepResult",
    "AnalyticalStepType",
    "ColumnAccess",
    "DataAnalysisRequest",
    "DataAnalysisResult",
    "GeneratedSQL",
    "LinkedColumn",
    "LinkedTable",
    "SQLExecutionResult",
    "SQLGenerationRequest",
    "SQLLineage",
    "SchemaCatalog",
    "SchemaColumn",
    "SchemaLinkResult",
    "SchemaRelation",
    "SchemaTable",
    "Sensitivity",
    "ValidatedSQL",
]
