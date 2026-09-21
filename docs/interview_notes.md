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

## 16. Why is SQL inside Query rather than a separate SQL Agent?

Text-to-SQL is a read-only structured-data capability, so it belongs to Query's existing security boundary. A separate SQL Agent would add routing and protocol surface without creating a new trust boundary. Query owns permission-filtered schema linking, generation, validation, execution and lineage; Exec remains the only protected-write boundary.

## 17. Why schema linking, and why not send the full schema to the model?

Full-schema prompts increase tokens, ambiguity and accidental exposure of forbidden metadata. The catalog is filtered by authenticated role/scope before linking. Exact aliases and lexical/BM25 signals always work; when the existing embedding provider is locally available, cached semantic vectors add true hybrid retrieval. Adaptive thresholds, column ranking and intent-controlled FK expansion produce a small, inspectable context. The result explicitly says `hybrid` or `lexical_only`.

## 18. Why does permission filtering happen before Schema Linking?

Linking over forbidden metadata could leak table names, column names or business concepts even if final execution were later rejected. Filtering first ensures ranking, semantic embeddings and the LLM generation context only see authorized schema. AST validation and PostgreSQL RLS remain later independent controls.

## 19. How is analytical SQL kept safe?

The chain is defense in depth: trusted SecurityContext, table/column filtering, bounded generation context, SQLGlot AST parsing, allowlists, sensitive-column policy, JOIN/column/row guards, read-only transaction, statement timeout, a separate read role, and PostgreSQL tenant/store RLS. The LLM makes none of these authorization decisions.

`SELECT` alone is not sufficient: PostgreSQL SELECT expressions can invoke executable functions. Generated SQL therefore uses a fail-closed function allowlist for known-safe aggregates, date, numeric and text functions. Unknown and administrative functions are rejected even when the root statement is SELECT. `CAST`, `CASE`, comparisons and arithmetic are recognized as SQL constructs.

## 20. How does bounded SQL repair work?

Only safe technical failures such as an undefined identifier may trigger one repair. The repaired SQL repeats schema permission checks, function policy, SQLGlot validation and cost guards before execution. Permission, RLS, timeout, read-only and cost failures are never repaired because changing SQL cannot legitimately grant authority and retrying may amplify risk.

## 21. What is an AnalyticalQueryPlan?

It is a typed, bounded plan inside `DataIntelligenceService`, not another Agent or planner. Known diagnostic intents use deterministic templates. For “why did refund rate rise?”, the plan includes a metric trend and only schema-supported segmentations such as category and SKU; it does not invent region. At most four independent read queries run with concurrency three, and every subquery traverses the complete safety and lineage path.

A why-question needs more than one SQL because a trend proves that a metric changed but does not localize contribution. Category and SKU breakdowns identify where the change is concentrated. They still do not prove business causation.

## 22. How does SQL evidence become a claim?

Every successful result creates SQL evidence with query ID, normalized rows, generated SQL, referenced tables/columns, tenant/store scope, row count, truncation and latency. Master adds it to an in-request EvidenceStore. Claims reference evidence IDs, and deterministic grounding verifies that referenced evidence exists in the same tenant scope before output.

## 23. Why combine SQL and RAG?

SQL answers what changed and where it is concentrated. RAG supplies policies, incident reports, SOPs and operational context. A composite DAG retrieves both in parallel, then a Master-owned synthesis service combines bounded evidence. This is more useful than asking either a database or document retriever to explain the whole business question alone.

## 24. How are unsupported claims detected?

The grounding layer verifies evidence IDs, citation IDs, tenant ownership and evidence requirements by claim type. Facts require direct evidence. Co-occurrence requires both structured and document sources. Correlation requires computed or explicitly association-supporting evidence. Numeric facts require SQL, API or computed evidence. Fake citations and contradictions produce explicit issue codes.

## 25. What is the difference between FACT, CO_OCCURRENCE, CORRELATION and HYPOTHESIS?

