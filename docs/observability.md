# 可观测性与韧性

[简体中文](observability.md) | [English](observability_en.md)

当前 Runtime 有意采用单进程异步 Agent 架构，使面试与 Demo 部署保持清晰，并避免不必要的分布式协调成本。`MessageBus` 保留了未来接入 Redis Streams 或 RabbitMQ 的抽象边界，但当前版本没有宣称实现分布式消息系统。

`GET /metrics` 暴露标签受限的 Prometheus 指标。生产部署应设置 `METRICS_AUTH_REQUIRED=true`，调用方需要具备 `system:read` 权限。

结构化日志通过 `TraceContext` 继承 `task_id` 和逐跳 `correlation_id`。租户与用户标识会做 SHA-256 哈希；请求体、查询、提示词、凭证和 Token 会被排除或脱敏。

业务 POST 路由使用进程内的租户/用户限流器，只适用于当前单进程 Demo Runtime。LLM 与淘宝集成使用有界的组件级熔断器；LLM 自身的重试是唯一重试层，并且只处理瞬时故障。

Readiness 会检查 PostgreSQL、Redis 和 Agent Runtime。LLM 未配置或不可用时会报告为 degraded；只有设置 `LLM_REQUIRED_FOR_READINESS=true` 才会让 readiness 失败。

数据智能遥测会记录标签受限的指标，包括 Schema Linking 延迟与候选数量、SQL 校验结果、安全拒绝原因、执行延迟、行数、截断和修复结果。原始 SQL、问题、任务 ID、用户 ID 和租户 ID 永远不会成为 Prometheus 标签。Trace 只记录选中来源、校验结果、证据 ID 和安全错误分类，不持久化模型隐藏推理。
