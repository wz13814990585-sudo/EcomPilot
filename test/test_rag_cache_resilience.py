from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from ecom_agent_matrix.config.settings import settings
from ecom_agent_matrix.infrastructure.embedding import provider as embedding
from ecom_agent_matrix.modules.rag import retriever
from ecom_agent_matrix.modules.rag.schemas import HybridRetrievalResult


class _Vector:
    def tolist(self):
        return [0.1, 0.2]


class _Model:
    def encode(self, text):
        return _Vector()


def test_retrieval_cache_key_contains_both_versions(monkeypatch):
    monkeypatch.setattr(settings, "RAG_INDEX_VERSION", "index-a")
    monkeypatch.setattr(settings, "RAG_RETRIEVAL_VERSION", "retrieval-a")
    first = retriever._cache_key("q", "en", None, 8)
    assert "index-a" in first and "retrieval-a" in first
    monkeypatch.setattr(settings, "RAG_INDEX_VERSION", "index-b")
    second = retriever._cache_key("q", "en", None, 8)
    monkeypatch.setattr(settings, "RAG_RETRIEVAL_VERSION", "retrieval-b")
    third = retriever._cache_key("q", "en", None, 8)
    assert len({first, second, third}) == 3


def test_corrupted_retrieval_cache_is_a_miss():
    async def scenario():
        redis = AsyncMock()
        redis.get.return_value = "not-json"
        with patch(
            "ecom_agent_matrix.modules.rag.retriever.AsyncRedisClient.get_client",
            new=AsyncMock(return_value=redis),
        ):
            return await retriever._load_cache("key")

    assert asyncio.run(scenario()) is None


def test_redis_read_and_write_failures_do_not_block_retrieval():
    async def read_failure():
        with (
            patch(
                "ecom_agent_matrix.modules.rag.retriever.AsyncRedisClient.get_client",
                new=AsyncMock(side_effect=ConnectionError("redis password=secret")),
            ),
            patch(
                "ecom_agent_matrix.modules.rag.retriever._hybrid_retrieve_detailed_uncached",
                new=AsyncMock(
                    return_value=HybridRetrievalResult(
                        success=True,
                        raw_documents=[{"chunk_text": "real result"}],
                        mode="hybrid",
                    )
                ),
            ),
        ):
            return await retriever.hybrid_retrieve("q", "en", top_k=1)

    async def write_failure():
        redis = AsyncMock()
        redis.get.return_value = None
        redis.set.side_effect = ConnectionError("redis down")
        with (
            patch(
                "ecom_agent_matrix.modules.rag.retriever.AsyncRedisClient.get_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "ecom_agent_matrix.modules.rag.retriever._hybrid_retrieve_detailed_uncached",
                new=AsyncMock(
                    return_value=HybridRetrievalResult(
                        success=True,
                        raw_documents=[{"chunk_text": "real result"}],
                        mode="hybrid",
                    )
                ),
            ),
        ):
            return await retriever.hybrid_retrieve("q", "en", top_k=1)

    assert asyncio.run(read_failure())[0][0]["chunk_text"] == "real result"
    assert asyncio.run(write_failure())[0][0]["chunk_text"] == "real result"


def test_degraded_retrieval_cache_preserves_mode_and_metadata():
    async def scenario():
        stored = {}
        redis = AsyncMock()

        async def get(key):
            return stored.get(key)

        async def set_value(key, value, **_kwargs):
            stored[key] = value

        redis.get.side_effect = get
        redis.set.side_effect = set_value
        degraded = HybridRetrievalResult(
            success=True,
            raw_documents=[{"source_id": "L", "chunk_text": "lexical"}],
            mode="lexical_only",
            degraded=True,
            channel_errors={"vector": "EMBEDDING_ERROR"},
            candidate_counts={"vector": 0, "lexical": 1, "fused": 1, "reranked": 1},
        )
        with (
            patch(
                "ecom_agent_matrix.modules.rag.retriever.AsyncRedisClient.get_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "ecom_agent_matrix.modules.rag.retriever._hybrid_retrieve_detailed_uncached",
                new=AsyncMock(return_value=degraded),
            ) as retrieve,
        ):
            first = await retriever.hybrid_retrieve_detailed("refund", "en")
            second = await retriever.hybrid_retrieve_detailed("refund", "en")
        return first, second, retrieve.await_count

    first, cached, calls = asyncio.run(scenario())
    assert first.mode == "lexical_only" and first.degraded
    assert cached.cached and cached.mode == "lexical_only" and cached.degraded
    assert cached.channel_errors == {"vector": "EMBEDDING_ERROR"}
    assert calls == 1


def test_embedding_key_is_stable_and_model_scoped():
    first = embedding._embedding_cache_key("hello", "model-a")
    repeated = embedding._embedding_cache_key("hello", "model-a")
    other_model = embedding._embedding_cache_key("hello", "model-b")
    assert first == repeated
    assert first != other_model
    assert "model-a" in first
    assert "hash(" not in first


def test_embedding_redis_failure_falls_back_to_real_model():
    async def scenario():
        with (
            patch(
                "ecom_agent_matrix.infrastructure.embedding.provider.AsyncRedisClient.get_client",
                new=AsyncMock(side_effect=ConnectionError("redis unavailable")),
            ),
            patch(
                "ecom_agent_matrix.infrastructure.embedding.provider.get_embed_model",
                return_value=_Model(),
            ),
            patch(
                "ecom_agent_matrix.infrastructure.embedding.provider.resolve_embed_model_name",
                return_value="model-a",
            ),
        ):
            return await embedding.get_text_embedding("hello")

    assert asyncio.run(scenario()) == [0.1, 0.2]


def test_embedding_corrupt_cache_falls_back_to_real_model():
    async def scenario():
        redis = AsyncMock()
        redis.get.return_value = "broken-json"
        with (
            patch(
                "ecom_agent_matrix.infrastructure.embedding.provider.AsyncRedisClient.get_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "ecom_agent_matrix.infrastructure.embedding.provider.get_embed_model",
                return_value=_Model(),
            ),
            patch(
                "ecom_agent_matrix.infrastructure.embedding.provider.resolve_embed_model_name",
                return_value="model-a",
            ),
        ):
            return await embedding.get_text_embedding("hello")

    assert asyncio.run(scenario()) == [0.1, 0.2]
