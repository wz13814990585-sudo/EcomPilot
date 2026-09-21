# 演示能力矩阵

| 能力 | 自然语言路由 | Agent | 工作流 / 服务 | 数据来源 | Demo 数据 | 预期结果 |
|---|---|---|---|---|---|---|
| data_analysis | RULE_DATA_ANALYSIS | Query | DataIntelligenceService | PostgreSQL | 720 条订单 | 通过 |
| knowledge_qa | RULE_KNOWLEDGE | RAG | RAGService | pgvector / 关键词 | 30 份文档 | 通过 |
| goods_search | RULE_GOODS_SEARCH | Query | 商品工作流 | ecom_goods | 52 个商品 | 通过 |
| goods_catalog | RULE_GOODS_CATALOG | Query | 商品工作流 | ecom_goods | 52 个商品 | 通过 |
| stock_analysis | RULE_STOCK | Query | 库存工作流 | 商品 + 订单 | 低库存/缺货商品 | 通过 |
| competitor_watch | RULE_COMPETITOR | Query | 竞品工作流 | competitor_price | 160 条价格观测 | 通过 |
| order_query | RULE_ORDER_QUERY | Query | 业务 API 工作流 | Demo provider | 4 个命名订单 | 通过 |
| ad_query | RULE_AD_QUERY | Query | 广告查询工作流 | Demo provider | 4 个广告活动 | 通过 |
| ad_optimize | RULE_AD_OPTIMIZE | Exec | 广告执行工作流 | Demo provider | 4 个广告活动 | 通过（需要审批） |
| data_check | RULE_DATA_CHECK | Query | 数据质量工作流 | PostgreSQL | 质量信号 | 通过 |
| ops_report | RULE_REPORT | Exec | 运营报告工作流 | PostgreSQL | 全部结构化数据 | 通过 |
| social_marketing | RULE_SOCIAL | Exec | 社媒工作流 | 商品提示词上下文 | BAG-001 | 通过 |
| customer_service | RULE_CRM | Exec | CRM + RAGService | 知识语料 | 政策 + SOP + 商品 | 通过 |
| risk_control | RULE_RISK | Exec | 风控工作流 | Demo provider / 受保护写入 | ORD-DEMO-RISK | 通过（需要审批） |

Runtime 始终只保留 `master_planning`、`data_query`、`biz_exec` 和 `knowledge_rag` 四个 Agent；业务能力通过受类型约束的 Workflow 与 Skill 扩展。
