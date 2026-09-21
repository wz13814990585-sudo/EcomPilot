"""SQLGlot AST safety, authorization and deterministic query-cost guards."""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from ...core.errors import ErrorCode
from ...core.security import TenantScope
from .schemas import ColumnAccess, SchemaCatalog, ValidatedSQL


class SQLValidationError(ValueError):
    def __init__(self, code: ErrorCode | str, message: str):
        self.code = str(code)
        super().__init__(message)


@dataclass(frozen=True)
class SQLGuardConfig:
    max_join_tables: int = 5
    max_selected_columns: int = 30
    max_rows: int = 200


@dataclass(frozen=True)
class SQLFunctionPolicy:
    """Fail-closed allowlist for executable functions in untrusted/generated SQL."""

    allowed: frozenset[str] = frozenset(
        {
            "abs",
            "avg",
            "case",
            "cast",
            "ceil",
            "ceiling",
            "coalesce",
            "count",
            "current_date",
            "current_time",
            "current_timestamp",
            "date_trunc",
            "extract",
            "floor",
            "greatest",
            "if",
            "least",
            "lower",
            "max",
            "min",
            "nullif",
            "round",
            "sum",
            "timestamp_trunc",
            "upper",
        }
    )


def _function_name(function: exp.Func) -> str:
    if isinstance(function, exp.Anonymous):
        return str(function.name or "").lower()
    return str(function.sql_name() or "").lower()


_FORBIDDEN_TYPES = tuple(
    expression
    for expression in (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Alter,
        exp.Create,
        exp.Merge,
        exp.Copy,
        exp.Command,
        exp.Grant,
        exp.Revoke,
        getattr(exp, "TruncateTable", None),
        getattr(exp, "Call", None),
    )
    if expression is not None
)


def _is_single_aggregate(select: exp.Select) -> bool:
    if select.args.get("group") or select.args.get("having"):
        return False
    projections = list(select.expressions)
    return bool(projections) and all(
        item.find(exp.AggFunc) is not None or item.find(exp.Column) is None for item in projections
    )


