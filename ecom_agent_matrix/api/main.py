"""FastAPI 入口：HTTP 与 Agent 矩阵同进程启动。"""

from __future__ import annotations

import asyncio
import time
import uuid
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

# 侧载注册 Agent / Skill
from .. import agents  # noqa: F401
from ..modules import skills  # noqa: F401
from .auth import (
    get_current_security_context,
    validate_security_configuration,
)
from .health import readiness_report
from .dispatch import set_application_service
from .route_customer import router as customer_router
from .route_task import router as task_router
from .route_warn import router as warn_router
from .route_approval import router as approval_router
from .route_admin import router as admin_router
from .route_conversation import router as conversation_router
from .errors import public_error
from ..config.settings import settings
from ..core.logging_config import setup_logger
from ..core.errors import ErrorCode
from ..core.llm import close_http_session
from ..runtime.messaging.registry import agent_map, agent_registry
from ..runtime.container import AppRuntime
from ..core.skill.skill_registry import skill_container
from ..orchestration.master.orchestrator import cancel_master_tasks
from ..db.base import AsyncPGClient
from ..db.redis_client import AsyncRedisClient
from ..platform.observability.context import (
    TraceContext,
    begin_request_performance,
    finish_request_performance,
    get_trace_context,
    trace_context,
)
from ..platform.observability.metrics import metrics
from ..core.security import effective_scopes

logger = setup_logger("api.main")

_agent_task: asyncio.Task | None = None
_runtime: AppRuntime | None = None
_accepting_requests = True

