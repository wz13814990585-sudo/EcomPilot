# Enterprise Data Agent Benchmark

- Status: **PASS**
- Cases: **50**
- Passed: **50**
- Failed: **0**

## Metrics

```json
{
  "column_precision": 0.885417,
  "column_recall": 1.0,
  "fast_path_rate": 0.571429,
  "planner_rate": 0.428571,
  "routing_accuracy": 1.0,
  "schema_link_latency_ms": 0.309625,
  "sql_parse_valid": 1.0,
  "sql_safety_pass": 1.0,
  "table_precision": 0.979167,
  "table_recall": 1.0,
  "unnecessary_planner_rate": 0.0,
  "unsafe_sql_blocked": 1.0,
  "table_f1": 0.989474,
  "column_f1": 0.939227,
  "task_success_rate": 1.0,
  "execution_success_rate": null,
  "execution_accuracy": null,
  "repair_rate": null,
  "repair_success_rate": null,
  "live_sql_status": "NOT_RUN",
  "rag_generation_status": "NOT_RUN",
  "external_api_status": "NOT_RUN",
  "unsafe_sql_execution_rate": 0.0,
  "llm_calls": 0,
  "token_cost_usd": 0.0
}
```

## Cases

| ID | Category | Status | Detail |
|---|---|---:|---|
| sql_001 | simple_sql | PASS | tables=['ecom_order'], columns=['create_time', 'total_amount'], sql=SELECT COALESCE(SUM(total_amount), 0) AS revenue, COUNT(*) AS order_count FROM ecom_order WHERE DATE_TRUNC('MONTH', create_time) = DATE_TRUNC('MONTH', CURRENT_DATE) |
| sql_002 | simple_sql | PASS | tables=['ecom_order'], columns=[], sql=SELECT COUNT(*) AS order_count FROM ecom_order |
| sql_003 | simple_sql | PASS | tables=['ecom_order'], columns=['refund_flag'], sql=SELECT DATE_TRUNC('MONTH', create_time) AS month, COUNT(*) AS order_count, SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END) AS refund_count, ROUND(CAST(SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END) AS DECIMAL) / NULLIF(COUNT(*), 0), 4) AS refund_rate FROM ecom_order GROUP BY DATE_TRUNC('MONTH', create_time) ORDER BY month DESC LIMIT 12 |
| sql_004 | simple_sql | PASS | tables=['ecom_goods', 'ecom_order'], columns=['buy_num', 'sku'], sql=SELECT o.sku, g.title_zh, SUM(o.buy_num) AS units_sold FROM ecom_order AS o JOIN ecom_goods AS g ON g.sku = o.sku GROUP BY o.sku, g.title_zh ORDER BY units_sold DESC, o.sku LIMIT 5 |
| sql_005 | simple_sql | PASS | tables=['ecom_order'], columns=['create_time', 'total_amount'], sql=SELECT COALESCE(SUM(total_amount), 0) AS revenue, COUNT(*) AS order_count FROM ecom_order WHERE DATE_TRUNC('MONTH', create_time) = DATE_TRUNC('MONTH', CURRENT_DATE) |
| sql_006 | simple_sql | PASS | tables=['ecom_order'], columns=[], sql=SELECT COUNT(*) AS order_count FROM ecom_order |
| sql_007 | simple_sql | PASS | tables=['ecom_order'], columns=['refund_flag'], sql=SELECT DATE_TRUNC('MONTH', create_time) AS month, COUNT(*) AS order_count, SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END) AS refund_count, ROUND(CAST(SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END) AS DECIMAL) / NULLIF(COUNT(*), 0), 4) AS refund_rate FROM ecom_order GROUP BY DATE_TRUNC('MONTH', create_time) ORDER BY month DESC LIMIT 12 |
| sql_008 | simple_sql | PASS | tables=['ecom_goods', 'ecom_order'], columns=['buy_num', 'sku'], sql=SELECT o.sku, g.title_zh, SUM(o.buy_num) AS units_sold FROM ecom_order AS o JOIN ecom_goods AS g ON g.sku = o.sku GROUP BY o.sku, g.title_zh ORDER BY units_sold DESC, o.sku LIMIT 10 |
| complex_001 | complex_sql | PASS | tables=['ecom_goods', 'ecom_order'], columns=['category', 'sku', 'total_amount'] |
| complex_002 | complex_sql | PASS | tables=['ecom_goods'], columns=['category', 'stock_num'] |
| complex_003 | complex_sql | PASS | tables=['ecom_order'], columns=['buy_num', 'sku'] |
| complex_004 | complex_sql | PASS | tables=['competitor_price', 'ecom_goods', 'ecom_order'], columns=['compete_price', 'competitor_name', 'price', 'sku', 'target_sku'] |
| complex_005 | complex_sql | PASS | tables=['ecom_order'], columns=['create_time', 'refund_flag'] |
| complex_006 | complex_sql | PASS | tables=['ecom_goods'], columns=['category', 'price', 'stock_num'] |
| complex_007 | complex_sql | PASS | tables=['competitor_price', 'ecom_goods'], columns=['compete_price', 'crawl_time', 'price', 'sku', 'target_sku'] |
| complex_008 | complex_sql | PASS | tables=['ecom_order'], columns=['buy_num', 'total_amount'] |
| rag_001 | rag | PASS | fast_path:knowledge_qa |
| rag_002 | rag | PASS | fast_path:knowledge_qa |
| rag_003 | rag | PASS | fast_path:knowledge_qa |
| rag_004 | rag | PASS | fast_path:knowledge_qa |
| rag_005 | rag | PASS | fast_path:knowledge_qa |
| rag_006 | rag | PASS | fast_path:knowledge_qa |
| joint_001 | sql_rag | PASS | planner:COMPOSITE_DATA_ANALYSIS |
| joint_002 | sql_rag | PASS | planner:COMPOSITE_DATA_ANALYSIS |
| joint_003 | sql_rag | PASS | planner:COMPOSITE_DATA_ANALYSIS |
| joint_004 | sql_rag | PASS | planner:COMPOSITE_DATA_ANALYSIS |
| joint_005 | sql_rag | PASS | planner:COMPOSITE_DATA_ANALYSIS |
| joint_006 | sql_rag | PASS | planner:COMPOSITE_DATA_ANALYSIS |
| api_001 | api | PASS | provider=demo-business-api, found=True, demo=True |
| api_002 | api | PASS | provider=demo-business-api, found=False, demo=True |
| api_003 | api | PASS | provider=demo-business-api, found=True, demo=True |
| api_004 | api | PASS | provider=demo-business-api, found=False, demo=True |
| api_005 | api | PASS | fast_path:order_query |
| api_006 | api | PASS | fast_path:order_query |
| perm_001 | permission | PASS | tables=['competitor_price', 'ecom_goods', 'ecom_order'] |
| perm_002 | permission | PASS | tables=['competitor_price', 'ecom_goods', 'ecom_order', 'risk_record'] |
| perm_003 | permission | PASS | result=PERMISSION_DENIED, limit=None |
| perm_004 | permission | PASS | result=TABLE_NOT_ALLOWED, limit=None |
| perm_005 | permission | PASS | result=COLUMN_NOT_ALLOWED, limit=None |
| perm_006 | permission | PASS | result=PASS, limit=200 |
| perm_007 | permission | PASS | tables=[] |
| perm_008 | permission | PASS | result=TABLE_NOT_ALLOWED, limit=None |
| safe_001 | safety | PASS | result=UNSAFE_SQL, limit=None |
| safe_002 | safety | PASS | result=UNSAFE_SQL, limit=None |
| safe_003 | safety | PASS | result=UNSAFE_SQL, limit=None |
| safe_004 | safety | PASS | result=UNSAFE_SQL, limit=None |
| safe_005 | safety | PASS | result=UNSAFE_SQL, limit=None |
| safe_006 | safety | PASS | result=UNSAFE_SQL, limit=None |
| safe_007 | safety | PASS | result=PASS, limit=200 |
| safe_008 | safety | PASS | result=PASS, limit=None |
