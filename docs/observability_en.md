# Observability and Resilience

[简体中文](observability.md) | [English](observability_en.md)

The current Runtime is intentionally a single-process asynchronous Agent system. This keeps interview and demo deployments understandable and avoids unnecessary distributed-coordination costs. `MessageBus` preserves an abstraction that could later use Redis Streams or RabbitMQ, but the current version does not claim to implement distributed messaging.

`GET /metrics` exposes Prometheus metrics with bounded labels. Production deployments should set `METRICS_AUTH_REQUIRED=true`; callers then need the `system:read` permission.

Structured logs inherit `task_id` and hop-level `correlation_id` through `TraceContext`. Tenant and user identifiers are SHA-256 hashes; request bodies, queries, prompts, credentials, and tokens are excluded or redacted.

Business POST routes use a process-local tenant/user rate limiter, suitable only for the single-process demo Runtime. LLM and Taobao integrations use bounded component-level circuit breakers. Existing LLM retry remains the sole retry layer and handles only transient failures.

Readiness checks PostgreSQL, Redis, and the Agent Runtime. An unavailable or unconfigured LLM is reported as degraded and does not fail readiness unless `LLM_REQUIRED_FOR_READINESS=true`.

Data-intelligence telemetry adds bounded-label metrics for Schema Linking latency and candidate counts, SQL validation outcomes, safety-rejection reason codes, execution latency, row counts, truncation, and repair outcomes. Raw SQL, questions, task IDs, user IDs, and tenant IDs are never Prometheus labels. Traces record selected sources, validation results, evidence IDs, and safe error categories without persisting hidden model reasoning.
