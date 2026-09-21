"""Agent Console frontend contract tests."""

from pathlib import Path

from ecom_agent_matrix.api.main import app


def test_agent_console_routes_are_registered():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/" in paths
    assert "/app" in paths
    assert "/app/static" in paths


def test_agent_console_exposes_supported_agent_capabilities():
    frontend = Path(__file__).parents[1] / "ecom_agent_matrix" / "api" / "frontend"
    html = (frontend / "index.html").read_text()
    script = (frontend / "app.js").read_text()

    assert "Ecom Agent Console" in html
    for endpoint in (
        "/api/v1/tasks",
        "/api/v1/customer/chat",
        "/api/v1/warn/competitor",
        "/api/v1/approvals/",
        "/api/v1/agents",
        "/health/ready",
    ):
        assert endpoint in script or endpoint in html

    for task_type in (
        "data_analysis",
        "knowledge_qa",
        "goods_search",
        "goods_catalog",
        "stock_analysis",
        "competitor_watch",
        "order_query",
        "ad_query",
        "ad_optimize",
        "data_check",
        "ops_report",
        "social_marketing",
        "customer_service",
        "risk_control",
    ):
        assert task_type in script


def test_frontend_never_persists_credentials_to_local_storage():
    script = (
        Path(__file__).parents[1]
        / "ecom_agent_matrix"
        / "api"
        / "frontend"
        / "app.js"
    ).read_text()
    assert "sessionStorage" in script
    assert "localStorage" not in script
