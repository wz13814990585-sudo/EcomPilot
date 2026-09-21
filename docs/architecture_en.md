# System Architecture and Key Sequences

[简体中文](architecture.md) | [English](architecture_en.md)

The system has four Runtime Agents. Workflows and Skills provide business variety without weakening those responsibility and security boundaries.

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

SecurityContext, RBAC, PostgreSQL RLS, approval, idempotency, timeouts, tracing, metrics, and evaluation are cross-cutting boundaries. Analysis and business APIs are Services/Skills, never additional Runtime Agents.

## Safe Text-to-SQL Fast Path

```mermaid
sequenceDiagram
    participant U as User
    participant M as Master
    participant Q as Query
    participant C as Schema Catalog
    participant V as SQLGlot Guard
    participant DB as PostgreSQL Read Role
    U->>M: What are this month's revenue and order count?
    M->>Q: data_analysis Fast Path
    Q->>C: permission-filtered hybrid / lexical-only Schema Linking
    C-->>Q: selected tables/columns/FKs + reason codes
    Q->>Q: structured SQL generation
    Q->>V: parse + function/table/column/cost/LIMIT validation
    V-->>Q: validated SELECT
    Q->>DB: read-only transaction + timeout + tenant/store RLS
    DB-->>Q: bounded rows
    Q-->>M: SQL evidence + lineage + quality warnings
    M-->>U: traceable answer
```

Generated SQL is never authorized by the model. Permission filtering occurs before generation and again during AST validation; RLS remains the final database boundary. Safe technical database errors may be repaired once, after which the full validation chain runs again. Permission, tenant, unsafe SQL, and cost failures are never repaired.

## Structured and unstructured joint analysis

```mermaid
sequenceDiagram
    participant M as Master
    participant Q as Query
    participant R as RAG
    participant S as Evidence Synthesis
    M->>M: deterministic composite analysis route
    par quantitative evidence
        M->>Q: data_analysis
        Q->>Q: bounded AnalyticalQueryPlan
        Q-->>M: trend + segment SQL evidence + lineage
    and document evidence
        M->>R: knowledge_qa
        R-->>M: document evidence + citations
    end
    M->>S: bounded evidence package
    S-->>M: facts, co-occurrences, correlations, hypotheses, unknowns
    M->>M: deterministic grounding check
    Note over M: SQL + document is co-occurrence unless association is measured
```

Every analytical subquery independently passes permission-filtered linking, SQL generation, the fail-closed function allowlist, AST validation, query guards, read-only execution, and RLS. A plan is capped at four steps with concurrency three. It can only use dimensions present in the allowed Catalog; if a region column does not exist, region analysis cannot be planned.

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
    M-->>A: final result, zero Planner calls
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

## High-risk approval

```mermaid
sequenceDiagram
    participant U as Requester
    participant E as Exec Workflow
    participant X as SkillExecutor
    participant DB as PostgreSQL
    participant H as Human Approver
    U->>E: deterministic risky-order payload
    E->>X: record_order_risk
    X->>DB: create exact-parameter pending approval
    X-->>U: awaiting_approval + approval_id
    H->>DB: authenticated approval endpoint
    DB-->>H: approved grant
    U->>E: same payload + X-Approval-Id
    E->>X: record_order_risk
    X->>DB: atomically consume approval
    X->>DB: write risk record once
    X-->>U: success
```

The LLM never participates in approval authorization. Tenant identity, required scopes, parameter hashes, expiry, and one-time consumption are deterministic security controls.

