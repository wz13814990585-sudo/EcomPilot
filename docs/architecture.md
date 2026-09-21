# 系统架构与关键时序

系统只有四个 Runtime Agent。丰富的业务能力由 Workflow 与 Skill 提供，不会削弱四个 Agent 的职责和安全边界。

```text
用户 -> FastAPI -> Master -> Fast Path / Typed Planner -> 已校验 DAG
                              |              |              |
                            Query           RAG            Exec
                              |              |              |
                         SQL / 只读 API    知识库       写 API
                              +--------------+--------------+
                                             |
                                         证据库
                                             |
                                       证据综合服务
                                             |
                                       Grounding 校验
```

SecurityContext、RBAC、PostgreSQL RLS、人工审批、幂等、超时、链路追踪、指标与评估构成横切安全边界。分析和业务 API 以 Service/Skill 形式存在，不会额外创建 Runtime Agent。

## 安全 Text-to-SQL Fast Path

```mermaid
sequenceDiagram
    participant U as 用户
    participant M as Master
    participant Q as Query
    participant C as Schema 目录
    participant V as SQLGlot 安全校验
    participant DB as PostgreSQL 只读角色
    U->>M: 本月销售额和订单数？
    M->>Q: data_analysis Fast Path
    Q->>C: 权限过滤后的 Hybrid / 关键词 Schema Linking
    C-->>Q: 表、字段、外键与原因码
    Q->>Q: 结构化 SQL 生成
    Q->>V: 语法、函数、表、字段、成本与 LIMIT 校验
    V-->>Q: 校验后的 SELECT
    Q->>DB: 只读事务 + 超时 + tenant/store RLS
    DB-->>Q: 有界结果集
    Q-->>M: SQL 证据 + Lineage + 质量提醒
    M-->>U: 可追溯回答
```

生成 SQL 的授权永远不由模型决定。系统在生成前进行权限过滤，并在 AST 校验时再次检查；RLS 是最终数据库边界。安全的技术性数据库错误最多允许修复一次，修复后必须重新经过完整校验链；权限、租户、危险 SQL 和成本超限错误绝不自动修复。

## 结构化数据 + 非结构化知识联合分析

```mermaid
sequenceDiagram
    participant M as Master
    participant Q as Query
    participant R as RAG
    participant S as 证据综合服务
    M->>M: 确定性组合分析路由
    par 定量证据
        M->>Q: data_analysis
        Q->>Q: 有界 AnalyticalQueryPlan
        Q-->>M: 趋势 + 分组 SQL 证据 + Lineage
    and 文档证据
        M->>R: knowledge_qa
        R-->>M: 文档证据 + 引用
    end
    M->>S: 有界证据包
    S-->>M: 事实、共现、相关性、假设与未知项
    M->>M: 确定性 Grounding 校验
    Note over M: 未测量关联时，SQL + 文档只能证明共现
```

每个分析子查询都独立经过权限过滤的 Schema Linking、SQL 生成、Fail-closed 函数白名单、AST 校验、查询守卫、只读执行和 RLS。计划最多四步、并发最多三个，并且只能使用授权 Catalog 中真实存在的维度；如果没有地区字段，系统就不会虚构地区分析。

## 简单任务 Fast Path

```mermaid
sequenceDiagram
    participant C as 客户端
    participant A as FastAPI
    participant M as Master
    participant Q as Query
    participant W as 只读 Workflow
    participant S as SkillExecutor
    participant D as PostgreSQL
    C->>A: 已认证的简单查询
    A->>M: AgentMessage(root task_id)
    M->>M: 确定性高置信路由
    M->>Q: 新 correlation_id
    Q->>W: 类型化请求
    W->>S: 纯只读 Skill
    S->>D: tenant-scoped SELECT
    D-->>S: 事实数据
    S-->>W: SkillResult
    W-->>Q: WorkflowResult
    Q-->>M: 关联响应
    M-->>A: 最终结果，Planner 调用为零
    A-->>C: API 响应
```

## 组合任务 Typed DAG

```mermaid
sequenceDiagram
    participant M as Master
    participant P as Typed Planner
    participant Q as Query
    participant R as RAG
    participant E as Exec/CRM
    M->>P: 组合型客户请求
    P-->>M: 校验后的 DAG
    par 独立上下文
        M->>Q: order_context
        Q-->>M: 订单事实
    and
        M->>R: policy_context
        R-->>M: Grounded 知识 + 引用
    end
    M->>E: customer_reply + upstream context
    E-->>M: 最终客户回复
    Note over M: 依赖感知执行与有界恢复
```

## 高风险操作审批

```mermaid
sequenceDiagram
    participant U as 请求者
    participant E as Exec 工作流
    participant X as SkillExecutor
    participant DB as PostgreSQL
    participant H as 人工审批人
    U->>E: 确定性的风险订单参数
    E->>X: record_order_risk
    X->>DB: 创建绑定精确参数的待审批记录
    X-->>U: awaiting_approval + approval_id
    H->>DB: 调用已认证审批接口
    DB-->>H: 已批准授权
    U->>E: 相同参数 + X-Approval-Id
    E->>X: record_order_risk
    X->>DB: 原子消费审批
    X->>DB: 风险记录只写入一次
    X-->>U: 执行成功
```

LLM 永远不参与审批授权。租户身份、必要 Scope、参数哈希、有效期和一次性消费全部由确定性安全代码控制。
