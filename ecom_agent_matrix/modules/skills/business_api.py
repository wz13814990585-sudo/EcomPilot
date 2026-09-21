"""Business API skills: reads belong to Query; protected writes belong to Exec."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...core.errors import ErrorCode
from ...core.skill.base_skill import BaseSkill, SkillResult
from ...core.skill.skill_registry import current_skill_execution_context, register_skill
from ..business_api import demo_business_api
from ..evidence import APIEvidence


class BusinessAPIReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: Literal[
        "get_order", "get_inventory", "get_refund_status", "get_campaign", "get_product"
    ]
    resource_id: str = Field(min_length=1)


class BusinessAPIReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool
    demo: bool
    provider: str
    operation: str
    resource_id: str
    fields: dict[str, Any]
    evidence: dict[str, Any]


class BusinessAPIWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: Literal["mark_order_risk", "pause_campaign"]
    resource_id: str = Field(min_length=1)
    fields: dict[str, Any] = Field(default_factory=dict)


class BusinessAPIWriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool
    demo: bool
    provider: str
    operation: str
    resource_id: str
    fields: dict[str, Any]


@register_skill
class BusinessAPIReadTool(BaseSkill):
    read_only = True
    side_effect = False
    risk_level = "low"
    timeout_seconds = 10
    idempotent = False
    required_scopes = frozenset({"commerce:read"})
    input_model = BusinessAPIReadInput
    output_model = BusinessAPIReadOutput
    skill_name = "business_api_read"
    skill_desc = "Read a business resource through a typed provider adapter"

    async def run(self, params: dict) -> SkillResult:
        operation = params["operation"]
        response = await getattr(demo_business_api, operation)(params["resource_id"])
        context = current_skill_execution_context()
        if context is None:
            return SkillResult(
                success=False,
                error_code=ErrorCode.AUTHENTICATION_REQUIRED,
                error_msg="Trusted skill context is required",
            )
        evidence = APIEvidence(
            id=f"api:{response.provider}:{response.operation}:{response.resource_id}",
            source_name=response.provider,
            task_id=context.task_id,
            tenant_id=context.tenant_id,
            store_id=context.store_id,
            provider=response.provider,
            operation=response.operation,
            resource_id=response.resource_id,
            response_fields=response.fields,
            retrieved_at=datetime.now(timezone.utc),
            metadata={"demo": response.demo},
        )
        return SkillResult(
            success=True,
            data={**response.model_dump(), "evidence": evidence.model_dump(mode="json")},
        )


@register_skill
class BusinessAPIWriteTool(BaseSkill):
    read_only = False
    side_effect = True
    risk_level = "high"
    timeout_seconds = 10
    idempotent = True
    approval_required = True
    required_scopes = frozenset({"risk:write"})
    input_model = BusinessAPIWriteInput
    output_model = BusinessAPIWriteOutput
    skill_name = "business_api_write"
    skill_desc = "Protected demo business mutation through the Exec Agent"

    async def run(self, params: dict) -> SkillResult:
        response = await getattr(demo_business_api, params["operation"])(
            params["resource_id"], params["fields"]
        )
        return SkillResult(success=True, data=response.model_dump())


__all__ = ["BusinessAPIReadTool", "BusinessAPIWriteTool"]
