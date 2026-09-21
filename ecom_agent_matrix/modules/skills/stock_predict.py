"""拓展：库存预测工具。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...core.skill.base_skill import BaseSkill, SkillResult
from ...core.skill.skill_registry import register_skill
from ...core.security import tenant_scope_from_skill_context
from ...db.base import AsyncPGClient


class StockPredictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=1)
    predict_days: int = Field(default=7, ge=1, le=90)
    history_records: list[dict[str, Any]] = Field(default_factory=list)


class StockPredictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    daily_avg_sales: float = Field(ge=0)
    predict_cycle: int = Field(ge=1)
    suggest_stock_amount: int = Field(ge=0)
    base_suggest_stock_amount: int = Field(ge=0)
    history_used: int = Field(ge=0)
    history_adjusted: bool


class InventoryRiskListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: int = Field(default=25, ge=0, le=10000)
    limit: int = Field(default=20, ge=1, le=100)


class InventoryRiskListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    count: int = Field(ge=0)


@register_skill
class InventoryRiskListTool(BaseSkill):
    read_only = True
    side_effect = False
    risk_level = "low"
    timeout_seconds = 15.0
    idempotent = True
    input_model = InventoryRiskListInput
    output_model = InventoryRiskListOutput
    skill_name = "inventory_risk_list"
    skill_desc = "List low-stock products with observed recent demand and replenishment gap"

    async def run(self, params: dict) -> SkillResult:
        scope = tenant_scope_from_skill_context()
        query_params: list[Any] = [
            int(params.get("threshold", 25)),
        ]
        scope_sql = ""
        if scope.usable:
            scope_sql = " AND g.tenant_id = %s AND g.store_id = %s"
            query_params.extend([scope.tenant_id, scope.store_id])
        query_params.append(int(params.get("limit", 20)))
        rows = await AsyncPGClient.execute_read(
            f"""
            SELECT g.sku, g.title_zh, g.category, g.stock_num,
                   COALESCE(SUM(o.buy_num) FILTER (
                     WHERE o.create_time >= CURRENT_DATE - INTERVAL '30 days'
                       AND o.create_time <= NOW()
                       AND o.refund_flag=false), 0) AS demand_30d
            FROM ecom_goods g
            LEFT JOIN ecom_order o ON o.sku=g.sku
              AND o.tenant_id=g.tenant_id AND o.store_id=g.store_id
            WHERE g.stock_num <= %s
              {scope_sql}
            GROUP BY g.sku, g.title_zh, g.category, g.stock_num
            ORDER BY g.stock_num ASC, demand_30d DESC
            LIMIT %s
            """,
            query_params,
            scope=scope,
        )
        items = []
        for sku, title, category, stock, demand in rows:
            recommended = max(0, int(demand or 0) - int(stock or 0))
            items.append(
                {
                    "sku": sku,
                    "title": title,
                    "category": category,
                    "current_stock": int(stock or 0),
                    "demand_30d": int(demand or 0),
                    "recommended_replenishment": recommended,
                    "risk_level": "high" if int(stock or 0) < 10 else "medium",
                }
            )
        return SkillResult(success=True, data={"items": items, "count": len(items)})


@register_skill
class StockPredictTool(BaseSkill):
    read_only = True
    side_effect = False
    risk_level = "low"
    timeout_seconds = 15.0
    idempotent = True
    input_model = StockPredictInput
    output_model = StockPredictOutput
    skill_name = "stock_predict"
    skill_desc = (
        "商品库存备货预测，参数 sku、predict_days（默认7）、"
        "history_records（已废弃，仅保留调用兼容，不参与预测）"
    )

    async def run(self, params: dict) -> SkillResult:
        try:
            sku = params["sku"]
            predict_days = int(params.get("predict_days", 7))
            scope = tenant_scope_from_skill_context()
            query_params: list[Any] = [sku]
            scope_sql = ""
            if scope.usable:
                scope_sql = " AND tenant_id = %s AND store_id = %s"
                query_params.extend([scope.tenant_id, scope.store_id])
            # history_records 可继续传入，但历史模型预测不是 observed truth，故完全忽略。

            # 统计近30天有效销量（剔除退款订单）
            stat_sql = f"""
            SELECT COALESCE(SUM(buy_num), 0)
            FROM ecom_order
            WHERE sku = %s
              AND create_time >= NOW() - INTERVAL '30 days'
              AND create_time <= NOW()
              AND refund_flag = false
              {scope_sql};
            """
            stat_res = await AsyncPGClient.execute_read(stat_sql, query_params, scope=scope)
            total_30d_sales = float(stat_res[0][0] or 0)
            daily_avg = total_30d_sales / 30
            safety_stock_rate = 1.2
            base_suggest = round(daily_avg * predict_days * safety_stock_rate)

            suggest_stock = base_suggest

            return SkillResult(
                success=True,
                data={
                    "daily_avg_sales": round(daily_avg, 2),
                    "predict_cycle": predict_days,
                    "suggest_stock_amount": suggest_stock,
                    "base_suggest_stock_amount": base_suggest,
                    "history_used": 0,
                    "history_adjusted": False,
                },
            )
        except KeyError as err:
            return SkillResult(success=False, error_msg=f"缺失参数：{err}")
        except ValueError:
            return SkillResult(success=False, error_msg="预测天数必须为整数")