- `FACT` is directly supported by cited evidence.
- `CO_OCCURRENCE` means observations share a relevant time or business context, without a measured association.
- `CORRELATION` requires quantitative or repeated evidence supporting an association.
- `HYPOTHESIS` is an uncertain possible explanation that still needs validation.

SQL plus a contemporaneous RAG document is therefore co-occurrence, not automatically correlation and never automatic causation.

## 26. Why is correlation not causation?

Metric movement and a contemporaneous policy or logistics event establish a useful hypothesis, not proof that one caused the other. The synthesis contract labels facts, correlations and hypotheses separately, states uncertainty, and recommends follow-up segmentation or experiments rather than asserting deterministic causality.

## 27. How is Text-to-SQL evaluated?

The evaluation deliberately separates two different claims. `SQL_EXECUTION_GOLD` runs 32 authored SQL statements through SQLGlot safety, the read role, RLS, PostgreSQL and the result comparator; it proves the validator/database/comparator path, not generation accuracy. `QUESTION_TO_SQL_EXECUTION` gives six deterministic questions—never their `reference_sql`—to the production `DataIntelligenceService`, then measures generation, parse, safety, execution and normalized result accuracy separately.

Execution results are compared instead of SQL strings because semantically equivalent SQL can differ in aliases, predicate order or formulation. Deterministic and integration evaluation are separate because the quality gate should not need a database, external APIs or large model downloads. The Level B job starts PostgreSQL/pgvector and uploads all reports even when a case fails. If a required service or populated RAG index is absent, the status is `NOT_RUN`, never an inferred pass.

## 28. What changes at production scale?

Replace the demo Business API adapter with authenticated provider adapters, load the catalog from governed metadata at startup, add explicit catalog refresh/versioning, and enable safe `EXPLAIN (FORMAT JSON)` cost estimates where supported. Durable transport or process separation should only follow measured throughput, availability or replay requirements; the four Agent boundaries stay stable.

## 29. How is PostgreSQL RLS tested rather than assumed?

The Level B seed creates tenant A and a clearly marked tenant B secret row, enables and forces tenant/store RLS, and creates a non-superuser role without `BYPASSRLS`. Tests set transaction-local tenant/store settings, query without application-added tenant predicates, and verify tenant A cannot see tenant B even with an explicit `tenant_id='tenant-b'` predicate. The same role must see tenant B only after the trusted scope is changed to tenant B.

## 30. Why use both application permissions and database RLS?

Application filtering prevents forbidden schema from reaching ranking, generation and logs; AST validation rejects unsafe query shapes before execution. RLS is the final data boundary if an application bug, unexpected query or future code path bypasses an earlier control. The integration suite also bypasses the AST layer intentionally and proves the read credential cannot `INSERT`, `UPDATE`, `DELETE` or `DROP`.

## 31. Why is semantic retrieval optional in CI?

The deterministic CI injects a fake semantic scorer to prove hybrid ranking, cache versioning and lexical fallback without downloading Torch models. This keeps CI reproducible and inexpensive. Actual embedding-provider quality belongs to optional Level C evaluation and cannot be reported as run when the model is unavailable.

## 32. Why is a SELECT allowlist insufficient without a function policy?

PostgreSQL permits function calls inside a SELECT, including sleep, administrative, file and extension-backed operations. The validator therefore distinguishes AST syntax operators such as `AND` from executable functions and applies a fail-closed allowlist to the latter. The database read role and read-only transaction remain independent defenses.

## 33. What do partial analytical results mean?

Every trend/category/SKU subquery traverses the full schema-link, generation, validation, execution and evidence path under a bounded semaphore. If one fails, the aggregate result is `PARTIAL`, not full success, and synthesis receives evidence only from successful steps. Missing dimensions such as region are skipped explicitly instead of hallucinated.

## 34. How do you prevent Agent benchmarks from lying?

Each layer records independent observables: generated SQL, parse validity, safety acceptance, execution success, result accuracy, lineage, evidence IDs and failure stage. Gold SQL and generated SQL have different report types; unavailable capabilities stay `NOT_RUN`; rates use executed cases; current Git metadata is read at report time; and CI preserves failure artifacts and prints failed case IDs directly.
