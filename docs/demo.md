# Enterprise Data Agent demo guide

These five demos exercise the real four-Agent runtime. They assume the local/Docker quick start is complete and API-key development mode uses your own local value.

```bash
export BASE_URL=http://127.0.0.1:8002
export DEMO_API_KEY=your-local-demo-key
```

## Demo 1 — Safe Text-to-SQL

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "本月销售额和订单数是多少？",
    "task_type": "data_analysis"
  }'
```

Inspect the Query sub-result for `schema_link` tables/columns/reason codes, `generated_sql`, `validated_sql`, bounded `result`, SQL `evidence`, and `lineage`. The database call uses the read role, a read-only transaction, statement timeout and tenant/store RLS.

## Demo 2 — SQL + RAG analysis

Run the document indexing step first, then ask:

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query": "为什么 8 月退款率上涨？"}'
```

The deterministic composite policy builds two parallel steps: Query produces SQL evidence and RAG produces document evidence with citations. Master then runs its internal evidence-synthesis service. Inspect `data.evidence`, `data.analysis.claims`, `citations`, `uncertainties`, and `grounding`. The answer must say that contemporaneous evidence is correlated but does not alone prove causation.

## Demo 3 — Business API read

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query": "查看订单 ORD-20260301-001 当前物流状态"}'
```

This Fast Path routes to Query and the `business_api_read` Skill. The response includes typed API evidence with provider, operation, resource ID, approved fields and retrieval time. The repository adapter is explicitly `demo-business-api`; it does not claim a production platform connection.

## Demo 4 — Security rejection before execution

Submit generated SQL through the analytical task contract:

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

Expected result: `UNSAFE_SQL`, no database execution, and no repair attempt. Similar checks reject untrusted tenant scope, forbidden tables/columns, row locks, dangerous functions, multi-statements and excessive query shapes.

## Demo 5 — Human approval and idempotency

The amount `501` deterministically exceeds the risk threshold. Request approval:

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

The first response is `success=false`, `status=awaiting_approval`, `error_code=APPROVAL_REQUIRED`. Approve with an identity carrying `risk:approve`:

```bash
curl -sS -X POST "$BASE_URL/api/v1/approvals/$APPROVAL_ID/approve" \
  -H "X-API-Key: $DEMO_API_KEY"
```

Resubmit the exact parameters with `X-Approval-Id`:

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

Changing any approved parameter invalidates the grant. Approval is consumed once, the idempotency key prevents duplicate side effects, and Exec writes are never blindly retried.

## Deterministic benchmark

```bash
python -m eval.enterprise.runner --suite all --fail-on-regression
```

This runs 50 local cases. Live PostgreSQL execution accuracy, full RAG generation and external provider tests remain `NOT_RUN` unless their dependencies are actually available.
