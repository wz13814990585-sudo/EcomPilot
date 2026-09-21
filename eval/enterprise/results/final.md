# Final Enterprise Data Agent Evaluation

- Status: **PASS**
- Git SHA: `868bd9123eb89f0acbc7fc17d02fe6b68fac4fb4`
- Timestamp: `2026-09-21T10:09:37.929717+00:00`

## Before → After

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| table_precision | 0.510417 | 0.979167 | 0.46875 |
| table_recall | 1.0 | 1.0 | 0.0 |
| table_f1 | NOT_RUN | 0.989474 | NOT_RUN |
| column_precision | 0.354018 | 0.885417 | 0.531399 |
| column_recall | 1.0 | 1.0 | 0.0 |
| column_f1 | NOT_RUN | 0.939227 | NOT_RUN |
| sql_parse_valid | 1.0 | 1.0 | 0.0 |
| sql_safety_pass | 1.0 | 1.0 | 0.0 |
| execution_success_rate | NOT_RUN | NOT_RUN | NOT_RUN |
| execution_accuracy | NOT_RUN | NOT_RUN | NOT_RUN |
| repair_rate | NOT_RUN | NOT_RUN | NOT_RUN |
| repair_success_rate | NOT_RUN | NOT_RUN | NOT_RUN |
| routing_accuracy | NOT_RUN | 1.0 | NOT_RUN |
| fast_path_rate | NOT_RUN | 0.571429 | NOT_RUN |
| planner_rate | NOT_RUN | 0.428571 | NOT_RUN |
| schema_link_latency_ms | NOT_RUN | 0.22525 | NOT_RUN |
| llm_calls | NOT_RUN | 0 | NOT_RUN |
| token_cost_usd | NOT_RUN | 0.0 | NOT_RUN |

## Deterministic quality

```json
{
  "analytical_plan_validity": 1.0,
  "unsupported_claim_rate": 0.0,
  "grounding_pass_rate": 1.0,
  "unsafe_sql_execution_rate": 0.0,
  "permission_violation_rate": 0.0,
  "tenant_isolation_failure_rate": 0.0
}
```

## Integration status

- Seeded PostgreSQL: **NOT_RUN**
- RAG live: **NOT_RUN**

`NOT_RUN` is preserved and is not counted as `PASS`.
