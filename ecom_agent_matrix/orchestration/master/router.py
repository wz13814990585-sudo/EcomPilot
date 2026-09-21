"""Master deterministic router: pure policy with no I/O."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...config.settings import settings
from ...core.llm import is_llm_configured
from .policy import (
    TASK_ROUTE_MAP,
    is_composite_analysis,
    is_composite_customer_reply,
)


class MasterRouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["fast_path", "planner", "clarify"]
    task_type: str | None = None
    target_agents: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason_code: str
    source: str = "rules"


_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "data_analysis",
        "RULE_DATA_ANALYSIS",
        re.compile(
            r"(?:\d{4}年)?\d{1,2}月.*(?:销售额|订单数|退款率)|"
            r"本月.*(?:销售额|订单数)|(?:销售额|订单数).*本月|"
            r"销量最高.*商品|退款率|(?:revenue|refund\s+rate|top\s+\d+\s+products)",
            re.I,
        ),
    ),
    (
        "knowledge_qa",
        "RULE_KNOWLEDGE",
        re.compile(
            r"退款规则|退款政策|退货政策|店铺规则|运营手册|FAQ|知识库|怎么退|"
            r"refund\s+policy|return\s+policy|store\s+policy",
            re.I,
        ),
    ),
    (
        "order_query",
        "RULE_ORDER_QUERY",
        re.compile(
            r"(?:ORD[-_][A-Z0-9_-]+|\d{10,20}).*(?:状态|物流|发货|订单)|"
            r"(?:状态|物流|发货|查询|查一下).*(?:ORD[-_][A-Z0-9_-]+|\d{10,20})|"
            r"查询订单|订单查询|订单状态|订单数据|order\s+status|tracking",
            re.I,
        ),
    ),
    (
        "stock_analysis",
        "RULE_STOCK",
        re.compile(r"库存|备货|补货|缺货|stock|inventory|replenish", re.I),
    ),
    (
        "ad_optimize",
        "RULE_AD_OPTIMIZE",
        re.compile(
            r"优化.*广告|广告.*优化|广告.*预算|调整出价|调出价|投放优化|"
            r"暂停.*(?:广告|活动)|停止.*(?:广告|活动)|optimi[sz]e.*(?:ad|campaign)|pause.*campaign",
            re.I,
        ),
    ),
    (
        "ops_report",
        "RULE_REPORT",
        re.compile(
            r"生成.*(?:运营)?(?:日报|周报|报表|报告)|运营日报|运营周报|店铺经营情况|ops\s+report",
            re.I,
        ),
    ),
    (
        "customer_service",
        "RULE_CRM",
        re.compile(
            r"回复.*(?:客户|顾客|买家)|(?:客户|顾客|买家).*(?:怎么回|怎么回复|应该怎么)|"
            r"(?:客服|售后).*(?:回复|处理)|帮我回复|customer\s+(?:reply|support)",
            re.I,
        ),
    ),
    (
        "risk_control",
        "RULE_RISK",
        re.compile(
            r"触发.*风控|风控扫描|风险拦截|标记.*高风险|标记.*风险订单|risk\s+check|mark.*risk",
            re.I,
        ),
    ),
    (
        "competitor_watch",
        "RULE_COMPETITOR",
        re.compile(
            r"竞品|比价|价格对比|竞价对比|跟价|(?:Temu|Amazon|AliExpress|eBay).*(?:价格|卖多少|便宜)|competitor|price\s+compar",
            re.I,
        ),
    ),
    (
        "data_check",
        "RULE_DATA_CHECK",
        re.compile(
            r"数据校验|数据.*(?:异常|有问题)|检查.*数据|完整性检查|脏数据|孤儿订单|执行\s*sql|跑\s*sql|data\s+check",
            re.I,
        ),
    ),
    (
        "ad_query",
        "RULE_AD_QUERY",
        re.compile(
            r"查询.*广告|广告(?:活动)?.*(?:效果|ROAS|表现)|哪个广告.*(?:最差|最低)|广告数据|投放数据|广告消耗|ad\s+(?:data|spend)",
            re.I,
        ),
    ),
    (
        "social_marketing",
        "RULE_SOCIAL",
        re.compile(
            r"(?:生成|写).*(?:TikTok|Instagram|社媒|营销|发帖|推广).*文案|"
            r"给.*(?:TikTok|Instagram).*文案|社媒文案|social\s+(?:copy|caption)",
            re.I,
        ),
    ),
    (
        "goods_catalog",
        "RULE_GOODS_CATALOG",
        re.compile(
            r"商品总数|商品数量|列出.*商品|全部商品|商品目录|店里.*哪些商品|product\s+catalog|list\s+all\s+products",
            re.I,
        ),
    ),
    (
        "goods_search",
        "RULE_GOODS_SEARCH",
        re.compile(
            r"搜索.*商品|查找.*商品|帮我找.*(?:背包|商品|款式)|找.*(?:商品|款式)|商品搜索|search.*product",
            re.I,
        ),
    ),
)


def _query(task_input: dict) -> str:
    for key in ("query", "user_query", "text", "message", "content"):
        value = task_input.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def route_master_task(task_input: dict) -> MasterRouteDecision:
    """返回单意图 Fast Path、复杂 Planner 或无模型 Clarify 决策。"""
    explicit = str(task_input.get("task_type") or "").strip()
    if explicit in TASK_ROUTE_MAP:
        enabled = settings.MASTER_FAST_PATH_ENABLED
        return MasterRouteDecision(
            mode="fast_path" if enabled else "planner",
            task_type=explicit,
            target_agents=list(TASK_ROUTE_MAP[explicit]) if enabled else [],
            confidence=1.0,
            reason_code="EXPLICIT_TASK_TYPE" if enabled else "FAST_PATH_DISABLED",
            source="explicit" if enabled else "settings",
        )

    query = _query(task_input)
    if is_composite_customer_reply(query):
        return MasterRouteDecision(
            mode="planner",
            confidence=0.98,
            reason_code="COMPOSITE_CUSTOMER_REPLY",
            source="rules_composite",
        )
    if is_composite_analysis(query):
        return MasterRouteDecision(
            mode="planner",
            confidence=0.98,
            reason_code="COMPOSITE_DATA_ANALYSIS",
            source="rules_composite",
        )
    matches = [rule for rule in _RULES if rule[2].search(query)]
    matched_types = {rule[0] for rule in matches}
    # Explicit protected-write verbs take precedence over read-only mentions of the same resource.
    protected_write = {
        "risk_control": bool(re.search(r"标记|拦截|mark", query, re.I)),
        "ad_optimize": bool(re.search(r"暂停|停止|pause", query, re.I)),
    }
    for protected_type in ("risk_control", "ad_optimize"):
        if protected_type in matched_types and protected_write[protected_type]:
            matched = next(rule for rule in matches if rule[0] == protected_type)
            enabled = settings.MASTER_FAST_PATH_ENABLED
            return MasterRouteDecision(
                mode="fast_path" if enabled else "planner",
                task_type=protected_type,
                target_agents=list(TASK_ROUTE_MAP[protected_type]) if enabled else [],
                confidence=0.98,
                reason_code=matched[1] if enabled else "FAST_PATH_DISABLED",
                source="rules" if enabled else "settings",
            )
    if len(matched_types) > 1:
        return MasterRouteDecision(
            mode="planner" if is_llm_configured() else "clarify",
            confidence=0.4,
            reason_code="AMBIGUOUS",
            source="rules",
        )

    if matches:
        task_type, reason_code, _pattern = matches[0]
        enabled = settings.MASTER_FAST_PATH_ENABLED
        return MasterRouteDecision(
            mode="fast_path" if enabled else "planner",
            task_type=task_type,
            target_agents=list(TASK_ROUTE_MAP[task_type]) if enabled else [],
            confidence=0.95,
            reason_code=reason_code if enabled else "FAST_PATH_DISABLED",
            source="rules" if enabled else "settings",
        )

    if is_llm_configured():
        return MasterRouteDecision(
            mode="planner",
            confidence=0.2,
            reason_code="UNKNOWN",
            source="config",
        )
    return MasterRouteDecision(
        mode="clarify",
        confidence=0.2,
        reason_code="UNKNOWN",
        source="rules",
    )


__all__ = ["MasterRouteDecision", "route_master_task"]
