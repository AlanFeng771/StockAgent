"""危險工具的待確認動作（只有人按確認按鈕才會執行）。

規格（Stage 8 spec，2026-10-13 使用者確認：只能按按鈕、結果用固定格式直接顯示）
==========================================================================

- ``create_pending_action(session, session_id, tool_name, arguments, summary, now, ttl_minutes) -> PendingAction``：
  id 為隨機 32 碼 hex；arguments 為驗證後的參數（凍結，確認時照這份執行，不能被改）；expires_at = now + ttl
- ``expire_stale_actions(session, session_id, now) -> list[PendingAction]``：該 session 已過期仍 pending 的
  動作改為 expired，並各寫一則 role="action" 聊天紀錄「已過期（未確認）：{summary}」
- ``list_pending_actions(session, session_id, now)``：先處理過期，再列出 pending（舊到新）
- ``confirm_action(session, action_id, ctx, now) -> ActionOutcome``：
  - 查無 → ``ActionNotFoundError``；已過期 → 標記 expired（寫紀錄）後 ``ActionExpiredError``；
    不是 pending（已確認/取消/執行中）→ ``ActionNotPendingError``
  - 以條件式 UPDATE（status 仍為 pending 才改為 executing）搶下執行權，連點兩次只會執行一次
  - 執行工具 handler：成功 → done，訊息 = ``tool.format_result(data)``；
    ``AnalysisBusyError`` → 退回 pending（使用者可稍後再按）並往上丟（API 409）；
    其他例外 → failed，訊息「執行失敗：{summary}（{錯誤}）」
  - 結果訊息寫入 result_message 與 role="action" 聊天紀錄（下一輪 LLM 看得到）
- ``cancel_action(session, action_id, now) -> ActionOutcome``：pending → cancelled，訊息「已取消：{summary}」
  並寫紀錄；查無 / 非 pending / 已過期的錯誤同 confirm

``ActionOutcome``：action_id、status（done / failed / cancelled）、message
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.chat.tools import TOOLS, ToolContext
from backend.app.db.models import ChatMessage, PendingAction
from backend.app.pipeline.jobs import AnalysisBusyError


class ActionError(Exception):
    """待確認動作例外基底。"""


class ActionNotFoundError(ActionError):
    pass


class ActionNotPendingError(ActionError):
    pass


class ActionExpiredError(ActionError):
    pass


class ActionOutcome(BaseModel):
    action_id: str
    status: Literal["done", "failed", "cancelled"]
    message: str


def create_pending_action(
    session: Session, session_id: str, tool_name: str, arguments: dict, summary: str,
    now: datetime, ttl_minutes: int,
) -> PendingAction:
    action = PendingAction(
        id=secrets.token_hex(16), session_id=session_id, tool_name=tool_name, arguments=arguments,
        summary=summary, status="pending", created_at=now, expires_at=now + timedelta(minutes=ttl_minutes),
    )
    session.add(action)
    session.commit()
    return action


def _resolve(session: Session, action: PendingAction, status: str, message: str, now: datetime) -> None:
    action.status = status
    action.result_message = message
    action.resolved_at = now
    session.add(ChatMessage(session_id=action.session_id, role="action", content=message))
    session.commit()


def _expire(session: Session, action: PendingAction, now: datetime) -> None:
    _resolve(session, action, "expired", f"已過期（未確認）：{action.summary}", now)


def expire_stale_actions(session: Session, session_id: str, now: datetime) -> list[PendingAction]:
    stale = list(session.scalars(
        select(PendingAction).where(
            PendingAction.session_id == session_id, PendingAction.status == "pending", PendingAction.expires_at <= now,
        ).order_by(PendingAction.created_at)
    ))
    for action in stale:
        _expire(session, action, now)
    return stale


def list_pending_actions(session: Session, session_id: str, now: datetime) -> list[PendingAction]:
    expire_stale_actions(session, session_id, now)
    return list(session.scalars(
        select(PendingAction).where(PendingAction.session_id == session_id, PendingAction.status == "pending")
        .order_by(PendingAction.created_at)
    ))


def _claim(session: Session, action_id: str, new_status: str, now: datetime) -> PendingAction:
    """條件式 UPDATE 搶下待確認動作：只有仍是 pending 且未過期才成功，避免重複執行。"""
    claimed = session.execute(
        update(PendingAction)
        .where(PendingAction.id == action_id, PendingAction.status == "pending", PendingAction.expires_at > now)
        .values(status=new_status)
    ).rowcount
    session.commit()
    action = session.get(PendingAction, action_id)
    if action is not None:
        session.refresh(action)
    if claimed == 1:
        return action
    if action is None:
        raise ActionNotFoundError(f"找不到待確認動作 {action_id}")
    if action.status == "pending":  # 仍是 pending 卻沒搶到 → 已過期
        _expire(session, action, now)
        raise ActionExpiredError(f"待確認動作已過期：{action.summary}")
    raise ActionNotPendingError(f"動作已處理過（{action.status}）：{action.summary}")


def confirm_action(session: Session, action_id: str, ctx: ToolContext, now: datetime) -> ActionOutcome:
    action = _claim(session, action_id, "executing", now)
    tool = TOOLS[action.tool_name]
    try:
        data = tool.handler(ctx, tool.args_model(**action.arguments))
    except AnalysisBusyError:
        action.status = "pending"  # 分析忙碌不算失敗，使用者可稍後再按
        session.commit()
        raise
    except Exception as exc:
        message = f"執行失敗：{action.summary}（{exc}）"
        _resolve(session, action, "failed", message, now)
        return ActionOutcome(action_id=action.id, status="failed", message=message)
    message = tool.format_result(data)
    _resolve(session, action, "done", message, now)
    return ActionOutcome(action_id=action.id, status="done", message=message)


def cancel_action(session: Session, action_id: str, now: datetime) -> ActionOutcome:
    action = _claim(session, action_id, "cancelled", now)
    message = f"已取消：{action.summary}"
    _resolve(session, action, "cancelled", message, now)
    return ActionOutcome(action_id=action.id, status="cancelled", message=message)
