"""LLM 客户端包。

业务只依赖本包的供应商无关接口：

    LLM Provider
     ├── DeepSeek
     ├── OpenAI
     └── Future Provider（实现 LLMProvider 后注册到 router）
"""

from .http import close_http_session, get_http_session
from .provider import LLMProvider, OpenAICompatProvider
from .router import (
    available_providers,
    current_provider_name,
    get_llm_provider,
    is_llm_configured,
    llm_chat,
    llm_reasoner,
    resolve_mode,
    resolve_model,
)
from .types import (
    ChatMode,
    ChatResult,
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
)
from .structured import llm_chat_structured

__all__ = [
    "ChatMode",
    "ChatResult",
    "LLMAuthError",
    "LLMError",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMResponseError",
    "LLMServerError",
    "OpenAICompatProvider",
    "available_providers",
    "close_http_session",
    "current_provider_name",
    "get_http_session",
    "get_llm_provider",
    "is_llm_configured",
    "llm_chat",
    "llm_chat_structured",
    "llm_reasoner",
    "resolve_mode",
    "resolve_model",
]
