"""Optional semantic schema scoring over the repository embedding abstraction."""

from __future__ import annotations

import asyncio
import hashlib
import math
from pathlib import Path

from ...config.settings import settings
from ...infrastructure.embedding.provider import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    resolve_embed_model_name,
)
from .schemas import SchemaCatalog


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, (numerator / (left_norm * right_norm) + 1.0) / 2.0))


class SchemaSemanticScorer:
    """Caches stable schema vectors while embedding each question once."""

    def __init__(self, provider: EmbeddingProvider, *, model_version: str) -> None:
        self.provider = provider
        self.model_version = model_version
        self._cache: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(catalog: SchemaCatalog, table_name: str, searchable_text: str, model: str) -> str:
        digest = hashlib.sha256(searchable_text.encode("utf-8")).hexdigest()
        return f"{catalog.version}:{table_name}:{model}:{digest}"

    async def score(self, question: str, catalog: SchemaCatalog) -> list[float]:
        keys = [
            self._key(catalog, table.name, table.searchable_text, self.model_version)
            for table in catalog.tables
        ]
        missing = [index for index, key in enumerate(keys) if key not in self._cache]
        if missing:
            texts = [catalog.tables[index].searchable_text for index in missing]
            vectors = await self.provider.embed_batch(texts)
            if len(vectors) != len(texts):
                raise ValueError("semantic provider returned an invalid schema vector count")
            async with self._lock:
                for index, vector in zip(missing, vectors, strict=True):
                    self._cache[keys[index]] = [float(value) for value in vector]
        question_vector = [float(value) for value in await self.provider.embed_text(question)]
        return [_cosine(question_vector, self._cache[key]) for key in keys]

    def cache_keys(self) -> frozenset[str]:
        return frozenset(self._cache)


def default_schema_semantic_scorer() -> SchemaSemanticScorer | None:
    """Enable local semantics only when the configured model is already present.

    This keeps deterministic CI offline and avoids an implicit model download. Deployments
    that mount a model path get true hybrid retrieval automatically; callers may also inject
    any ``EmbeddingProvider`` explicitly.
    """

    configured = Path(str(settings.EMBED_MODEL_PATH or "").strip())
    if not settings.SCHEMA_SEMANTIC_ENABLED or not configured.exists():
        return None
    return SchemaSemanticScorer(
        LocalEmbeddingProvider(),
        model_version=resolve_embed_model_name(),
    )


__all__ = ["SchemaSemanticScorer", "default_schema_semantic_scorer"]
