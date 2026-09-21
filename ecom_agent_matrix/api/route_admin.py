"""Admin-only database and RAG management endpoints."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import get_current_security_context
from .errors import public_error
from ..core.errors import ErrorCode
from ..core.security import SecurityContext, tenant_scope_from_security
from ..db.base import AsyncPGClient
from ..db.redis_client import AsyncRedisClient
from ..modules.rag.preprocessor import clean_text, split_chunk

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class ProductPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]+$")
    category: str = Field(default="general", max_length=32)
    price: float = Field(ge=0, le=1_000_000)
    cost_price: float | None = Field(default=None, ge=0, le=1_000_000)
    stock_num: int = Field(default=0, ge=0, le=10_000_000)
    reorder_level: int = Field(default=20, ge=0, le=10_000_000)
    title_zh: str = Field(min_length=1, max_length=300)
    title_en: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=10_000)
    supplier: str = Field(default="", max_length=128)
    status: str = Field(default="active")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return value.upper()

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"active", "draft", "archived"}:
            raise ValueError("status must be active, draft or archived")
        return normalized

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip()[:40] for tag in value if tag.strip()))[:20]


class RAGDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=20, max_length=100_000)
    category: str = Field(default="general", max_length=80)
    language: str = Field(default="zh", max_length=8)
    effective_date: date = Field(default_factory=date.today)
    sku: str = Field(default="GENERAL", max_length=64)

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,99}", normalized):
            raise ValueError("document_id 只能包含小写字母、数字、下划线和连字符")
        return normalized


def require_admin(
    security: SecurityContext = Depends(get_current_security_context),
) -> SecurityContext:
    if not security.authenticated or "admin" not in security.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=public_error(ErrorCode.PERMISSION_DENIED),
        )
    return security


def _product(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "sku": row[0],
        "category": row[1] or "",
        "price": float(row[2] or 0),
        "cost_price": float(row[3]) if row[3] is not None else None,
        "stock_num": int(row[4] or 0),
        "reorder_level": int(row[5] or 0),
        "title_zh": row[6] or "",
        "title_en": row[7] or "",
        "description": row[8] or "",
        "supplier": row[9] or "",
        "status": row[10] or "active",
        "tags": list(row[11] or []),
        "updated_at": row[12].isoformat() if row[12] else "",
    }


async def _invalidate_rag_cache(security: SecurityContext) -> None:
    scope_hash = hashlib.sha256(
        f"{security.tenant_id}:{security.store_id}".encode("utf-8")
    ).hexdigest()[:20]
    try:
        client = await AsyncRedisClient.get_client()
        keys = [key async for key in client.scan_iter(match=f"rag:retrieve:*:{scope_hash}:*")]
        if keys:
            await client.delete(*keys)
    except Exception:
        # Cache invalidation is best effort; retrieval remains correct after TTL expiry.
        return


async def _audit_admin(
    security: SecurityContext,
    *,
    event_type: str,
    resource: str,
    action: str,
) -> None:
    """Best-effort mutation audit without exposing credentials or document contents."""
    try:
        await AsyncPGClient.execute_write(
            """INSERT INTO security_audit_log
            (event_type,task_id,tenant_id,store_id,user_id,agent_id,skill_name,outcome,
             reason_code,metadata_json)
            VALUES (%s,%s,%s,%s,%s,'admin_console','admin_data_management','success',NULL,%s::jsonb)""",
            [
                event_type,
                f"admin-{uuid.uuid4()}",
                security.tenant_id,
                security.store_id,
                security.user_id,
                json.dumps({"resource": resource, "action": action}, ensure_ascii=False),
            ],
            scope=tenant_scope_from_security(security),
        )
    except Exception:
        return


@router.get("/me")
async def admin_identity(security: SecurityContext = Depends(require_admin)):
    return {
        "is_admin": True,
        "user_id": security.user_id,
        "tenant_id": security.tenant_id,
        "store_id": security.store_id,
        "roles": sorted(security.roles),
    }


@router.get("/overview")
async def admin_overview(security: SecurityContext = Depends(require_admin)):
    scope = tenant_scope_from_security(security)
    product_rows = await AsyncPGClient.execute_read(
        """SELECT COUNT(*), COUNT(*) FILTER (WHERE status='active'),
        COALESCE(SUM(stock_num),0), COUNT(*) FILTER (WHERE stock_num <= reorder_level)
        FROM ecom_goods WHERE tenant_id=%s AND store_id=%s""",
        [security.tenant_id, security.store_id],
        scope=scope,
    )
    business_rows = await AsyncPGClient.execute_read(
        """SELECT
        (SELECT COUNT(*) FROM ecom_order WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(*) FROM competitor_price WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(*) FROM risk_record WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(DISTINCT COALESCE(meta_json->>'document_id', goods_sku))
           FROM vector_goods_kb WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(*) FROM vector_goods_kb WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(embedding) FROM vector_goods_kb WHERE tenant_id=%s AND store_id=%s)""",
        [security.tenant_id, security.store_id] * 6,
        scope=scope,
    )
    p = product_rows[0]
    b = business_rows[0]
    return {
        "products": int(p[0]),
        "active_products": int(p[1]),
        "stock_units": int(p[2]),
        "low_stock_products": int(p[3]),
        "orders": int(b[0]),
        "competitor_records": int(b[1]),
        "risk_records": int(b[2]),
        "rag_documents": int(b[3]),
        "rag_chunks": int(b[4]),
        "vector_chunks": int(b[5]),
        "retrieval_mode": "hybrid" if int(b[5]) else "lexical_only" if int(b[4]) else "none",
    }


@router.get("/products")
async def list_products(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    security: SecurityContext = Depends(require_admin),
):
    scope = tenant_scope_from_security(security)
    where = "WHERE tenant_id=%s AND store_id=%s"
    params: list[Any] = [security.tenant_id, security.store_id]
    if query.strip():
        where += (
            " AND (sku ILIKE %s OR title_zh ILIKE %s OR title_en ILIKE %s OR category ILIKE %s)"
        )
        pattern = f"%{query.strip()}%"
        params.extend([pattern] * 4)
    count_rows = await AsyncPGClient.execute_read(
        f"SELECT COUNT(*) FROM ecom_goods {where}", params, scope=scope
    )
    rows = await AsyncPGClient.execute_read(
        f"""SELECT sku,category,price,cost_price,stock_num,reorder_level,title_zh,title_en,
        desc_multi,supplier,status,tags,update_time FROM ecom_goods {where}
        ORDER BY update_time DESC, sku LIMIT %s OFFSET %s""",
        [*params, limit, offset],
        scope=scope,
    )
    return {"items": [_product(row) for row in rows], "total": int(count_rows[0][0])}


async def _save_product(
    payload: ProductPayload,
    security: SecurityContext,
    *,
    existing_sku: str | None = None,
) -> dict[str, Any]:
    scope = tenant_scope_from_security(security)
    params = [
        payload.sku,
        payload.category,
        payload.price,
        payload.cost_price,
        payload.stock_num,
        payload.reorder_level,
        payload.title_zh,
        payload.title_en,
        payload.description,
        payload.supplier,
        payload.status,
        payload.tags,
        security.tenant_id,
        security.store_id,
    ]
    if existing_sku is None:
        rows = await AsyncPGClient.execute_write(
            """INSERT INTO ecom_goods
            (sku,category,price,cost_price,stock_num,reorder_level,title_zh,title_en,
             desc_multi,supplier,status,tags,tenant_id,store_id,is_demo,update_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,NOW())
            ON CONFLICT (tenant_id,store_id,sku) DO NOTHING
            RETURNING sku,category,price,cost_price,stock_num,reorder_level,title_zh,title_en,
              desc_multi,supplier,status,tags,update_time""",
            params,
            scope=scope,
        )
        if not rows:
            raise HTTPException(
                status_code=409,
                detail=public_error(
                    ErrorCode.INVALID_REQUEST,
                    message=f"SKU {payload.sku} 已存在，请使用编辑功能。",
                ),
            )
        action = "create"
    else:
        rows = await AsyncPGClient.execute_write(
            """UPDATE ecom_goods SET sku=%s,category=%s,price=%s,cost_price=%s,stock_num=%s,
            reorder_level=%s,title_zh=%s,title_en=%s,desc_multi=%s,supplier=%s,status=%s,
            tags=%s,update_time=NOW()
            WHERE sku=%s AND tenant_id=%s AND store_id=%s
            RETURNING sku,category,price,cost_price,stock_num,reorder_level,title_zh,title_en,
              desc_multi,supplier,status,tags,update_time""",
            [*params[:12], existing_sku.upper(), security.tenant_id, security.store_id],
            scope=scope,
        )
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=public_error(
                    ErrorCode.INVALID_REQUEST, message=f"没有找到商品 {existing_sku}。"
                ),
            )
        action = "update"
    await _audit_admin(
        security,
        event_type="admin_product_changed",
        resource=payload.sku,
        action=action,
    )
    return _product(rows[0])


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductPayload,
    security: SecurityContext = Depends(require_admin),
):
    return {"message": "商品已创建。", "item": await _save_product(payload, security)}


@router.put("/products/{sku}")
async def update_product(
    sku: str,
    payload: ProductPayload,
    security: SecurityContext = Depends(require_admin),
):
    return {
        "message": "商品已更新。",
        "item": await _save_product(payload, security, existing_sku=sku),
    }


@router.delete("/products/{sku}")
async def delete_product(sku: str, security: SecurityContext = Depends(require_admin)):
    rows = await AsyncPGClient.execute_write(
        """DELETE FROM ecom_goods WHERE sku=%s AND tenant_id=%s AND store_id=%s
        RETURNING sku""",
        [sku.upper(), security.tenant_id, security.store_id],
        scope=tenant_scope_from_security(security),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=public_error(ErrorCode.INVALID_REQUEST, message=f"没有找到商品 {sku}。"),
        )
    await _audit_admin(
        security,
        event_type="admin_product_changed",
        resource=str(rows[0][0]),
        action="delete",
    )
    return {"message": f"商品 {rows[0][0]} 已删除。", "deleted": rows[0][0]}


@router.get("/rag/documents")
async def list_rag_documents(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=100, ge=1, le=300),
    security: SecurityContext = Depends(require_admin),
):
    scope = tenant_scope_from_security(security)
    where = "WHERE tenant_id=%s AND store_id=%s"
    params: list[Any] = [security.tenant_id, security.store_id]
    if query.strip():
        where += " AND (chunk_text ILIKE %s OR meta_json->>'title' ILIKE %s)"
        params.extend([f"%{query.strip()}%"] * 2)
    rows = await AsyncPGClient.execute_read(
        f"""SELECT COALESCE(meta_json->>'document_id', goods_sku) AS document_id,
        MAX(meta_json->>'title'), MAX(meta_json->>'category'), MAX(lang), COUNT(*),
        COUNT(embedding), MIN(LEFT(chunk_text, 180)), MAX(create_time)
        FROM vector_goods_kb {where}
        GROUP BY COALESCE(meta_json->>'document_id', goods_sku)
        ORDER BY MAX(create_time) DESC, document_id LIMIT %s""",
        [*params, limit],
        scope=scope,
    )
    return {
        "items": [
            {
                "document_id": row[0],
                "title": row[1] or row[0],
                "category": row[2] or "",
                "language": row[3] or "",
                "chunks": int(row[4]),
                "vector_chunks": int(row[5]),
                "preview": row[6] or "",
                "updated_at": row[7].isoformat() if row[7] else "",
            }
            for row in rows
        ]
    }


@router.get("/rag/documents/{document_id}")
async def get_rag_document(
    document_id: str,
    security: SecurityContext = Depends(require_admin),
):
    rows = await AsyncPGClient.execute_read(
        """SELECT goods_sku,lang,chunk_text,meta_json,create_time FROM vector_goods_kb
        WHERE COALESCE(meta_json->>'document_id', goods_sku)=%s
          AND tenant_id=%s AND store_id=%s ORDER BY id""",
        [document_id, security.tenant_id, security.store_id],
        scope=tenant_scope_from_security(security),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=public_error(
                ErrorCode.INVALID_REQUEST, message=f"没有找到知识文档 {document_id}。"
            ),
        )
    meta = rows[0][3] or {}
    return {
        "document_id": document_id,
        "title": meta.get("title") or document_id,
        "category": meta.get("category") or "general",
        "language": rows[0][1] or "zh",
        "effective_date": meta.get("effective_date") or "",
        "sku": rows[0][0] or "GENERAL",
        "content": "\n".join(str(row[2] or "") for row in rows),
        "chunks": len(rows),
    }


async def _save_rag_document(
    payload: RAGDocumentPayload,
    security: SecurityContext,
    *,
    document_id: str | None = None,
) -> dict[str, Any]:
    doc_id = document_id or payload.document_id or f"admin-{uuid.uuid4().hex[:12]}"
    content = clean_text(payload.content)
    chunks = split_chunk(content)
    records = []
    for index, chunk in enumerate(chunks):
        records.append(
            {
                "sku": payload.sku.upper(),
                "lang": payload.language.lower(),
                "chunk": chunk,
                "meta": {
                    "document_id": doc_id,
                    "chunk_id": f"{doc_id}:{index}",
                    "title": payload.title,
                    "category": payload.category,
                    "language": payload.language.lower(),
                    "effective_date": payload.effective_date.isoformat(),
                    "source": "admin-console",
                    "tenant_id": security.tenant_id,
                    "store_id": security.store_id,
                },
            }
        )
    rows = await AsyncPGClient.execute_write(
        """WITH deleted AS (
          DELETE FROM vector_goods_kb
          WHERE COALESCE(meta_json->>'document_id', goods_sku)=%s
            AND tenant_id=%s AND store_id=%s
        ), payload AS (
          SELECT * FROM jsonb_to_recordset(%s::jsonb)
          AS x(sku text, lang text, chunk text, meta jsonb)
        )
        INSERT INTO vector_goods_kb
          (tenant_id,store_id,goods_sku,lang,chunk_text,embedding,meta_json,create_time)
        SELECT %s,%s,sku,lang,chunk,NULL,meta,NOW() FROM payload
        RETURNING id""",
        [
            doc_id,
            security.tenant_id,
            security.store_id,
            json.dumps(records, ensure_ascii=False),
            security.tenant_id,
            security.store_id,
        ],
        scope=tenant_scope_from_security(security),
    )
    await _invalidate_rag_cache(security)
    await _audit_admin(
        security,
        event_type="admin_rag_changed",
        resource=doc_id,
        action="update" if document_id else "create",
    )
    return {
        "document_id": doc_id,
        "title": payload.title,
        "chunks": len(rows),
        "retrieval_mode": "lexical_only",
    }


@router.post("/rag/documents", status_code=status.HTTP_201_CREATED)
async def create_rag_document(
    payload: RAGDocumentPayload,
    security: SecurityContext = Depends(require_admin),
):
    return {
        "message": "知识文档已写入，立即可用于关键词检索。",
        "item": await _save_rag_document(payload, security),
    }


@router.put("/rag/documents/{document_id}")
async def update_rag_document(
    document_id: str,
    payload: RAGDocumentPayload,
    security: SecurityContext = Depends(require_admin),
):
    return {
        "message": "知识文档已更新。",
        "item": await _save_rag_document(payload, security, document_id=document_id),
    }


@router.delete("/rag/documents/{document_id}")
async def delete_rag_document(
    document_id: str,
    security: SecurityContext = Depends(require_admin),
):
    rows = await AsyncPGClient.execute_write(
        """DELETE FROM vector_goods_kb
        WHERE COALESCE(meta_json->>'document_id', goods_sku)=%s
          AND tenant_id=%s AND store_id=%s RETURNING id""",
        [document_id, security.tenant_id, security.store_id],
        scope=tenant_scope_from_security(security),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=public_error(
                ErrorCode.INVALID_REQUEST, message=f"没有找到知识文档 {document_id}。"
            ),
        )
    await _invalidate_rag_cache(security)
    await _audit_admin(
        security,
        event_type="admin_rag_changed",
        resource=document_id,
        action="delete",
    )
    return {"message": f"知识文档 {document_id} 已删除。", "deleted_chunks": len(rows)}


__all__ = ["router", "require_admin", "ProductPayload", "RAGDocumentPayload"]
