"""自动化运营任务接口（经 Master Fast Path / Typed DAG / Recovery）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .auth import get_current_approval_grant, get_current_security_context
from .dispatch import dispatch_to_master
from .schemas import ApiResult, TaskCreateRequest
from ..config.constants import MSG_PRIORITY_NORMAL
from ..core.security import SecurityContext, authorize_task
from ..core.security import ApprovalGrant
from ..core.security.errors import AuthorizationError
from fastapi import HTTPException, status
from ..platform.resilience.rate_limit import enforce_business_rate_limit

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("", response_model=ApiResult, dependencies=[Depends(enforce_business_rate_limit)])
async def create_task(
    body: TaskCreateRequest,
    security: SecurityContext = Depends(get_current_security_context),
    approval: ApprovalGrant | None = Depends(get_current_approval_grant),
) -> ApiResult:
    content = {
        "query": body.query,
        **(body.payload or {}),
    }
    if body.task_type:
        content["task_type"] = body.task_type
        try:
            authorize_task(security, body.task_type)
        except AuthorizationError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="PERMISSION_DENIED"
            ) from None
    priority = body.priority if body.priority is not None else MSG_PRIORITY_NORMAL
    result = await dispatch_to_master(
        content, priority=priority, timeout=body.timeout, security=security, approval=approval
    )
    return ApiResult(**result)
