"""LLM 供应商实现。

新增供应商：
1. 实现 LLMProvider（或继承 OpenAICompatProvider）
2. 在 router.PROVIDER_REGISTRY 注册名称
"""

from .deepseek import DeepSeekProvider
from .openai import OpenAIProvider

__all__ = ["DeepSeekProvider", "OpenAIProvider"]
