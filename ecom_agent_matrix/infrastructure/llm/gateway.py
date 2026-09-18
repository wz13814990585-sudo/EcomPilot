from ...core.llm import close_http_session, llm_chat


class LLMGateway:
    async def chat(self, **kwargs):
        return await llm_chat(**kwargs)

    async def close(self) -> None:
        await close_http_session()


__all__ = ["LLMGateway"]
