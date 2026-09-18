"""Trusted identity and authorization boundary."""

from .context import SecurityContext, security_log_fields
from .errors import (
    AuthenticationError,
    AuthorizationError,
    SecurityConfigurationError,
)
from .policy import (
    authorize_task,
    authorize_task_types,
    effective_scopes,
    is_task_authorized,
    required_scopes_for_task,
    require_trusted_ingress,
)
from .scope import (
    TenantScope,
    require_tenant_scope,
    tenant_scope_from_security,
    tenant_scope_from_skill_context,
    tenant_scope_from_task_context,
)
from .approval_models import ApprovalGrant, ApprovalRequest

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "SecurityConfigurationError",
    "SecurityContext",
    "authorize_task",
    "authorize_task_types",
    "effective_scopes",
    "is_task_authorized",
    "required_scopes_for_task",
    "security_log_fields",
    "require_trusted_ingress",
    "TenantScope",
    "require_tenant_scope",
    "tenant_scope_from_security",
    "tenant_scope_from_skill_context",
    "tenant_scope_from_task_context",
    "ApprovalGrant",
    "ApprovalRequest",
]
