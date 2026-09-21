# Architecture sequences

The system has four runtime Agents. Workflows and Skills provide business variety without weakening those responsibility boundaries.

```text
User -> FastAPI -> Master -> Fast Path / Typed Planner -> Validated DAG
                              |              |              |
                            Query           RAG            Exec
                              |              |              |
                         SQL / Read API  Knowledge Base  Write API
                              +--------------+--------------+
                                             |
                                      Evidence Store
                                             |
                                  Evidence Synthesis Service
                                             |
                                      Grounding Check
```

SecurityContext, RBAC, PostgreSQL RLS, approval, idempotency, timeouts, tracing, metrics and evaluation are cross-cutting boundaries. Analysis and business APIs are services/Skills, never additional runtime Agents.

## Safe Text-to-SQL Fast Path

```mermaid
sequenceDiagram
    participant U as User
    participant M as Master
    participant Q as Query
    participant C as Schema Catalog
    participant V as SQLGlot Guard
    participant DB as PostgreSQL Read Role
    U->>M: 本月销售额和订单数？
    M->>Q: data_analysis Fast Path
    Q->>C: permission-filtered hybrid schema link
    C-->>Q: selected tables/columns/FKs + reason codes
    Q->>Q: structured SQL generation
    Q->>V: parse + AST/table/column/cost/LIMIT validation
    V-->>Q: validated SELECT
    Q->>DB: read-only transaction + statement timeout + tenant/store RLS
    DB-->>Q: bounded rows
    Q-->>M: SQL evidence + lineage + quality warnings
    M-->>U: traceable answer
```

Generated SQL is never authorized by the model. Permission filtering occurs before generation and again at AST validation; RLS remains the final database boundary. Safe technical database errors may be repaired once, then the complete validation chain runs again. Permission, tenant, unsafe SQL and cost failures are never repaired.

## Structured + unstructured analysis

```mermaid
sequenceDiagram
    participant M as Master
    participant Q as Query
    participant R as RAG
    participant S as Evidence Synthesis
    M->>M: deterministic composite analysis route
    par quantitative evidence
        M->>Q: data_analysis
        Q-->>M: SQL evidence + lineage
    and document evidence
        M->>R: knowledge_qa
        R-->>M: document evidence + citations
    end
    M->>S: bounded evidence package
    S-->>M: facts, correlations, hypotheses, uncertainties
    M->>M: deterministic grounding check
    Note over M: correlation is never promoted to causation
```

## Simple Fast Path

```mermaid
sequenceDiagram
    participant C as Client
    participant A as FastAPI
    participant M as Master
    participant Q as Query
    participant W as Read Workflow
    participant S as SkillExecutor
    participant D as PostgreSQL
    C->>A: authenticated simple query
    A->>M: AgentMessage(root task_id)
    M->>M: deterministic high-confidence route
    M->>Q: new correlation_id
    Q->>W: typed request
    W->>S: pure read Skill
    S->>D: tenant-scoped SELECT
    D-->>S: facts
    S-->>W: SkillResult
    W-->>Q: WorkflowResult
    Q-->>M: correlated reply
    M-->>A: final result, zero planner calls
    A-->>C: API response
```

## Composite Typed DAG

```mermaid
sequenceDiagram
    participant M as Master
    participant P as Typed Planner
    participant Q as Query
    participant R as RAG
    participant E as Exec/CRM
    M->>P: composite customer request
    P-->>M: validated DAG
    par independent context
        M->>Q: order_context
        Q-->>M: order facts
    and
        M->>R: policy_context
        R-->>M: grounded knowledge + citations
    end
    M->>E: customer_reply + upstream context
    E-->>M: final customer response
    Note over M: dependency-aware execution and bounded recovery
```

## Risk approval

```mermaid
sequenceDiagram
    participant U as Requester
    participant E as Exec Workflow
    participant X as SkillExecutor
    participant DB as PostgreSQL
    participant H as Human Approver
    U->>E: deterministic risky order payload
    E->>X: record_order_risk
    X->>DB: create exact-parameter pending approval
    X-->>U: failed / awaiting_approval + approval_id
    H->>DB: authenticated approve endpoint
    DB-->>H: approved grant
    U->>E: same payload + X-Approval-Id
    E->>X: record_order_risk
    X->>DB: atomically consume approval
    X->>DB: write risk record once
    X-->>U: success
```

The LLM never participates in approval. Tenant identity, required scopes, parameter hashes, expiry, and one-time consumption are deterministic security controls.
