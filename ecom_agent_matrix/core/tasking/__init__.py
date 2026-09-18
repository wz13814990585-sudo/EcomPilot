"""统一任务上下文与确定性字段标准化。"""

from .context import TaskContext
from .normalizer import (
    ensure_task_context,
    normalize_task_context,
)
from .result import WorkflowResult
from .status import TaskStatus
from .requests import (
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
    "TaskStatus",
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
