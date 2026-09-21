"""Inspectable lexical/semantic/alias schema linking with controlled FK expansion."""

from __future__ import annotations

import inspect
import math
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Protocol

from ...config.settings import settings
from .schemas import LinkedColumn, LinkedTable, SchemaCatalog, SchemaLinkResult

LegacySemanticScorer = Callable[[str, list[str]], Awaitable[list[float]]]


class CatalogSemanticScorer(Protocol):
    async def score(self, question: str, catalog: SchemaCatalog) -> list[float]: ...


def _tokens(text: str) -> list[str]:
    value = str(text or "").lower()
    latin = re.findall(r"[a-z0-9_]+", value)
    latin += [token[:-1] for token in latin if token.endswith("s") and len(token) > 3]
    segments = re.findall(r"[\u4e00-\u9fff]+", value)
    cjk = [
        segment[index : index + 2]
        for segment in segments
        for index in range(max(1, len(segment) - 1))
    ]
    return latin + cjk


def _bm25(query: list[str], documents: list[list[str]]) -> list[float]:
    if not documents:
        return []
    average_length = sum(len(document) for document in documents) / max(len(documents), 1)
    document_frequency = Counter(
        token for token in set(query) for document in documents if token in document
    )
    scores: list[float] = []
    for document in documents:
        frequencies = Counter(document)
        score = 0.0
        for token in set(query):
            frequency = frequencies[token]
            if not frequency:
                continue
            occurrences = document_frequency[token]
            inverse = math.log(1 + (len(documents) - occurrences + 0.5) / (occurrences + 0.5))
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(document) / max(average_length, 1)
            )
            score += inverse * frequency * 2.5 / denominator
        scores.append(score)
    return scores


def _normalize(values: list[float]) -> list[float]:
    maximum = max(values, default=0.0)
    return [value / maximum if maximum > 0 else 0.0 for value in values]


def _term_match(question: str, terms: tuple[str, ...]) -> bool:
    normalized = question.lower()
    return any(term and term.lower() in normalized for term in terms)


