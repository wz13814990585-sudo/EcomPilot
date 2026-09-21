# Interview notes

## 1. Why only four Agents?

An Agent represents a stable responsibility and security boundary, not a database table or feature label. Master, Query, Exec, and RAG cover orchestration, reads, commands, and knowledge retrieval without creating a fragile network of tiny personas. New business cases normally add a parser, workflow, or Skill while the four runtime boundaries remain stable.

## 2. What is the difference between an Agent, Workflow, and Skill?

An Agent owns a responsibility and execution policy. A Workflow coordinates a typed business sequence inside that boundary. A Skill is one atomic, contracted capability executed through common permission, timeout, validation, and telemetry controls.

## 3. Why does a simple task not use the Planner LLM?

High-confidence simple intents already have deterministic routing rules, so a model adds latency, cost, and routing variance without adding useful judgment. The Fast Path dispatches once and records zero planner calls. Ambiguous or genuinely composite work can still use the typed planning path.

## 4. Why does Master use a typed DAG?

Free-form model plans are unsafe execution instructions. A typed DAG constrains Agent/task mappings, step counts, dependencies, cycles, and payload shape before execution. It also makes independent steps concurrent and downstream context explicit and testable.

## 5. Why are Exec failures not automatically retried?

A write may have succeeded remotely even when its response was lost, so blind retry can duplicate side effects. Write Skills are fail-closed and not automatically retried, especially for approval consumption and high-risk actions. Future retry is limited to operations with a proven idempotency key and explicit contract.

## 6. Why combine vector and lexical retrieval?

Vector search handles semantic similarity and multilingual phrasing, while lexical search preserves exact identifiers and rare terms. Independent candidate sets fused with RRF reduce dependence on either channel's score scale. Batch reranking then spends semantic compute only on the bounded fused set.

## 7. How is hallucination reduced?

The service separates retrieval from answer generation, filters/reranks sources, assigns stable source IDs, and validates returned citations. It exposes grounding and invalid-citation status rather than hiding uncertainty. When generation fails, a deterministic source-context fallback remains available.

## 8. How is tenant A prevented from seeing tenant B data?

Tenant and store identity are derived from authenticated claims, not request payloads. They propagate in trusted contexts to transaction-local PostgreSQL settings, and RLS policies enforce the same boundary in the database. Cache keys, memory access, approvals, and audit records also include tenant/store scope.

## 9. Why require human approval for high-risk writes?

Authorization answers whether a user may request an operation; approval answers whether this exact risky operation should proceed now. The approval binds tenant, store, Skill, exact parameter hash, expiry, and one-time consumption. The LLM cannot create or approve that grant.

## 10. Why no Kafka or Redis Streams?

The current workload is a portfolio/demo-scale single-process runtime, where distributed messaging would add deployment and failure modes without proving more about orchestration correctness. The asyncio bus keeps the demo reproducible and observable. A MessageBus boundary preserves a future transport substitution if scale or durability requirements justify it.

## 11. How do you find the slowest Agent?

Prometheus histograms record Agent, Workflow, Skill, HTTP, and LLM duration with bounded labels. Root `task_id` and hop `correlation_id` connect structured logs without putting high-cardinality IDs into metrics. Comparing Agent duration with downstream Workflow/Skill/LLM histograms localizes the bottleneck.

## 12. How are LLM tokens and cost measured?

Only real provider invocations increment call and latency metrics. Provider usage populates prompt and completion token counters, while an optional static price table produces explicitly estimated cost. Missing pricing yields no estimate rather than a fabricated value, and rule fallbacks do not count as model calls.

## 13. What happens when the LLM is unavailable?

Transient failures receive bounded retry and then open a component-level circuit breaker after the configured threshold. Fast Path routing, database facts, permission decisions, and approval remain deterministic. RAG and CRM can return safe source/template fallbacks, while readiness reports LLM degradation without necessarily taking the entire API out of service.

## 14. How would this evolve for production scale?

First define measured SLOs, load characteristics, durability needs, and failure budgets. Then move process-local state to appropriate shared services, add an idempotent durable transport only where required, deploy separate read/write identities with managed secrets, and automate migrations and deployment. The four responsibility boundaries and typed contracts should remain even if their transport or process placement changes.

## 15. Why SQLGlot instead of checking whether SQL starts with SELECT?

String prefixes cannot safely understand CTEs, nested writes, multiple statements, row locks, `SELECT INTO`, table aliases, functions or LIMIT semantics. SQLGlot produces an AST that the validator can inspect and rewrite deterministically. The project rejects DDL/DML, unsafe functions, forbidden tables/columns and expensive shapes before the database sees the statement.

## 16. Why schema linking, and why not send the full schema to the model?

Full-schema prompts increase tokens, ambiguity and accidental exposure of forbidden metadata. The catalog is filtered by authenticated role/scope before linking. Lexical/BM25 signals, exact business aliases, optional semantic scores, column metadata and FK expansion produce a small, inspectable schema context with scores and reason codes.

## 17. How is analytical SQL kept safe?

The chain is defense in depth: trusted SecurityContext, table/column filtering, bounded generation context, SQLGlot AST parsing, allowlists, sensitive-column policy, JOIN/column/row guards, read-only transaction, statement timeout, a separate read role, and PostgreSQL tenant/store RLS. The LLM makes none of these authorization decisions.

## 18. How does SQL evidence become a claim?

Every successful result creates SQL evidence with query ID, normalized rows, generated SQL, referenced tables/columns, tenant/store scope, row count, truncation and latency. Master adds it to an in-request EvidenceStore. Claims reference evidence IDs, and deterministic grounding verifies that referenced evidence exists in the same tenant scope before output.

## 19. Why combine SQL and RAG?

SQL answers what changed and where it is concentrated. RAG supplies policies, incident reports, SOPs and operational context. A composite DAG retrieves both in parallel, then a Master-owned synthesis service combines bounded evidence. This is more useful than asking either a database or document retriever to explain the whole business question alone.

## 20. How are unsupported claims detected?

The grounding layer verifies evidence IDs, citation IDs, tenant ownership and evidence requirements by claim type. Facts require evidence; correlations require quantitative or temporal evidence; numeric metric claims require SQL, API or computed evidence; fake citations and contradictory evidence produce explicit issue codes.

## 21. Why is correlation not causation?

Metric movement and a contemporaneous policy or logistics event establish a useful hypothesis, not proof that one caused the other. The synthesis contract labels facts, correlations and hypotheses separately, states uncertainty, and recommends follow-up segmentation or experiments rather than asserting deterministic causality.

## 22. How is Text-to-SQL evaluated?

The repository includes 50 enterprise cases across simple/complex SQL, RAG, SQL+RAG, API, permissions and safety. It reports table/column precision and recall, parse validity, safety pass and unsafe-block rates. Live execution success/accuracy and repair rates remain `NOT_RUN` unless a seeded PostgreSQL environment is actually exercised.

## 23. What changes at production scale?

Replace the demo Business API adapter with authenticated provider adapters, load the catalog from governed metadata at startup, add explicit catalog refresh/versioning, and enable safe `EXPLAIN (FORMAT JSON)` cost estimates where supported. Durable transport or process separation should only follow measured throughput, availability or replay requirements; the four Agent boundaries stay stable.
