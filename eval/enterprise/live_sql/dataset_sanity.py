"""Independent mathematical checks for the deterministic ecommerce seed."""

from __future__ import annotations

from .database import execute_scoped
from .normalizer import compare_rows, normalize_rows

CHECKS = (
    ("total_order_count", "SELECT COUNT(*) AS value FROM ecom_order", [{"value": 17}]),
    ("total_revenue", "SELECT SUM(total_amount) AS value FROM ecom_order", [{"value": 1420.0}]),
    (
        "monthly_revenue",
        "SELECT DATE_TRUNC('month',create_time) AS month,SUM(total_amount) AS revenue "
        "FROM ecom_order GROUP BY DATE_TRUNC('month',create_time) ORDER BY month",
        [
            {"month": "2026-07-01T00:00:00", "revenue": 430.0},
            {"month": "2026-08-01T00:00:00", "revenue": 730.0},
            {"month": "2026-09-01T00:00:00", "revenue": 260.0},
        ],
    ),
    (
        "monthly_order_count",
        "SELECT DATE_TRUNC('month',create_time) AS month,COUNT(*) AS orders "
        "FROM ecom_order GROUP BY DATE_TRUNC('month',create_time) ORDER BY month",
        [
            {"month": "2026-07-01T00:00:00", "orders": 5},
            {"month": "2026-08-01T00:00:00", "orders": 8},
            {"month": "2026-09-01T00:00:00", "orders": 4},
        ],
    ),
    (
        "monthly_refund_count",
        "SELECT DATE_TRUNC('month',create_time) AS month,"
        "SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END) AS refunds "
        "FROM ecom_order GROUP BY DATE_TRUNC('month',create_time) ORDER BY month",
        [
            {"month": "2026-07-01T00:00:00", "refunds": 2},
            {"month": "2026-08-01T00:00:00", "refunds": 5},
            {"month": "2026-09-01T00:00:00", "refunds": 1},
        ],
    ),
    (
        "monthly_refund_rate",
        "SELECT DATE_TRUNC('month',create_time) AS month,"
        "ROUND(SUM(CASE WHEN refund_flag THEN 1 ELSE 0 END)::numeric/COUNT(*),3) "
        "AS refund_rate FROM ecom_order GROUP BY DATE_TRUNC('month',create_time) ORDER BY month",
        [
            {"month": "2026-07-01T00:00:00", "refund_rate": 0.4},
            {"month": "2026-08-01T00:00:00", "refund_rate": 0.625},
            {"month": "2026-09-01T00:00:00", "refund_rate": 0.25},
        ],
    ),
    (
        "sku_units",
        "SELECT sku,SUM(buy_num) AS units FROM ecom_order GROUP BY sku ORDER BY sku",
        [
            {"sku": "SKU-A", "units": 6},
            {"sku": "SKU-B", "units": 6},
            {"sku": "SKU-C", "units": 5},
            {"sku": "SKU-D", "units": 4},
        ],
    ),
    (
        "sku_revenue",
        "SELECT sku,SUM(total_amount) AS revenue FROM ecom_order GROUP BY sku ORDER BY sku",
        [
            {"sku": "SKU-A", "revenue": 600.0},
            {"sku": "SKU-B", "revenue": 300.0},
            {"sku": "SKU-C", "revenue": 400.0},
            {"sku": "SKU-D", "revenue": 120.0},
        ],
    ),
    (
        "category_revenue",
        "SELECT g.category,SUM(o.total_amount) AS revenue FROM ecom_order o "
        "JOIN ecom_goods g ON g.sku=o.sku GROUP BY g.category ORDER BY g.category",
        [
            {"category": "beauty", "revenue": 120.0},
            {"category": "electronics", "revenue": 900.0},
            {"category": "home", "revenue": 400.0},
        ],
    ),
    (
        "category_refunds",
        "SELECT g.category,SUM(CASE WHEN o.refund_flag THEN 1 ELSE 0 END) AS refunds "
        "FROM ecom_order o JOIN ecom_goods g ON g.sku=o.sku "
        "GROUP BY g.category ORDER BY g.category",
        [
            {"category": "beauty", "refunds": 1},
            {"category": "electronics", "refunds": 4},
            {"category": "home", "refunds": 3},
        ],
    ),
    ("inventory_total", "SELECT SUM(stock_num) AS value FROM ecom_goods", [{"value": 55}]),
    (
        "competitor_price_statistics",
        "SELECT MIN(compete_price) AS minimum,MAX(compete_price) AS maximum,"
        "AVG(compete_price) AS average FROM competitor_price",
        [{"minimum": 25.0, "maximum": 95.0, "average": 60.0}],
    ),
)


def run_dataset_sanity(connection) -> dict:
    cases = []
    for name, sql, expected in CHECKS:
        actual = normalize_rows(execute_scoped(connection, sql))
        normalized_expected = normalize_rows(expected)
        passed = compare_rows(actual, normalized_expected)
        cases.append(
            {
                "id": name,
                "status": "PASS" if passed else "FAIL",
                "actual": actual,
                "expected": normalized_expected,
            }
        )
    failed = sum(case["status"] == "FAIL" for case in cases)
    return {
        "status": "PASS" if not failed else "FAIL",
        "totals": {"cases": len(cases), "pass": len(cases) - failed, "fail": failed},
        "cases": cases,
    }


__all__ = ["CHECKS", "run_dataset_sanity"]
