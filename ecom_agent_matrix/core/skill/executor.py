"""统一 Skill 执行器。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic import ValidationError

from ...config.constants import AGENT_EXEC, AGENT_QUERY
from ..errors import ErrorCode
from .base_skill import SkillResult
from .idempotency import (
    IdempotencyStore,
    default_idempotency_store,
    idempotency_key,
)
from .skill_registry import (
    SkillExecutionContext,
    current_skill_execution_context,
    lookup_skill,
)
from ..security.policy import effective_scopes
from ..security.approval import (
    APPROVAL_ALREADY_USED,
    APPROVAL_EXPIRED,
    APPROVAL_INVALID,
    APPROVAL_REQUIRED,
    approval_params_hash,
    approval_service,
)
from ..security.audit import record_audit_event
from ..security.scope import TenantScope
from ...platform.observability.context import update_trace_context
from ...platform.observability.metrics import metrics

SKILL_NOT_FOUND = ErrorCode.SKILL_NOT_FOUND.value
PERMISSION_DENIED = ErrorCode.PERMISSION_DENIED.value
VALIDATION_ERROR = ErrorCode.VALIDATION_ERROR.value
TIMEOUT = ErrorCode.SKILL_TIMEOUT.value
EXECUTION_ERROR = ErrorCode.SKILL_EXECUTION_ERROR.value
OUTPUT_VALIDATION_ERROR = ErrorCode.OUTPUT_VALIDATION_ERROR.value
SKILL_FAILED = ErrorCode.SKILL_FAILED.value

logger = logging.getLogger("skill.executor")


class SkillExecutor:
    """完成查找、鉴权、契约校验、超时控制和结果标准化。"""

    def __init__(
        self,
        idempotency_store: IdempotencyStore | None = None,
        *,
        approval_service_instance=None,
    ) -> None:
        self.idempotency_store = idempotency_store or default_idempotency_store
        self.approval_service = approval_service_instance

    async def execute(
        self,
        skill_name: str,
        params: dict,
        *,
        context: SkillExecutionContext | None = None,
    ) -> SkillResult:
        started = time.perf_counter()
        update_trace_context(skill_name=skill_name)
        effective_context = context or current_skill_execution_context()
        skill_cls = lookup_skill(skill_name)

        if skill_cls is None:
            return self._error(
                SKILL_NOT_FOUND,
                f"不存在该工具：{skill_name}",
                skill_name,
                started,
                effective_context,
            )

        spec = skill_cls.spec()
        if spec.deprecated:
            logger.warning(
                "deprecated_skill_execution",
                extra={
                    "event": "deprecated_skill_execution",
                    "skill_name": skill_name,
                    "replacement": spec.replacement or "",
                },
            )
        denied_reason = self._permission_denied_reason(spec, effective_context)
        if denied_reason:
            return self._error(
                PERMISSION_DENIED,
                denied_reason,
                skill_name,
                started,
                effective_context,
                spec=spec,
            )

        # Authorization precedes parameter parsing so an unauthorized caller
        # cannot probe a write Skill's input contract.
        if self._requires_trusted_identity(spec):
            # _permission_denied_reason already proved this context exists and
            # carries a verified, complete identity.
            granted_scopes = effective_scopes(effective_context)  # type: ignore[arg-type]
            if spec.required_scopes and not spec.required_scopes.issubset(granted_scopes):
                return self._error(
                    PERMISSION_DENIED,
                    f"Skill scope permission denied: {skill_name}",
                    skill_name,
                    started,
                    effective_context,
                    spec=spec,
                )

        try:
            validated_params = self._validate_input(spec.input_model, params)
        except (ValidationError, TypeError, ValueError) as exc:
            return self._error(
                VALIDATION_ERROR,
                f"Skill 输入参数校验失败：{type(exc).__name__}",
                skill_name,
                started,
                effective_context,
                spec=spec,
            )

        params_hash = ""
        approval_id = ""
        idempotency_token = ""
        idempotency_scope = None
        if spec.idempotent and self._requires_trusted_identity(spec):
            idempotency_scope = TenantScope(
                tenant_id=effective_context.tenant_id,
                store_id=effective_context.store_id,
                identity_trusted=True,
            )
            idempotency_token = idempotency_key(
                tenant_id=effective_context.tenant_id,
                store_id=effective_context.store_id,
                task_id=effective_context.task_id,
                skill_name=skill_name,
                params=validated_params,
            )
            existing = await self.idempotency_store.get(idempotency_token, scope=idempotency_scope)
            if existing is not None:
                if existing.status == "succeeded" and existing.result:
                    replay = SkillResult.model_validate(existing.result)
                    replay.metadata = {**replay.metadata, "idempotent_replay": True}
                    return replay
                return self._error(
                    ErrorCode.ALREADY_EXECUTED.value,
                    "Identical side effect already started or completed",
                    skill_name,
                    started,
                    effective_context,
                    spec=spec,
                )
        if spec.approval_required:
            active_approval_service = self.approval_service or approval_service
            params_hash = approval_params_hash(skill_name, validated_params)
            if effective_context.approval is None:
                try:
                    request = await active_approval_service.create_pending(
                        context=effective_context,
                        skill_name=skill_name,
                        params_hash=params_hash,
                    )
                except Exception:
                    return self._error(
                        EXECUTION_ERROR,
                        "Approval service unavailable",
                        skill_name,
                        started,
                        effective_context,
                        spec=spec,
                    )
                return self._error(
                    APPROVAL_REQUIRED,
                    "High-risk execution requires human approval",
                    skill_name,
                    started,
                    effective_context,
                    spec=spec,
                    data={
                        "approval_required": True,
                        "approval_id": request.approval_id,
                        "skill_name": skill_name,
                    },
                )
            approval_id = effective_context.approval.approval_id
            try:
                await active_approval_service.consume(
                    effective_context.approval,
                    context=effective_context,
                    skill_name=skill_name,
                    params_hash=params_hash,
                )
            except PermissionError as exc:
                code = (
                    str(exc)
                    if str(exc) in {APPROVAL_EXPIRED, APPROVAL_ALREADY_USED, APPROVAL_INVALID}
                    else APPROVAL_INVALID
                )
                return self._error(
                    code,
                    "Approval is invalid or unavailable",
                    skill_name,
                    started,
                    effective_context,
                    spec=spec,
                )
            await self._audit_high_risk(
                "HIGH_RISK_EXECUTION_STARTED",
                effective_context,
                skill_name,
                approval_id,
                "started",
            )

        if idempotency_token and idempotency_scope is not None:
            acquired = await self.idempotency_store.begin(
                idempotency_token,
                scope=idempotency_scope,
                task_id=effective_context.task_id,
                skill_name=skill_name,
            )
            if not acquired:
                return self._error(
                    ErrorCode.ALREADY_EXECUTED.value,
                    "Identical side effect already started or completed",
                    skill_name,
                    started,
                    effective_context,
                    spec=spec,
                )

        try:
            raw_result = await asyncio.wait_for(
                skill_cls().run(validated_params),
                timeout=spec.timeout_seconds,
            )
        except asyncio.TimeoutError:
            await self._mark_idempotency_failed(
                idempotency_token, idempotency_scope, ErrorCode.SKILL_TIMEOUT.value
            )
            await self._audit_high_risk(
                "HIGH_RISK_EXECUTION_FAILED",
                effective_context,
                skill_name,
                approval_id,
                "timeout",
            )
            return self._error(
                TIMEOUT,
                f"Skill 执行超时（>{spec.timeout_seconds:g}s）",
                skill_name,
                started,
                effective_context,
                spec=spec,
            )
        except Exception as exc:
            await self._mark_idempotency_failed(
                idempotency_token,
                idempotency_scope,
                ErrorCode.SKILL_EXECUTION_ERROR.value,
            )
            logger.exception(
                "skill_execution_exception",
                extra={
                    "event": "skill_execution_exception",
                    "skill_name": skill_name,
                    "agent_id": effective_context.agent_id if effective_context else "",
                    "error_type": type(exc).__name__,
                },
            )
            await self._audit_high_risk(
                "HIGH_RISK_EXECUTION_FAILED",
                effective_context,
                skill_name,
                approval_id,
                "failed",
            )
            return self._error(
                EXECUTION_ERROR,
                f"Skill 执行失败：{type(exc).__name__}",
                skill_name,
                started,
                effective_context,
                spec=spec,
            )

        if not isinstance(raw_result, SkillResult):
            await self._mark_idempotency_failed(
                idempotency_token,
                idempotency_scope,
                ErrorCode.OUTPUT_VALIDATION_ERROR.value,
            )
            await self._audit_high_risk(
                "HIGH_RISK_EXECUTION_FAILED",
                effective_context,
                skill_name,
                approval_id,
                "output_validation_failed",
            )
            return self._error(
                OUTPUT_VALIDATION_ERROR,
                "Skill 返回值不是 SkillResult",
                skill_name,
                started,
                effective_context,
                spec=spec,
            )

        if raw_result.success and spec.output_model is not None:
            try:
                validated_output = spec.output_model.model_validate(raw_result.data)
                raw_result.data = validated_output.model_dump()
            except (ValidationError, TypeError, ValueError) as exc:
                await self._mark_idempotency_failed(
                    idempotency_token,
                    idempotency_scope,
                    ErrorCode.OUTPUT_VALIDATION_ERROR.value,
                )
                await self._audit_high_risk(
                    "HIGH_RISK_EXECUTION_FAILED",
                    effective_context,
                    skill_name,
                    approval_id,
                    "output_validation_failed",
                )
                return self._error(
                    OUTPUT_VALIDATION_ERROR,
                    f"Skill 输出数据校验失败：{type(exc).__name__}",
                    skill_name,
                    started,
                    effective_context,
                    spec=spec,
                )

        if not raw_result.success and not raw_result.error_code:
            raw_result.error_code = SKILL_FAILED

        contract_metadata: dict[str, Any] = {}
        if spec.deprecated:
            contract_metadata = {
                "deprecated": True,
                "replacement": spec.replacement,
            }
        raw_result.metadata = {
            **raw_result.metadata,
            **contract_metadata,
            **self._metadata(skill_name, started, effective_context),
        }
        self._log_result(raw_result)
        if idempotency_token and idempotency_scope is not None:
            if raw_result.success:
                await self.idempotency_store.complete(
                    idempotency_token,
                    scope=idempotency_scope,
                    result=raw_result.model_dump(mode="json"),
                )
            else:
                await self._mark_idempotency_failed(
                    idempotency_token,
                    idempotency_scope,
                    str(raw_result.error_code or SKILL_FAILED),
                )
        if spec.approval_required and effective_context and effective_context.identity_trusted:
            await self._audit_high_risk(
                "HIGH_RISK_EXECUTION_SUCCEEDED"
                if raw_result.success
                else "HIGH_RISK_EXECUTION_FAILED",
                effective_context,
                skill_name,
                approval_id,
                "succeeded" if raw_result.success else "failed",
            )
        return raw_result

    async def _mark_idempotency_failed(self, key, scope, error_code: str) -> None:
        if key and scope is not None:
            await self.idempotency_store.fail(key, scope=scope, error_code=error_code)

    @staticmethod
    async def _audit_high_risk(event, context, skill_name, approval_id, outcome) -> None:
        if not context or not context.identity_trusted or not approval_id:
            return
        await record_audit_event(
            event,
            scope=TenantScope(
                tenant_id=context.tenant_id,
                store_id=context.store_id,
                identity_trusted=context.identity_trusted,
            ),
            task_id=context.task_id,
            user_id=context.user_id,
            agent_id=context.agent_id,
            skill_name=skill_name,
            approval_id=approval_id,
            outcome=outcome,
        )

    @staticmethod
    def _validate_input(input_model: type | None, params: dict) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise TypeError("params 必须为 dict")
        if input_model is None:
            return dict(params)
        return input_model.model_validate(params).model_dump()

    @staticmethod
    def _permission_denied_reason(spec, context: SkillExecutionContext | None) -> str:
        protected = SkillExecutor._requires_trusted_identity(spec)
        if not protected:
            if context is None or context.agent_id in {AGENT_QUERY, AGENT_EXEC}:
                return ""
            return f"未授权的 Skill execution context：{context.agent_id}"
        if context is None:
            return f"缺少 SkillExecutionContext，拒绝执行 write Skill：{spec.name}"
        if context.agent_id == AGENT_QUERY and not (spec.read_only and not spec.side_effect):
            return f"data_query 无权执行非只读 Skill：{spec.name}"
        if not context.identity_trusted:
            return f"身份未验证，拒绝执行 write Skill：{spec.name}"
        if not all((context.tenant_id, context.store_id, context.user_id)):
            return f"身份作用域不完整，拒绝执行 write Skill：{spec.name}"
        if context.agent_id in {AGENT_QUERY, AGENT_EXEC}:
            return ""
        return f"未授权的 Skill execution context：{context.agent_id}"

    @staticmethod
    def _requires_trusted_identity(spec) -> bool:
        """Any non-pure-read or policy-protected contract is fail-closed."""
        return bool(
            spec.read_only is not True
            or spec.side_effect is True
            or spec.required_scopes
            or spec.approval_required
        )

    @staticmethod
    def _metadata(
        skill_name: str,
        started: float,
        context: SkillExecutionContext | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "skill_name": skill_name,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if context is not None:
            metadata["agent_id"] = context.agent_id
        return metadata

    def _error(
        self,
        error_code: str,
        error_msg: str,
        skill_name: str,
        started: float,
        context: SkillExecutionContext | None,
        *,
        spec=None,
        data: dict[str, Any] | None = None,
    ) -> SkillResult:
        metadata = self._metadata(skill_name, started, context)
        if spec is not None and spec.deprecated:
            metadata.update({"deprecated": True, "replacement": spec.replacement})
        result = SkillResult(
            success=False,
            error_code=error_code,
            error_msg=error_msg,
            metadata=metadata,
            data=data or {},
        )
        self._log_result(result)
        return result

    @staticmethod
    def _log_result(result: SkillResult) -> None:
        metrics.observe_skill(
            str(result.metadata.get("skill_name") or "unknown"),
            result.success,
            result.error_code,
            float(result.metadata.get("latency_ms") or 0) / 1000,
        )
        logger.info(
            "skill_execution_done",
            extra={
                "event": "skill_execution_done",
                "skill_name": result.metadata.get("skill_name", ""),
                "agent_id": result.metadata.get("agent_id", ""),
                "latency_ms": result.metadata.get("latency_ms", 0),
                "success": result.success,
                "error_code": result.error_code,
            },
        )


skill_executor = SkillExecutor()
