"""聊天端點與危險動作的確認／取消（只有人按按鈕才會呼叫確認端點）。"""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import get_session, tool_context
from backend.app.api.schemas import ActionRequest, ChatHistoryOut, ChatIn
from backend.app.chat.actions import ActionOutcome, cancel_action, confirm_action, list_pending_actions
from backend.app.chat.chat_service import ChatReply
from backend.app.db import crud

router = APIRouter(prefix="/api/chat")
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
VISIBLE_ROLES = ("user", "assistant", "action")  # tool_log 只給 LLM 看


@router.post("", response_model=ChatReply)
def chat(body: ChatIn, request: Request, session: Session = Depends(get_session)):
    session_id = body.session_id or secrets.token_hex(16)
    return request.app.state.chat_service.send(tool_context(request, session), session_id, body.message)


@router.get("/history", response_model=ChatHistoryOut)
def history(
    session_id: str = Query(pattern=SESSION_ID_PATTERN), limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    return ChatHistoryOut(
        session_id=session_id,
        messages=crud.get_chat_history(session, session_id, limit=limit, roles=VISIBLE_ROLES),
        pending_actions=list_pending_actions(session, session_id, datetime.now()),
    )


@router.post("/actions/{action_id}/confirm", response_model=ActionOutcome)
def confirm(action_id: str, body: ActionRequest, request: Request, session: Session = Depends(get_session)):
    return confirm_action(session, action_id, tool_context(request, session), datetime.now())


@router.post("/actions/{action_id}/cancel", response_model=ActionOutcome)
def cancel(action_id: str, body: ActionRequest, session: Session = Depends(get_session)):
    return cancel_action(session, action_id, datetime.now())
