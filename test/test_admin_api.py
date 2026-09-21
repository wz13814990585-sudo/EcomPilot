from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from ecom_agent_matrix.api.main import app
from ecom_agent_matrix.api.route_admin import (
    ProductPayload,
    admin_overview,
    require_admin,
)
from ecom_agent_matrix.core.security import SecurityContext


def _security(*roles: str) -> SecurityContext:
    return SecurityContext(
        subject="user-1",
        user_id="user-1",
        tenant_id="tenant-a",
        store_id="store-a",
        roles=frozenset(roles),
        scopes=frozenset(),
        auth_type="api_key",
        authenticated=True,
    )


def test_admin_routes_are_registered():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/admin/me" in paths
    assert "/api/v1/admin/overview" in paths
    assert "/api/v1/admin/products" in paths
    assert "/api/v1/admin/rag/documents" in paths


def test_admin_role_is_checked_server_side():
    with pytest.raises(HTTPException) as denied:
        require_admin(_security("operator"))
    assert denied.value.status_code == 403
    assert require_admin(_security("admin")).user_id == "user-1"


def test_product_payload_normalizes_and_bounds_admin_input():
    item = ProductPayload(
        sku="hike-101",
        title_zh="演示登山杖",
        price=29.9,
        stock_num=10,
        tags=[" 户外 ", "户外", "新品"],
    )
    assert item.sku == "HIKE-101"
    assert item.tags == ["户外", "新品"]


def test_admin_overview_uses_scoped_read_pool():
    execute = AsyncMock(
        side_effect=[
            [(48, 47, 2200, 9)],
            [(720, 160, 12, 30, 30, 0)],
        ]
    )
    with patch("ecom_agent_matrix.api.route_admin.AsyncPGClient.execute_read", new=execute):
        result = asyncio.run(admin_overview(_security("admin")))
    assert result["products"] == 48
    assert result["rag_documents"] == 30
    assert result["retrieval_mode"] == "lexical_only"
    assert all(call.kwargs["scope"].usable for call in execute.await_args_list)
