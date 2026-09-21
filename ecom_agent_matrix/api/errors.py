"""Human-facing API error contracts without exposing internal implementation details."""

from __future__ import annotations

from typing import Any

from ..core.errors import ErrorCode


_GUIDANCE: dict[str, tuple[str, str, str, bool]] = {
    ErrorCode.INVALID_REQUEST.value: (
        "还需要补充信息",
        "当前信息不足，暂时无法完成这个请求。",
        "请根据下方提示补充信息后重新发送。",
        True,
    ),
    ErrorCode.VALIDATION_ERROR.value: (
        "输入内容需要调整",
        "部分输入内容格式不正确。",
        "请检查必填项、数字范围和 JSON 格式后重试。",
        True,
    ),
    ErrorCode.AUTHENTICATION_REQUIRED.value: (
        "需要登录",
        "当前请求没有有效的身份凭证。",
        "请在左侧填写有效凭证，然后重新发送。",
        True,
    ),
    ErrorCode.PERMISSION_DENIED.value: (
        "没有操作权限",
        "当前账号不能执行这项操作。",
        "请联系管理员授予相应角色，或切换到有权限的账号。",
        False,
    ),
    ErrorCode.AGENT_TIMEOUT.value: (
        "处理时间超过预期",
        "任务没有在限定时间内完成，系统已安全停止等待。",
        "请稍后重试；如果仍然失败，可缩小查询范围并向管理员提供任务编号。",
        True,
    ),
    ErrorCode.WORKFLOW_TIMEOUT.value: (
        "处理时间超过预期",
        "任务没有在限定时间内完成，系统已安全停止等待。",
        "请稍后重试；如果仍然失败，可缩小查询范围并向管理员提供任务编号。",
        True,
    ),
    ErrorCode.AGENT_UNAVAILABLE.value: (
        "服务暂时不可用",
        "负责处理该请求的服务当前没有就绪。",
        "请先在“系统状态”检查依赖服务，恢复后再试。",
        True,
    ),
    ErrorCode.RATE_LIMITED.value: (
        "请求过于频繁",
        "短时间内提交的请求较多。",
        "请稍等片刻再试。",
        True,
    ),
    ErrorCode.APPROVAL_REQUIRED.value: (
        "等待管理员审批",
        "这是受保护的写操作，尚未执行。",
        "请由管理员核对目标和参数后批准。",
        True,
    ),
    ErrorCode.UNSUPPORTED_PLATFORM.value: (
        "暂不支持这个平台",
        "当前广告平台不在支持范围内。",
        "请选择 Meta、Google、TikTok 或 Amazon 后重试。",
        True,
    ),
    ErrorCode.MISSING_PRODUCT.value: (
        "没有找到商品",
        "无法确定你想操作的商品。",
        "请补充商品名称或 SKU 后重试。",
        True,
    ),
    ErrorCode.MISSING_SKU.value: (
        "需要商品 SKU",
        "当前请求缺少可识别的商品编号。",
        "请补充类似 BAG-001 的 SKU 后重试。",
        True,
    ),
    ErrorCode.RETRIEVAL_ERROR.value: (
        "知识库暂时不可用",
        "系统暂时无法读取知识库内容。",
        "请在管理员页面检查 RAG 数据和数据库状态后重试。",
        True,
    ),
    ErrorCode.SQL_EXECUTION_ERROR.value: (
        "数据查询没有完成",
        "系统暂时无法完成数据库查询。",
        "请稍后重试；持续失败时请向管理员提供任务编号。",
        True,
    ),
}

_SAFE_DETAIL_CODES = {
    ErrorCode.INVALID_REQUEST.value,
    ErrorCode.VALIDATION_ERROR.value,
    ErrorCode.MISSING_PRODUCT.value,
    ErrorCode.MISSING_SKU.value,
    ErrorCode.MISSING_COMPETITOR.value,
    ErrorCode.UNSUPPORTED_PLATFORM.value,
    ErrorCode.UNSUPPORTED_REPORT_TYPE.value,
    ErrorCode.PRICE_UNAVAILABLE.value,
}


def public_error(
    code: ErrorCode | str | None,
    *,
    message: str = "",
    task_id: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable Chinese error payload and keep raw internals out of the UI."""
    value = str(
        code.value if isinstance(code, ErrorCode) else code or ErrorCode.INTERNAL_ERROR.value
    )
    title, default_message, next_action, retryable = _GUIDANCE.get(
        value,
        (
            "暂时无法完成",
            "系统在处理请求时遇到了问题。",
            "请重试一次；如果问题持续，请向管理员提供任务编号。",
            True,
        ),
    )
    safe_message = str(message or "").strip() if value in _SAFE_DETAIL_CODES else ""
    return {
        "success": False,
        "error_code": value,
        "title": title,
        "message": safe_message or default_message,
        "next_action": next_action,
        "retryable": retryable,
        "task_id": task_id,
        "context": context or {},
    }


def root_failure(data: dict[str, Any] | None, fallback: str = "") -> tuple[str, dict[str, Any]]:
    """Extract the first useful business failure from Master results."""
    payload = data if isinstance(data, dict) else {}
    candidates = payload.get("sub_results") or []
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict) or item.get("success"):
                continue
            details = item.get("data") if isinstance(item.get("data"), dict) else {}
            message = str(item.get("error_msg") or details.get("error_msg") or "").strip()
            context = {
                key: details[key]
                for key in (
                    "missing_profit_fields",
                    "supported_platforms",
                    "sku",
                    "campaign_id",
                    "order_no",
                )
                if details.get(key) not in (None, "", [], {})
            }
            if message:
                return message, context
    return str(fallback or "").strip(), {}


__all__ = ["public_error", "root_failure"]