class SQLSafetyValidator:
    def __init__(
        self,
        config: SQLGuardConfig | None = None,
        function_policy: SQLFunctionPolicy | None = None,
    ) -> None:
        self.config = config or SQLGuardConfig()
        self.function_policy = function_policy or SQLFunctionPolicy()

    def validate(
        self,
        sql: str,
        *,
        catalog: SchemaCatalog,
        scope: TenantScope,
        max_rows: int | None = None,
        dialect: str = "postgres",
    ) -> ValidatedSQL:
        try:
            statements = parse(sql, read=dialect)
        except ParseError as exc:
            raise SQLValidationError(ErrorCode.SQL_PARSE_ERROR, "SQL could not be parsed") from exc
        if len(statements) != 1 or statements[0] is None:
            raise SQLValidationError(ErrorCode.UNSAFE_SQL, "Exactly one SQL statement is required")
        root = statements[0]
        if isinstance(root, _FORBIDDEN_TYPES) or any(root.find_all(_FORBIDDEN_TYPES)):
            raise SQLValidationError(
                ErrorCode.UNSAFE_SQL, "Only read-only SELECT queries are allowed"
            )
        if not isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            raise SQLValidationError(
                ErrorCode.UNSAFE_SQL, "SQL root must be SELECT or WITH ... SELECT"
            )
        if root.find(exp.Into) is not None or any(
            select.args.get("locks") for select in root.find_all(exp.Select)
        ):
            raise SQLValidationError(
                ErrorCode.UNSAFE_SQL, "SELECT INTO and row locks are forbidden"
            )
        called_functions = {_function_name(function) for function in root.find_all(exp.Func)}
        unsafe_functions = called_functions.difference(self.function_policy.allowed)
        if unsafe_functions:
            raise SQLValidationError(
                ErrorCode.UNSAFE_SQL,
                f"SQL function is not allowlisted: {', '.join(sorted(unsafe_functions))}",
            )

        cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
        physical_tables = [
            table for table in root.find_all(exp.Table) if table.name.lower() not in cte_names
        ]
        referenced_tables = tuple(dict.fromkeys(table.name.lower() for table in physical_tables))
        allowed_tables = {table.name.lower(): table for table in catalog.tables}
        unknown_tables = [table for table in referenced_tables if table not in allowed_tables]
        if unknown_tables:
            raise SQLValidationError(
                ErrorCode.TABLE_NOT_ALLOWED,
                f"Table is not allowed: {', '.join(sorted(unknown_tables))}",
            )
        if (
            any(allowed_tables[name].tenant_scoped for name in referenced_tables)
            and not scope.usable
        ):
            raise SQLValidationError(
                ErrorCode.PERMISSION_DENIED, "Trusted tenant scope is required"
            )

        aliases = {
            (table.alias or table.name).lower(): table.name.lower() for table in physical_tables
        }
        select = root if isinstance(root, exp.Select) else root.find(exp.Select)
        projection_aliases = {
            projection.alias.lower()
            for projection in (select.expressions if select is not None else ())
            if projection.alias
        }
        referenced_columns: list[str] = []
        for column in root.find_all(exp.Column):
            if isinstance(column.this, exp.Star):
                table_names = (
                    [aliases.get(column.table.lower(), column.table.lower())]
                    if column.table
                    else list(referenced_tables)
                )
                if any(
                    any(item.access.value != "allow" for item in allowed_tables[name].columns)
                    for name in table_names
                    if name in allowed_tables
                ):
                    raise SQLValidationError(
                        ErrorCode.COLUMN_NOT_ALLOWED,
                        "Wildcard selection is forbidden for tables with protected columns",
                    )
                continue
            name = column.name.lower()
            if column.table:
                table_name = aliases.get(column.table.lower(), column.table.lower())
                table = allowed_tables.get(table_name)
                if table is None or table.column(name) is None:
                    raise SQLValidationError(
                        ErrorCode.COLUMN_NOT_ALLOWED, f"Column is not allowed: {column.sql()}"
                    )
                referenced_columns.append(f"{table_name}.{name}")
            else:
                if name in projection_aliases:
                    continue
                matches = [
                    table_name
                    for table_name in referenced_tables
                    if allowed_tables[table_name].column(name) is not None
                ]
                if not matches and name != "*":
                    raise SQLValidationError(
                        ErrorCode.COLUMN_NOT_ALLOWED, f"Column is not allowed: {name}"
                    )
                referenced_columns.extend(f"{table_name}.{name}" for table_name in matches)

        joins = len(list(root.find_all(exp.Join)))
        if joins > self.config.max_join_tables:
            raise SQLValidationError(ErrorCode.QUERY_COST_EXCEEDED, "Query joins too many tables")
        selected_count = len(select.expressions) if select is not None else 0
        if selected_count > self.config.max_selected_columns:
            raise SQLValidationError(
                ErrorCode.QUERY_COST_EXCEEDED, "Query selects too many columns"
            )

        effective_max = min(max(1, int(max_rows or self.config.max_rows)), self.config.max_rows)
        applied_limit: int | None = None
        if select is not None and not _is_single_aggregate(select):
            current_limit = select.args.get("limit")
            current_value = None
            if current_limit is not None and isinstance(current_limit.expression, exp.Literal):
                try:
                    current_value = int(current_limit.expression.this)
                except (TypeError, ValueError):
                    current_value = None
            if current_value is None or current_value > effective_max:
                select.set("limit", exp.Limit(expression=exp.Literal.number(effective_max)))
                applied_limit = effective_max
            else:
                applied_limit = current_value

        output_columns = tuple(
            projection.alias_or_name
            for projection in (select.expressions if select is not None else ())
            if projection.alias_or_name
        )
        masked_output_columns: list[str] = []
        for projection in select.expressions if select is not None else ():
            output_name = projection.alias_or_name
            if not output_name:
                continue
            projection_columns = list(projection.find_all(exp.Column))
            if isinstance(projection, exp.Column):
                projection_columns.insert(0, projection)
            for column in projection_columns:
                table_names = (
                    [aliases.get(column.table.lower(), column.table.lower())]
                    if column.table
                    else list(referenced_tables)
                )
                if any(
                    (allowed_tables[table_name].column(column.name) is not None)
                    and (allowed_tables[table_name].column(column.name).access == ColumnAccess.MASK)
                    for table_name in table_names
                    if table_name in allowed_tables
                ):
                    masked_output_columns.append(output_name)
                    break
        return ValidatedSQL(
            sql=root.sql(dialect=dialect),
            referenced_tables=referenced_tables,
            referenced_columns=tuple(dict.fromkeys(referenced_columns)),
            output_columns=output_columns,
            masked_output_columns=tuple(dict.fromkeys(masked_output_columns)),
            applied_limit=applied_limit,
            join_count=joins,
            selected_column_count=selected_count,
        )


__all__ = [
    "SQLFunctionPolicy",
    "SQLGuardConfig",
    "SQLSafetyValidator",
    "SQLValidationError",
]