_OPENAPI_TAGS = [
    {"name": "system", "description": "健康检查与注册表"},
    {"name": "tasks", "description": "经 Master Fast Path / Typed DAG / Recovery 的通用运营任务"},
    {"name": "customer", "description": "店铺规则 / 售后问答（经 Master → RAG 或查询）"},
    {"name": "warn", "description": "竞品价格查询（经 Master 或直达 Query）"},
    {"name": "approvals", "description": "高风险写操作人工审批"},
    {"name": "admin", "description": "管理员商品与知识库维护"},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _agent_task, _runtime, _accepting_requests
    _accepting_requests = True
    validate_security_configuration(settings)
    logger.info(
        "api_starting",
        extra={
            "event": "api_starting",
            "agents": sorted(agent_map.keys()),
            "auth_mode": settings.AUTH_MODE,
        },
    )
    if not agent_map:
        raise RuntimeError("agent_map 为空：侧载注册失败")
    _runtime = AppRuntime.build(settings, agent_registry=agent_registry)
    await _runtime.start()
    _agent_task = _runtime._agent_task
    _app.state.runtime = _runtime
    set_application_service(_runtime.application_service)
    yield
    _accepting_requests = False
    await shutdown_runtime(_runtime)
    _runtime = None
    _agent_task = None


async def shutdown_runtime(runtime_or_task: AppRuntime | asyncio.Task | None) -> None:
    """Bounded cleanup owned by the FastAPI lifespan."""

    async def cleanup():
        if isinstance(runtime_or_task, AppRuntime):
            await runtime_or_task.close()
            return
        agent_task = runtime_or_task
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except asyncio.CancelledError:
                pass
        await cancel_master_tasks()
        await close_http_session()
        await AsyncRedisClient.close()
        await AsyncPGClient.close()

    try:
        await asyncio.wait_for(cleanup(), timeout=float(settings.SHUTDOWN_TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        logger.error(
            "shutdown_timeout",
            extra={
                "event": "shutdown_timeout",
                "error_code": ErrorCode.INTERNAL_ERROR.value,
                "component": "runtime",
            },
        )


app = FastAPI(
    title="Ecom Agent Matrix",
    version="0.2.0",
    description=(
        "跨境独立站电商多智能体矩阵 HTTP 网关。\n\n"
        "- 交互文档：`/docs`（Swagger）或 `/redoc`\n"
        "- 鉴权：开发环境 X-API-Key，生产环境 JWT Bearer token\n"
        "- 通用任务走 Master（规划/分发/聚合）；子 Agent 仅 Query / Exec / RAG"
    ),
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
)
app.include_router(task_router)
app.include_router(customer_router)
app.include_router(warn_router)
app.include_router(approval_router)
app.include_router(admin_router)
app.include_router(conversation_router)

_FRONTEND_DIR = Path(__file__).with_name("frontend")
app.mount("/app/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="agent-console-static")


def _error_code_for_status(status_code: int) -> ErrorCode:
    if status_code == 401:
        return ErrorCode.AUTHENTICATION_REQUIRED
    if status_code == 403:
        return ErrorCode.PERMISSION_DENIED
    if status_code == 429:
        return ErrorCode.RATE_LIMITED
    if status_code == 504:
        return ErrorCode.AGENT_TIMEOUT
    if status_code in {502, 503}:
        return ErrorCode.AGENT_UNAVAILABLE
    if status_code in {400, 404, 409, 422}:
        return ErrorCode.INVALID_REQUEST
    return ErrorCode.INTERNAL_ERROR


@app.exception_handler(HTTPException)
async def human_http_error(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("error_code"):
        payload = {**detail, "success": False}
    else:
        payload = public_error(
            _error_code_for_status(exc.status_code),
            message=str(detail) if exc.status_code in {400, 404, 409, 422} else "",
            task_id=get_trace_context().task_id,
        )
    headers = dict(exc.headers or {})
    if payload.get("task_id"):
        headers.setdefault("X-Task-Id", str(payload["task_id"]))
    return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)


@app.exception_handler(RequestValidationError)
async def human_validation_error(_request: Request, exc: RequestValidationError):
    fields = [
        {
            "field": ".".join(str(part) for part in item.get("loc", [])[1:]),
            "message": item.get("msg", "输入不正确"),
        }
        for item in exc.errors()[:10]
    ]
    payload = public_error(
        ErrorCode.VALIDATION_ERROR,
        task_id=get_trace_context().task_id,
        context={"fields": fields},
    )
    return JSONResponse(status_code=422, content=payload)


@app.get("/", include_in_schema=False)
@app.get("/app", include_in_schema=False)
async def agent_console():
    """Serve the same-origin Agent Console frontend."""
    return FileResponse(_FRONTEND_DIR / "index.html")


@app.middleware("http")
async def observe_http_request(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    task_id = str(uuid.uuid4())
    begin_request_performance(task_id)
    with trace_context(TraceContext(task_id=task_id, request_started_at=time.time())):
        try:
            if not _accepting_requests and request.url.path not in {"/health", "/health/ready"}:
                response = PlainTextResponse("DEPENDENCY_UNAVAILABLE", status_code=503)
            else:
                response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", None) or "unmatched"
            latency = time.perf_counter() - started
            metrics.observe_http(request.method, route, status_code, latency)
            trace = get_trace_context()
            logger.info(
                "http_request_completed",
                extra={
                    "event": "http_request_completed",
                    "method": request.method,
                    "route": route,
                    "status": status_code,
                    "latency_ms": round(latency * 1000, 2),
                    "task_id": trace.task_id,
                    "correlation_id": trace.correlation_id,
                },
            )
            finish_request_performance(task_id)


@app.get("/health", tags=["system"], summary="存活探针（不探测外部依赖）")
async def health():
    return {
        "status": "ok",
        "agents_running": bool(_agent_task and not _agent_task.done()),
        "agents_count": len(agent_map),
        "skills_count": len(skill_container),
        "api_auth_enabled": True,
    }


@app.get("/health/ready", tags=["system"], summary="就绪探针（Postgres + Redis）")
async def health_ready(response: Response):
    agents_alive = bool(_agent_task and not _agent_task.done())
    report = await readiness_report(
        agents_alive=agents_alive,
        catalog_source=_runtime.catalog_source if _runtime else None,
        schema_version=_runtime.schema_version if _runtime else "",
    )
    if not report["ready"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if report["ready"] else "not_ready",
        "agents_running": agents_alive,
        **report,
    }


@app.get("/metrics", tags=["system"], include_in_schema=False)
async def prometheus_metrics(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    if settings.METRICS_AUTH_REQUIRED or str(settings.APP_ENV).lower() == "production":
        security = await get_current_security_context(authorization, x_api_key)
        if "system:read" not in effective_scopes(security):
            raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get(
    "/api/v1/agents",
    tags=["system"],
    summary="已注册 Agent / Skill",
    dependencies=[Depends(get_current_security_context)],
)
async def list_agents():
    return {"agents": sorted(agent_map.keys()), "skills": sorted(skill_container.keys())}


@app.get(
    "/api/v1/system/rag/status",
    tags=["system"],
    summary="Demo data and RAG index status",
    dependencies=[Depends(get_current_security_context)],
)
async def rag_status():
    """Expose non-secret readiness facts used by the chat-first console."""
    try:
        rows = await AsyncPGClient.execute_sql(
            """SELECT
            COUNT(DISTINCT COALESCE(meta_json->>'document_id', goods_sku)),
            COUNT(*), COUNT(embedding)
            FROM vector_goods_kb WHERE tenant_id=%s AND store_id=%s""",
            [settings.DEV_TENANT_ID, settings.DEV_STORE_ID],
        )
        demo = await AsyncPGClient.execute_sql(
            """SELECT
            (SELECT COUNT(*) FROM ecom_goods WHERE tenant_id=%s AND store_id=%s),
            (SELECT COUNT(*) FROM ecom_order WHERE tenant_id=%s AND store_id=%s),
            (SELECT COUNT(*) FROM competitor_price WHERE tenant_id=%s AND store_id=%s),
            (SELECT COUNT(*) FROM risk_record WHERE tenant_id=%s AND store_id=%s)""",
            [settings.DEV_TENANT_ID, settings.DEV_STORE_ID] * 4,
        )
        documents, chunks, vectors = (int(value or 0) for value in rows[0])
        vector_ready = vectors > 0
        return {
            "documents": documents,
            "chunks": chunks,
            "vector_chunks": vectors,
            "vector_ready": vector_ready,
            "lexical_ready": chunks > 0,
            "embedding_runtime_installed": importlib.util.find_spec("sentence_transformers")
            is not None,
            "retrieval_backend": "postgresql/pgvector+lexical",
            "retrieval_mode": "hybrid" if vector_ready else "lexical_only" if chunks else "none",
            "demo_data": {
                "loaded": bool(demo[0][0] and demo[0][1]),
                "products": int(demo[0][0]),
                "orders": int(demo[0][1]),
                "competitor_records": int(demo[0][2]),
                "risk_records": int(demo[0][3]),
            },
        }
    except Exception:
        return {
            "documents": 0,
            "chunks": 0,
            "vector_ready": False,
            "lexical_ready": False,
            "retrieval_mode": "none",
            "demo_data": {"loaded": False},
            "hint": "Run: python -m ecom_agent_matrix.scripts.bootstrap_demo",
        }
