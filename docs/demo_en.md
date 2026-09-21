# EcomPilot Demo Guide

[简体中文](demo.md) | [English](demo_en.md)

These five demos exercise the real four-Agent Runtime rather than static pages or mocked responses. Complete the local or Docker quick start first and use your own local credential in API-key development mode.

```bash
export BASE_URL=http://127.0.0.1:8002
export DEMO_API_KEY=your-local-demo-key
```

## Demo 1: Safe Text-to-SQL

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "What are this month’s revenue and order count?",
    "task_type": "data_analysis"
  }'
```

Inspect the Query sub-result for `schema_link` tables, columns, and reason codes; `generated_sql`; `validated_sql`; bounded `result`; SQL `evidence`; and `lineage`. The database call uses a read role, read-only transaction, statement timeout, and tenant/store RLS.

## Demo 2: SQL + RAG analysis

Index the knowledge documents first, then ask:

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query": "Why did the refund rate increase in August?"}'
```

The deterministic composite policy builds two parallel steps: Query produces SQL evidence while RAG produces cited document evidence. Master then runs its bounded evidence-synthesis service. Inspect `data.evidence`, `data.analysis.claims`, `citations`, `uncertainties`, and `grounding`. The answer must distinguish contemporaneous evidence from proven causality.

## Demo 3: Business API read

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{"query": "Show the current shipping status of ORD-20260301-001"}'
```

This Fast Path routes to Query and the `business_api_read` Skill. The response includes typed API evidence with provider, operation, resource ID, approved fields, and retrieval time. The repository adapter is explicitly labeled `demo-business-api`; it does not claim a production platform connection.

## Demo 4: Security rejection before execution

Submit dangerous SQL through the analytical task contract:

```bash
curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "Delete all refund records",
    "task_type": "data_analysis",
    "payload": {"sql": "DELETE FROM ecom_order"}
  }'
```

Expected result: `UNSAFE_SQL`, no database execution, and no repair attempt. The same chain rejects untrusted tenant scope, forbidden tables or columns, row locks, dangerous functions, multiple statements, and excessive query shapes.

## Demo 5: Human approval and idempotency

The amount `501` deterministically exceeds the risk threshold and requests approval:

```bash
RISK_RESPONSE=$(curl -sS "$BASE_URL/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $DEMO_API_KEY" \
  -d '{
    "query": "Check high-risk order ORD-DEMO-RISK",
    "task_type": "risk_control",
    "payload": {"order_no": "ORD-DEMO-RISK", "total_amount": 501, "buy_count": 1}
  }')
APPROVAL_ID=$(printf '%s' "$RISK_RESPONSE" | jq -r '.data.sub_results[0].data.approval_id')
```

The first response is `success=false`, `status=awaiting_approval`, and `error_code=APPROVAL_REQUIRED`. Approve it with an identity carrying `risk:approve`:

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
    "query": "Check high-risk order ORD-DEMO-RISK",
    "task_type": "risk_control",
    "payload": {"order_no": "ORD-DEMO-RISK", "total_amount": 501, "buy_count": 1}
  }'
```

Changing any approved parameter invalidates the grant. Approval is consumed once, the idempotency key prevents duplicate side effects, and Exec writes are never blindly retried. Repeating an already executed approval returns a human-readable “no need to approve again” response.

## Deterministic benchmark

```bash
python -m eval.enterprise.runner --suite all --fail-on-regression
```

This runs 50 local cases. Live PostgreSQL execution accuracy, full RAG generation, and external-provider tests remain `NOT_RUN` unless their dependencies are actually available.

