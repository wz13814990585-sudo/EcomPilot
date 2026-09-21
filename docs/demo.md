# 跨境电商多智能体平台演示指南

[简体中文](demo.md) | [English](demo_en.md)

下面五条演示路径会调用真实的四 Agent Runtime，而不是静态页面或伪响应。开始前请先完成 README 中的本地或 Docker 启动步骤，并在 API Key 开发模式下使用你自己的本地凭证。

```bash
export BASE_URL=http://127.0.0.1:8002
export DEMO_API_KEY=your-local-demo-key
```

## 演示一：安全 Text-to-SQL

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "本月销售额和订单数是多少？",
    "task_type": "data_analysis"
  }'
```

可以在 Query 子结果中检查 `schema_link` 的表、字段和原因码，以及 `generated_sql`、`validated_sql`、受限查询结果、SQL `evidence` 与 `lineage`。数据库访问使用只读角色、只读事务、语句超时和租户/店铺 RLS。

## 演示二：SQL + RAG 联合分析

先执行知识文档索引，再提问：

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query": "为什么 8 月退款率上涨？"}'
```

确定性组合策略会并行执行两步：Query 生成 SQL 证据，RAG 生成带引用的文档证据，随后由 Master 进行证据综合。可以检查 `data.evidence`、`data.analysis.claims`、`citations`、`uncertainties` 和 `grounding`。回答会明确区分同期相关证据与因果结论，避免把共现直接说成因果。

## 演示三：业务 API 只读查询

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query": "查看订单 ORD-20260301-001 当前物流状态"}'
```

该请求通过 Fast Path 路由到 Query 和 `business_api_read` Skill。响应包含结构化 API 证据，例如 provider、operation、resource ID、允许返回的字段和检索时间。仓库中的适配器明确标记为 `demo-business-api`，不冒充真实生产电商平台连接。

## 演示四：危险 SQL 在执行前被拒绝

通过分析任务协议提交危险 SQL：

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "删除所有退款记录",
    "task_type": "data_analysis",
    "payload": {"sql": "DELETE FROM ecom_order"}
  }'
```

预期结果是 `UNSAFE_SQL`：不会访问数据库，也不会尝试自动修复。相同安全链路还会拒绝不可信租户范围、禁用表/字段、行锁、危险函数、多语句和超限查询结构。

## 演示五：人工审批与幂等保护

金额 `501` 会确定性超过风险阈值并触发审批：

```bash
RISK_RESPONSE=$(curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "检查高风险订单 ORD-DEMO-RISK",
    "task_type": "risk_control",
    "payload": {"order_no": "ORD-DEMO-RISK", "total_amount": 501, "buy_count": 1}
  }')
APPROVAL_ID=$(printf '%s' "$RISK_RESPONSE" | jq -r '.data.sub_results[0].data.approval_id')
```

第一次响应为 `success=false`、`status=awaiting_approval`、`error_code=APPROVAL_REQUIRED`。请使用拥有 `risk:approve` 权限的身份批准：

```bash
curl -sS -X POST "$BASE_URL/api/v1/approvals/$APPROVAL_ID/approve" \
  -H "X-API-Key: $DEMO_API_KEY"
```

携带 `X-Approval-Id` 并使用完全相同的参数重试：

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -H "X-Approval-Id: $APPROVAL_ID" \
  -d '{
    "query": "检查高风险订单 ORD-DEMO-RISK",
    "task_type": "risk_control",
    "payload": {"order_no": "ORD-DEMO-RISK", "total_amount": 501, "buy_count": 1}
  }'
```

修改任何已审批参数都会使授权失效。审批只能消费一次，幂等键会阻止重复副作用，Exec 写操作也不会被盲目重试。重复点击已经执行的审批时，接口会返回人性化的“无需重复审批”提示。

## 确定性评估

```bash
python -m eval.enterprise.runner --suite all --fail-on-regression
```

该命令执行 50 个本地用例。只有在真实依赖可用时才会运行 PostgreSQL 实执行准确率、完整 RAG 生成和外部 provider 测试；否则相应指标会明确标记为 `NOT_RUN`。