class HybridSchemaLinker:
    def __init__(
        self,
        semantic_scorer: CatalogSemanticScorer | LegacySemanticScorer | None = None,
        *,
        absolute_threshold: float | None = None,
        relative_threshold: float | None = None,
    ) -> None:
        self.semantic_scorer = semantic_scorer
        self.absolute_threshold = float(
            settings.SQL_SCHEMA_LINK_ABSOLUTE_THRESHOLD
            if absolute_threshold is None
            else absolute_threshold
        )
        self.relative_threshold = float(
            settings.SQL_SCHEMA_LINK_RELATIVE_THRESHOLD
            if relative_threshold is None
            else relative_threshold
        )

    async def _semantic_scores(
        self, question: str, catalog: SchemaCatalog
    ) -> tuple[list[float], str]:
        scorer = self.semantic_scorer
        if scorer is None or not catalog.tables:
            return [0.0] * len(catalog.tables), "lexical_only"
        try:
            score_method = getattr(scorer, "score", None)
            if score_method is not None and inspect.isroutine(score_method):
                values = await score_method(question, catalog)
            else:
                values = await scorer(question, [table.searchable_text for table in catalog.tables])
            if len(values) != len(catalog.tables):
                return [0.0] * len(catalog.tables), "lexical_only"
            return [max(0.0, min(float(value), 1.0)) for value in values], "hybrid"
        except Exception:
            return [0.0] * len(catalog.tables), "lexical_only"

    async def link(
        self,
        question: str,
        catalog: SchemaCatalog,
        *,
        task_type: str = "data_analysis",
        top_k: int = 6,
    ) -> SchemaLinkResult:
        started = time.perf_counter()
        query_tokens = _tokens(f"{question} {task_type}")
        table_documents = [_tokens(table.searchable_text) for table in catalog.tables]
        lexical = _normalize(_bm25(query_tokens, table_documents))
        semantic, retrieval_mode = await self._semantic_scores(question, catalog)

        ranked: list[tuple[float, str, set[str], list[LinkedColumn], float]] = []
        for index, table in enumerate(catalog.tables):
            reasons: set[str] = set()
            table_exact = _term_match(question, (table.name, *table.business_terms))
            if table_exact:
                reasons.add("EXACT_ALIAS_MATCH")
            if lexical[index] > 0:
                reasons.add("LEXICAL_MATCH")
            if semantic[index] > 0:
                reasons.add("SEMANTIC_MATCH")

            linked_columns: list[LinkedColumn] = []
            strongest_column = 0.0
            query_set = set(query_tokens)
            for column in table.columns:
                column_tokens = set(_tokens(column.searchable_text))
                overlap = len(query_set.intersection(column_tokens))
                exact = _term_match(question, (column.name, *column.business_terms))
                score = min(1.0, (0.75 if exact else 0.0) + min(overlap * 0.25, 0.75))
                if score < 0.5:
                    continue
                codes = ["COLUMN_EXACT_MATCH" if exact else "COLUMN_LEXICAL_MATCH"]
                linked_columns.append(
                    LinkedColumn(name=column.name, score=score, reason_codes=tuple(codes))
                )
                strongest_column = max(strongest_column, score)

            table_score = (
                lexical[index] * 0.45
                + semantic[index] * 0.25
                + strongest_column * 0.45
                + (0.55 if table_exact else 0.0)
            )
            if linked_columns:
                reasons.add("COLUMN_METADATA_MATCH")
            if table_score > 0:
                ranked.append((table_score, table.name, reasons, linked_columns, strongest_column))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        top_score = ranked[0][0] if ranked else 0.0
        selected = [
            item
            for item in ranked
            if item[0] >= self.absolute_threshold
            and (item[0] >= top_score * self.relative_threshold or "EXACT_ALIAS_MATCH" in item[2])
        ][: max(1, top_k)]
        if not selected and ranked:
            selected = ranked[:1]

        selected_names = {item[1] for item in selected}
        by_name = {item[1]: item for item in ranked}
        join_intent = bool(
            re.search(r"\bby\b|按.*(?:品类|商品|sku)|对比|compare|contribut|导致", question, re.I)
        )
        for relation in catalog.relations:
            for origin, neighbor in (
                (relation.from_table, relation.to_table),
                (relation.to_table, relation.from_table),
            ):
                candidate = by_name.get(neighbor)
                if origin not in selected_names or neighbor in selected_names or candidate is None:
                    continue
                strong_column_intent = candidate[4] >= 0.75
                strong_table_evidence = candidate[0] >= max(
                    self.absolute_threshold, top_score * 0.7
                )
                if join_intent and (strong_column_intent or strong_table_evidence):
                    candidate[2].add("FK_EXPANSION")
                    selected.append(candidate)
                    selected_names.add(neighbor)
                    break
            if len(selected) >= max(1, top_k):
                break

        if not selected and catalog.tables:
            selected = [(0.0, catalog.tables[0].name, {"DETERMINISTIC_FALLBACK"}, [], 0.0)]
            selected_names = {catalog.tables[0].name}

        required_join_columns: dict[str, set[str]] = {}
        relations = []
        for relation in catalog.relations:
            if relation.from_table in selected_names and relation.to_table in selected_names:
                relations.append(relation)
                required_join_columns.setdefault(relation.from_table, set()).add(
                    relation.from_column
                )
                required_join_columns.setdefault(relation.to_table, set()).add(relation.to_column)

        linked_tables: list[LinkedTable] = []
        for score, name, reasons, columns, _ in sorted(
            selected, key=lambda item: (-item[0], item[1])
        ):
            existing = {column.name for column in columns}
            for column_name in sorted(required_join_columns.get(name, set())):
                if column_name not in existing:
                    columns.append(
                        LinkedColumn(
                            name=column_name,
                            score=0.01,
                            reason_codes=("REQUIRED_JOIN_KEY",),
                        )
                    )
            linked_tables.append(
                LinkedTable(
                    name=name,
                    score=score,
                    reason_codes=tuple(sorted(reasons)),
                    columns=tuple(sorted(columns, key=lambda item: (-item.score, item.name))),
                )
            )
        return SchemaLinkResult(
            tables=tuple(linked_tables),
            relations=tuple(relations),
            candidate_count=len(catalog.tables),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            retrieval_mode=retrieval_mode,
        )


__all__ = ["CatalogSemanticScorer", "HybridSchemaLinker", "LegacySemanticScorer"]
