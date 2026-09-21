"""Inspectable lexical/semantic/alias schema linking with FK expansion."""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable

from .schemas import LinkedColumn, LinkedTable, SchemaCatalog, SchemaLinkResult

SemanticScorer = Callable[[str, list[str]], Awaitable[list[float]]]


def _tokens(text: str) -> list[str]:
    value = str(text or "").lower()
    latin = re.findall(r"[a-z0-9_]+", value)
    latin += [token[:-1] for token in latin if token.endswith("s") and len(token) > 3]
    cjk_segments = re.findall(r"[\u4e00-\u9fff]+", value)
    cjk = [
        segment[index : index + 2]
        for segment in cjk_segments
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


class HybridSchemaLinker:
    def __init__(self, semantic_scorer: SemanticScorer | None = None) -> None:
        self.semantic_scorer = semantic_scorer

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
        lexical = _bm25(query_tokens, table_documents)
        semantic = [0.0] * len(catalog.tables)
        if self.semantic_scorer and catalog.tables:
            try:
                values = await self.semantic_scorer(
                    question, [table.searchable_text for table in catalog.tables]
                )
                if len(values) == len(catalog.tables):
                    semantic = [max(0.0, min(float(value), 1.0)) for value in values]
            except Exception:
                semantic = [0.0] * len(catalog.tables)

        ranked: list[tuple[float, str, set[str], tuple[LinkedColumn, ...]]] = []
        normalized_question = question.lower()
        for index, table in enumerate(catalog.tables):
            reasons: set[str] = set()
            exact_terms = (table.name, *table.business_terms)
            exact = any(term.lower() in normalized_question for term in exact_terms if term)
            if exact:
                reasons.add("EXACT_ALIAS_MATCH")
            if lexical[index] > 0:
                reasons.add("LEXICAL_MATCH")
            if semantic[index] > 0:
                reasons.add("SEMANTIC_MATCH")
            table_score = lexical[index] + semantic[index] * 2 + (3 if exact else 0)
            linked_columns: list[LinkedColumn] = []
            for column in table.columns:
                column_tokens = _tokens(column.searchable_text)
                overlap = len(set(query_tokens).intersection(column_tokens))
                column_exact = any(
                    term.lower() in normalized_question
                    for term in (column.name, *column.business_terms)
                    if term
                )
                if overlap or column_exact or column.primary_key:
                    codes = (
                        ["COLUMN_TERM_MATCH"]
                        if overlap or column_exact
                        else ["PRIMARY_KEY_CONTEXT"]
                    )
                    linked_columns.append(
                        LinkedColumn(
                            name=column.name,
                            score=float(overlap + (2 if column_exact else 0)),
                            reason_codes=tuple(codes),
                        )
                    )
            if linked_columns:
                table_score += max(column.score for column in linked_columns)
                reasons.add("COLUMN_METADATA_MATCH")
            if table_score > 0:
                ranked.append(
                    (
                        table_score,
                        table.name,
                        reasons,
                        tuple(sorted(linked_columns, key=lambda item: (-item.score, item.name))),
                    )
                )

        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = ranked[: max(1, top_k)]
        selected_names = {item[1] for item in selected}
        expanded: dict[str, tuple[float, set[str], tuple[LinkedColumn, ...]]] = {
            name: (score, reasons, columns) for score, name, reasons, columns in selected
        }
        for relation in catalog.relations:
            if relation.from_table in selected_names and relation.to_table not in selected_names:
                expanded[relation.to_table] = (0.01, {"FK_EXPANSION"}, ())
            elif relation.to_table in selected_names and relation.from_table not in selected_names:
                expanded[relation.from_table] = (0.01, {"FK_EXPANSION"}, ())

        if not expanded and catalog.tables:
            fallback = catalog.tables[0]
            expanded[fallback.name] = (0.0, {"DETERMINISTIC_FALLBACK"}, ())

        linked_tables = tuple(
            LinkedTable(
                name=name,
                score=score,
                reason_codes=tuple(sorted(reasons)),
                columns=columns,
            )
            for name, (score, reasons, columns) in sorted(
                expanded.items(), key=lambda item: (-item[1][0], item[0])
            )
        )
        final_names = {table.name for table in linked_tables}
        relations = tuple(
            relation
            for relation in catalog.relations
            if relation.from_table in final_names and relation.to_table in final_names
        )
        return SchemaLinkResult(
            tables=linked_tables,
            relations=relations,
            candidate_count=len(catalog.tables),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )


__all__ = ["HybridSchemaLinker"]
