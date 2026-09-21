# Agent Evaluation Report

- Timestamp: `2026-09-21T13:21:54.179099+00:00`
- Git SHA: `94f76f2`
- Environment: `development`
- Deterministic gate: **PASS**

| Suite | Status | Passed | Failed | Not run | Degraded |
|---|---:|---:|---:|---:|---:|
| routing | PASS | 13 | 0 | 0 | 0 |
| planning | PASS | 6 | 0 | 0 | 0 |
| execution | NOT_RUN | 0 | 0 | 0 | 0 |
| safety | PASS | 16 | 0 | 0 | 0 |
| recovery | DEGRADED | 3 | 0 | 8 | 0 |
| rag | NOT_RUN | 0 | 0 | 0 | 0 |

## Metrics

### Routing

```json
{
  "routing_accuracy": 1.0,
  "fast_path_precision": 1.0,
  "fast_path_recall": 1.0,
  "unnecessary_planner_rate": 0.0,
  "clarification_rate": 0.153846,
  "invalid_route_rate": 0.0
}
```

### Planning

```json
{
  "plan_parse_success_rate": 1.0,
  "plan_policy_validity_rate": 1.0,
  "cycle_violation_rate": 0.166667,
  "invalid_agent_task_mapping_rate": 0.166667,
  "dependency_violation_rate": 0.166667,
  "step_count_limit_compliance": 1.0,
  "required_dependency_correctness": 1.0
}
```

### Execution

```json
{}
```

### Safety

```json
{
  "unsafe_execution_rate": 0.0,
  "approval_compliance_rate": 1.0,
  "duplicate_side_effect_rate": 0.0,
  "tenant_isolation_failure_rate": 0.0
}
```

### Recovery

```json
{
  "recovery_attempt_rate": null,
  "recovery_success_rate": 1.0,
  "degraded_success_rate": null,
  "unsafe_retry_rate": 0.0,
  "recovery_llm_calls": 0
}
```

### Rag

```json
{}
```

### Cost

```json
{
  "llm_calls": null,
  "prompt_tokens": null,
  "completion_tokens": null,
  "estimated_cost": null
}
```

