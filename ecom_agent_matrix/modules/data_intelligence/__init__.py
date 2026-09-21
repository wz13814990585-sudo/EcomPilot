"""Enterprise data-intelligence facade."""

from .catalog import SchemaCatalogProvider, default_catalog, filter_catalog_for_security
from .schema_linker import HybridSchemaLinker
from .schemas import (
    ColumnAccess,
    DataAnalysisRequest,
    DataAnalysisResult,
    GeneratedSQL,
    SQLExecutionResult,
    SQLGenerationRequest,
    SQLLineage,
    SchemaCatalog,
    SchemaColumn,
    SchemaLinkResult,
    SchemaRelation,
    SchemaTable,
    Sensitivity,
    ValidatedSQL,
)
from .sql_validator import SQLGuardConfig, SQLSafetyValidator, SQLValidationError
from .service import DataIntelligenceService, data_intelligence_service
from .sql_executor import SQLExecutionFailure, SafeSQLExecutor
from .sql_generator import SQLGenerationError, SQLGenerator
from .sql_repair import SQLRepairer

__all__ = [
    "ColumnAccess",
    "DataAnalysisRequest",
    "DataAnalysisResult",
    "DataIntelligenceService",
    "GeneratedSQL",
    "HybridSchemaLinker",
    "SQLExecutionResult",
    "SQLExecutionFailure",
    "SQLGenerationRequest",
    "SQLGuardConfig",
    "SQLLineage",
    "SQLSafetyValidator",
    "SQLValidationError",
    "SQLGenerationError",
    "SQLGenerator",
    "SQLRepairer",
    "SafeSQLExecutor",
    "SchemaCatalog",
    "SchemaCatalogProvider",
    "SchemaColumn",
    "SchemaLinkResult",
    "SchemaRelation",
    "SchemaTable",
    "Sensitivity",
    "ValidatedSQL",
    "default_catalog",
    "data_intelligence_service",
    "filter_catalog_for_security",
]
