"""Conversation lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from .auth import get_current_security_context
from .conversation import clear_conversation
from ..core.security import SecurityContext

router = APIRouter(prefix="/api/v1/conversations", tags=["customer"])


@router.delete("/{session_id}")
async def delete_conversation(
    session_id: str = Path(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]+$"),
    security: SecurityContext = Depends(get_current_security_context),
):
    await clear_conversation(session_id, security)
    return {"success": True, "message": "对话记录和短期记忆已清除。", "session_id": session_id}


__all__ = ["router"]
