"""Embedding adapter shared by memory, retrieval and indexing."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.core.logging_config import setup_logger
from ecom_agent_matrix.db.redis_client import AsyncRedisClient

_embed_model = None
_CACHE_TTL = 3600
_HF_FALLBACK = "BAAI/bge-small-en-v1.5"
logger = setup_logger("infrastructure.embedding")


class EmbeddingProvider(Protocol):
    async def embed_text(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


def resolve_embed_model_name() -> str:
    raw = (settings.EMBED_MODEL_PATH or "").strip() or _HF_FALLBACK
    path = Path(raw)
    if path.exists():
        return str(path)
    return raw if "/" in raw and not raw.startswith(".") else _HF_FALLBACK


def get_embed_model() -> Any:
    global _embed_model
    if _embed_model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _embed_model = SentenceTransformer(resolve_embed_model_name(), device=device)
    return _embed_model


def _embedding_cache_key(text: str, model_identity: str | None = None) -> str:
    identity = model_identity or resolve_embed_model_name()
    version = identity.replace(":", "_").replace(" ", "_")
    digest = hashlib.sha256(f"{identity}\0{text}".encode()).hexdigest()
    return f"embed:{version}:{digest}"


async def get_text_embedding(text: str) -> list[float]:
    identity = resolve_embed_model_name()
    cache_key = _embedding_cache_key(text, identity)
    redis = None
    try:
        redis = await AsyncRedisClient.get_client()
        cached = await redis.get(cache_key)
        if cached:
            value = json.loads(cached)
            if isinstance(value, list):
                return value
    except Exception as exc:
        logger.warning(
            "embedding_cache_read_failed",
            extra={"event": "embedding_cache_read_failed", "error_type": type(exc).__name__},
        )
    model = await asyncio.wait_for(
        asyncio.to_thread(get_embed_model), timeout=float(settings.EMBEDDING_TIMEOUT_SECONDS)
    )
    vector = await asyncio.wait_for(
        asyncio.to_thread(model.encode, text), timeout=float(settings.EMBEDDING_TIMEOUT_SECONDS)
    )
    result = vector.tolist()
    try:
        redis = redis or await AsyncRedisClient.get_client()
        await redis.set(cache_key, json.dumps(result), ex=_CACHE_TTL)
    except Exception as exc:
        logger.warning(
            "embedding_cache_write_failed",
            extra={"event": "embedding_cache_write_failed", "error_type": type(exc).__name__},
        )
    return result


async def get_text_embeddings_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    model = await asyncio.wait_for(
        asyncio.to_thread(get_embed_model), timeout=float(settings.EMBEDDING_TIMEOUT_SECONDS)
    )

    def encode():
        values = model.encode(texts, batch_size=batch_size, show_progress_bar=False)
        return [row.tolist() for row in values]

    return await asyncio.wait_for(
        asyncio.to_thread(encode), timeout=float(settings.EMBEDDING_TIMEOUT_SECONDS)
    )


class LocalEmbeddingProvider:
    async def embed_text(self, text: str) -> list[float]:
        return await get_text_embedding(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await get_text_embeddings_batch(texts)


__all__ = [
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "get_embed_model",
    "get_text_embedding",
    "get_text_embeddings_batch",
    "resolve_embed_model_name",
]
