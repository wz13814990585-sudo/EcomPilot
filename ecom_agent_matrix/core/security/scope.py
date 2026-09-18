"""Trusted tenant/store data scope shared by DB, RAG and memory layers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TenantScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    tenant_id: str = ""
    store_id: str = ""
    identity_trusted: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.identity_trusted and self.tenant_id and self.store_id)


def tenant_scope_from_security(security: Any | None) -> TenantScope:
    return TenantScope(
        tenant_id=str(getattr(security, "tenant_id", "") or ""),
        store_id=str(getattr(security, "store_id", "") or ""),
        identity_trusted=bool(getattr(security, "authenticated", False)),
    )


def tenant_scope_from_task_context(context: Any | None) -> TenantScope:
    """Compatibility adapter; only authenticated security-like objects are trusted.

    A TaskContext may carry tenant/store identifiers for business routing and tracing,
    but its ``identity_trusted`` field is not an authentication authority.
    """
    return TenantScope(
        tenant_id=str(getattr(context, "tenant_id", "") or ""),
        store_id=str(getattr(context, "store_id", "") or ""),
        identity_trusted=bool(getattr(context, "authenticated", False)),
    )


def tenant_scope_from_skill_context(context: Any | None = None) -> TenantScope:
    try:
        from ..skill.skill_registry import (
            SkillExecutionContext,
            current_skill_execution_context,
        )
    except ImportError:
        return TenantScope()
    if context is None:
        context = current_skill_execution_context()
    if not isinstance(context, SkillExecutionContext):
        return TenantScope()
    return TenantScope(
        tenant_id=str(getattr(context, "tenant_id", "") or ""),
        store_id=str(getattr(context, "store_id", "") or ""),
        identity_trusted=bool(getattr(context, "identity_trusted", False)),
    )


def require_tenant_scope(scope: TenantScope, *, production: bool) -> TenantScope:
    if production and not scope.usable:
        raise PermissionError("TENANT_SCOPE_REQUIRED")
    return scope


__all__ = [
    "TenantScope",
    "require_tenant_scope",
    "tenant_scope_from_security",
    "tenant_scope_from_skill_context",
    "tenant_scope_from_task_context",
]
