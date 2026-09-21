# Demo capability matrix

| Capability | NL route | Agent | Workflow / service | Data source | Demo data | Expected result |
|---|---|---|---|---|---|---|
| data_analysis | RULE_DATA_ANALYSIS | Query | DataIntelligenceService | PostgreSQL | 720 orders | PASS |
| knowledge_qa | RULE_KNOWLEDGE | RAG | RAGService | pgvector / lexical | 30 documents | PASS |
| goods_search | RULE_GOODS_SEARCH | Query | goods workflow | ecom_goods | 48 products | PASS |
| goods_catalog | RULE_GOODS_CATALOG | Query | goods workflow | ecom_goods | 48 products | PASS |
| stock_analysis | RULE_STOCK | Query | stock workflow | goods + orders | low/OOS products | PASS |
| competitor_watch | RULE_COMPETITOR | Query | competitor workflow | competitor_price | 160 observations | PASS |
| order_query | RULE_ORDER_QUERY | Query | business API workflow | demo provider | 4 named demo orders | PASS |
| ad_query | RULE_AD_QUERY | Query | advertising query workflow | demo provider | 4 campaigns | PASS |
| ad_optimize | RULE_AD_OPTIMIZE | Exec | advertising workflow | demo provider | 4 campaigns | PASS_REQUIRES_APPROVAL |
| data_check | RULE_DATA_CHECK | Query | data-check workflow | PostgreSQL | quality signals | PASS |
| ops_report | RULE_REPORT | Exec | report workflow | PostgreSQL | all structured data | PASS |
| social_marketing | RULE_SOCIAL | Exec | social workflow | product prompt context | BAG-001 | PASS |
| customer_service | RULE_CRM | Exec | CRM + RAGService | knowledge corpus | policy + SOP + products | PASS |
| risk_control | RULE_RISK | Exec | risk workflow | demo provider / protected write | ORD-DEMO-RISK | PASS_REQUIRES_APPROVAL |

Runtime Agents remain exactly `master_planning`, `data_query`, `biz_exec`, and `knowledge_rag`.
