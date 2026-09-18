"""统一任务上下文与确定性字段标准化。"""

from ecom_agent_matrix.core.tasking.context import TaskContext
from ecom_agent_matrix.core.tasking.normalizer import (
    ensure_task_context,
    normalize_task_context,
)
from ecom_agent_matrix.core.tasking.result import WorkflowResult
from ecom_agent_matrix.core.tasking.requests import (
    AdOptimizeRequest,
    CRMReplyRequest,
    CompetitorWatchRequest,
    DataCheckRequest,
    GoodsSearchRequest,
    OrderQueryRequest,
    ProfitInputs,
    RiskOperationRequest,
)

__all__ = [
    "TaskContext",
    "WorkflowResult",
    "ensure_task_context",
    "normalize_task_context",
    "AdOptimizeRequest",
    "CRMReplyRequest",
    "CompetitorWatchRequest",
    "DataCheckRequest",
    "GoodsSearchRequest",
    "OrderQueryRequest",
    "ProfitInputs",
    "RiskOperationRequest",
]
