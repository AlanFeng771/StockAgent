"""聊天 agentic loop：送訊息給 ChatGPT、依權限分派工具呼叫、定期總結聊天紀錄。

規格（Stage 8 spec，2026-10-13 使用者確認）
==========================================

``ChatService(settings=None, client=None, prompt=None, summary_prompt=None, now=datetime.now)``

``send(ctx, session_id, message) -> ChatReply``
--------------------------------------------
1. 沒有 OpenAI key（或仍是範例值）→ ``ChatNotConfiguredError``（什麼都不寫入）；
   訊息去空白後為空或超過 ``chat_message_max_chars`` → ``ChatInputError``
2. 處理該 session 已過期的待確認動作（寫入過期紀錄）→ 存入使用者訊息
3. 組 messages：system prompt（含今天日期、禁止事項與引導）＋聊天摘要（若有，另一則 system）＋
   未被摘要涵蓋的訊息（最多 recent + every 則；role="action" 以 assistant 身分、加「[動作紀錄]」前綴）
4. 呼叫 ``client.chat.completions.create(model=chat_model, messages, tools, temperature, timeout)``：
   - 回覆帶 ``tool_calls`` → assistant 訊息（含 tool_calls）接回對話，逐筆分派，結果以
     ``{"role": "tool", "tool_call_id", "content": JSON}`` 接回，再呼叫一次
   - 已達 ``chat_max_tool_rounds`` 輪 → 最後一次呼叫帶 ``tool_choice="none"``，要求直接回覆（不會無限迴圈）
   - API 例外 → ``ChatLLMError``（使用者訊息已存，工具已執行的效果保留）
5. 防止謊稱（2026-10-13 實測 gpt-4o 會模仿歷史文字說「請按確認」卻沒呼叫工具）：最終回覆要使用者
   按確認（``CONFIRM_CLAIM``），但本輪沒有建立待確認動作、該 session 也沒有仍有效的待確認動作 →
   加一則 system 更正訊息重做一次；重做後仍如此 → 回覆末尾加上「本次沒有建立確認按鈕」的系統提示
6. 本輪有呼叫工具 → 存一則 role="tool_log"（每個工具的參數與結果；只給 LLM 看，API 歷史不顯示），
   之後組 context 時以 assistant 身分、「[工具紀錄]」前綴送出，讓 LLM 看到過去「說要按確認」前確實呼叫過工具
7. 存入最終回覆（role="assistant"），視需要更新摘要，回傳 ``ChatReply``

工具分派（回給 LLM 的 tool content 為 JSON）
------------------------------------------
- 不存在的工具（含禁止事項）→ rejected，``{"ok": false, "error": "沒有這個工具…"}``
- 參數不是 JSON 或驗證失敗 → rejected
- auto：執行 handler → ``{"ok": true, "data"}``（executed）；例外 → ``{"ok": false, "error"}``（failed）
- confirm：**不執行**。``describe`` 前置檢查失敗 → failed；否則建立待確認動作 →
  ``{"ok": false, "status": "pending_confirmation", "action_id", "summary", "message": 需使用者在畫面上按確認…}``
- 每次分派記錄一筆 ``ActionLog``（tool、arguments、level、status、summary、error、action_id）

聊天摘要（使用者確認：定期呼叫 LLM 總結，gpt-4o-mini）
----------------------------------------------------
未被摘要涵蓋的訊息達 ``chat_recent_messages + chat_summary_every`` 則時，把最舊的（保留最近
``chat_recent_messages`` 則）連同舊摘要交給 ``chat_summary_model`` 濃縮，更新 ``ChatSummary``
（covered_until_id = 被併入的最後一則 id）。總結失敗不影響回覆（下次再試）。

``ChatReply``：session_id、reply、actions_taken、pending_actions（該 session 仍待確認的動作）
"""

from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from typing import Any, Callable, Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.chat.actions import create_pending_action, expire_stale_actions, list_pending_actions
from backend.app.chat.tools import FORBIDDEN_ACTIONS, TOOLS, ToolContext, openai_tool_schemas
from backend.app.config import Settings, get_settings
from backend.app.db import crud
from backend.app.db.models import ChatMessage, ChatSummary
from backend.app.llm.prompt_templates import PromptTemplate, load_prompt
from backend.app.llm.report_generator import PLACEHOLDER_API_KEY

logger = logging.getLogger(__name__)


class ChatError(Exception):
    """聊天例外基底。"""


class ChatNotConfiguredError(ChatError):
    pass


class ChatInputError(ChatError, ValueError):
    pass


class ChatLLMError(ChatError):
    pass


class ActionLog(BaseModel):
    tool: str
    arguments: dict | str
    level: Literal["auto", "confirm"] | None
    status: Literal["executed", "failed", "pending_confirmation", "rejected"]
    summary: str | None = None
    error: str | None = None
    action_id: str | None = None


class PendingActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_name: str
    arguments: dict
    summary: str
    created_at: datetime
    expires_at: datetime


class ChatReply(BaseModel):
    session_id: str
    reply: str
    actions_taken: list[ActionLog]
    pending_actions: list[PendingActionOut]


ACTION_PREFIX = "[動作紀錄] "
TOOL_LOG_PREFIX = "[工具紀錄] "
ROLE_LABELS = {"user": "使用者", "assistant": "助理", "action": "動作紀錄", "tool_log": "工具紀錄"}
PENDING_MESSAGE = "尚未執行。已在畫面上建立確認按鈕，需使用者親自按下確認才會執行，你無法代為確認。請告知使用者按確認。"

# 回覆要使用者按確認，但畫面上沒有任何確認按鈕（2026-10-13 實測 gpt-4o 會模仿歷史文字而不呼叫工具）
CONFIRM_CLAIM = re.compile(r"確認按鈕|按下?.{0,4}確認")
FALSE_CLAIM_CORRECTION = (
    "系統檢查：你剛才的回覆要求使用者按確認按鈕，但這一輪你沒有呼叫任何危險動作工具，畫面上沒有確認按鈕。"
    "若使用者要求移除或分析，請現在呼叫對應工具（多檔股票就逐一呼叫）；否則請更正回覆，不要提到確認按鈕。"
)
FALSE_CLAIM_NOTICE = "\n\n（系統提示：本次沒有建立確認按鈕，上述動作並未執行。）"
STATUS_TEXT = {"executed": "已執行", "failed": "失敗", "rejected": "被拒絕", "pending_confirmation": "待使用者確認"}


def _tool_log_text(actions: list[ActionLog]) -> str:
    """該輪實際呼叫的工具（存成 tool_log，下一輪 LLM 才看得到「說要按確認」之前確實呼叫過工具）。"""
    lines = []
    for log in actions:
        args = log.arguments if isinstance(log.arguments, str) else ", ".join(f"{k}={v}" for k, v in log.arguments.items())
        line = f"- {log.tool}({args}) → {STATUS_TEXT[log.status]}"
        if log.status == "pending_confirmation":
            line += f"（已建立確認按鈕：{log.summary}）"
        elif log.error:
            line += f"：{log.error}"
        lines.append(line)
    return "\n".join(lines)


class ChatService:
    def __init__(
        self,
        settings: Settings | None = None,
        client: Any = None,
        prompt: PromptTemplate | None = None,
        summary_prompt: PromptTemplate | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.prompt = prompt or load_prompt("chat")
        self.summary_prompt = summary_prompt or load_prompt("chat_summary")
        self._now = now

    # ------------------------------------------------------------------ 對外
    def send(self, ctx: ToolContext, session_id: str, message: str) -> ChatReply:
        api_key = self.settings.openai_api_key
        if not api_key or api_key == PLACEHOLDER_API_KEY:
            raise ChatNotConfiguredError("未設定 OPENAI_API_KEY（或仍是 .env.example 的範例值），無法聊天")
        message = (message or "").strip()
        if not message or len(message) > self.settings.chat_message_max_chars:
            raise ChatInputError(f"訊息不可為空，且不可超過 {self.settings.chat_message_max_chars} 字")

        session = ctx.session
        now = self._now()
        expire_stale_actions(session, session_id, now)
        crud.add_chat_message(session, session_id, "user", message)

        messages = self._build_context(session, session_id, now)
        actions: list[ActionLog] = []
        rounds = 0
        corrected = False
        while True:
            allow_tools = rounds < self.settings.chat_max_tool_rounds
            reply_message = self._complete(messages, allow_tools)
            tool_calls = getattr(reply_message, "tool_calls", None) or []
            if not (tool_calls and allow_tools):
                reply = reply_message.content or ""
                if not self._false_confirmation_claim(reply, actions, session, session_id, now):
                    break
                if corrected:
                    reply += FALSE_CLAIM_NOTICE
                    break
                corrected = True  # 要使用者按確認、卻沒有任何確認按鈕 → 退回重做一次
                messages += [{"role": "assistant", "content": reply}, {"role": "system", "content": FALSE_CLAIM_CORRECTION}]
                continue
            messages.append({"role": "assistant", "content": reply_message.content, "tool_calls": [
                {"id": call.id, "type": "function",
                 "function": {"name": call.function.name, "arguments": call.function.arguments}}
                for call in tool_calls
            ]})
            for call in tool_calls:
                content, log = self._dispatch(ctx, session_id, call.function.name, call.function.arguments, now)
                actions.append(log)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(content, ensure_ascii=False)})
            rounds += 1

        if actions:
            crud.add_chat_message(session, session_id, "tool_log", _tool_log_text(actions))
        crud.add_chat_message(session, session_id, "assistant", reply)
        self._maybe_summarize(session, session_id)
        pending = list_pending_actions(session, session_id, now)
        return ChatReply(
            session_id=session_id, reply=reply, actions_taken=actions,
            pending_actions=[PendingActionOut.model_validate(action) for action in pending],
        )

    # ------------------------------------------------------------------ LLM
    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def _complete(self, messages: list[dict], allow_tools: bool):
        kwargs = dict(
            model=self.settings.chat_model, messages=messages, tools=openai_tool_schemas(),
            temperature=self.settings.chat_temperature, timeout=self.settings.openai_timeout_seconds,
        )
        if not allow_tools:
            kwargs["tool_choice"] = "none"
        try:
            return self.client.chat.completions.create(**kwargs).choices[0].message
        except Exception as exc:
            raise ChatLLMError(f"ChatGPT 呼叫失敗：{type(exc).__name__}: {exc}") from exc

    def _build_context(self, session: Session, session_id: str, now: datetime) -> list[dict]:
        forbidden = "\n".join(f"- {action.guidance}" for action in FORBIDDEN_ACTIONS)
        system = self.prompt.system + "\n\n" + self.prompt.render("context", today=now.date().isoformat(),
                                                                  forbidden=forbidden)
        messages = [{"role": "system", "content": system}]
        summary = session.get(ChatSummary, session_id)
        if summary is not None:
            messages.append({"role": "system", "content": f"先前對話摘要：\n{summary.content}"})
        limit = self.settings.chat_recent_messages + self.settings.chat_summary_every
        for row in self._uncovered(session, session_id, summary)[-limit:]:
            messages.append(self._to_llm_message(row))
        return messages

    @staticmethod
    def _false_confirmation_claim(
        reply: str, actions: list[ActionLog], session: Session, session_id: str, now: datetime,
    ) -> bool:
        if not CONFIRM_CLAIM.search(reply):
            return False
        if any(log.status == "pending_confirmation" for log in actions):
            return False
        return not list_pending_actions(session, session_id, now)  # 之前建立、仍有效的按鈕也算

    def _to_llm_message(self, row: ChatMessage) -> dict:
        if row.role == "action":
            return {"role": "assistant", "content": ACTION_PREFIX + row.content}
        if row.role == "tool_log":
            return {"role": "assistant", "content": TOOL_LOG_PREFIX + "\n" + row.content}
        if row.role == "user":
            return {"role": "user", "content": self.prompt.render_user(message=row.content)}
        return {"role": row.role, "content": row.content}

    @staticmethod
    def _uncovered(session: Session, session_id: str, summary: ChatSummary | None) -> list[ChatMessage]:
        covered = summary.covered_until_id if summary is not None else 0
        return list(session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.id > covered)
            .order_by(ChatMessage.id)
        ))

    # ------------------------------------------------------------------ 工具
    def _dispatch(self, ctx: ToolContext, session_id: str, name: str, raw_arguments: str, now: datetime):
        tool = TOOLS.get(name)
        if tool is None:
            error = f"沒有名為 {name} 的工具。若是禁止的操作，請依系統說明用文字引導使用者。"
            return {"ok": False, "error": error}, ActionLog(
                tool=name, arguments=raw_arguments, level=None, status="rejected", error=error)
        try:
            args = tool.args_model.model_validate(json.loads(raw_arguments or "{}"))
        except (ValueError, ValidationError) as exc:
            error = f"參數錯誤：{exc}"
            return {"ok": False, "error": error}, ActionLog(
                tool=name, arguments=raw_arguments, level=tool.level, status="rejected", error=error)
        arguments = args.model_dump(mode="json", exclude_none=True)

        if tool.level == "auto":
            try:
                data = tool.handler(ctx, args)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                return {"ok": False, "error": error}, ActionLog(
                    tool=name, arguments=arguments, level="auto", status="failed", error=error)
            return {"ok": True, "data": data}, ActionLog(
                tool=name, arguments=arguments, level="auto", status="executed")

        try:
            summary = tool.describe(ctx, args)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": error}, ActionLog(
                tool=name, arguments=arguments, level="confirm", status="failed", error=error)
        action = create_pending_action(ctx.session, session_id, name, arguments, summary, now=now,
                                       ttl_minutes=self.settings.chat_action_ttl_minutes)
        content = {"ok": False, "status": "pending_confirmation", "action_id": action.id, "summary": summary,
                   "message": PENDING_MESSAGE}
        return content, ActionLog(tool=name, arguments=arguments, level="confirm", status="pending_confirmation",
                                  summary=summary, action_id=action.id)

    # ------------------------------------------------------------------ 摘要
    def _maybe_summarize(self, session: Session, session_id: str) -> None:
        summary = session.get(ChatSummary, session_id)
        uncovered = self._uncovered(session, session_id, summary)
        recent = self.settings.chat_recent_messages
        if len(uncovered) < recent + self.settings.chat_summary_every:
            return
        fold = uncovered[:-recent] if recent else uncovered
        transcript = "\n".join(f"{ROLE_LABELS.get(row.role, row.role)}：{row.content}" for row in fold)
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.chat_summary_model,
                messages=[
                    {"role": "system", "content": self.summary_prompt.system},
                    {"role": "user", "content": self.summary_prompt.render_user(
                        previous_summary=summary.content if summary else "（無）", messages=transcript)},
                ],
                temperature=0, timeout=self.settings.openai_timeout_seconds,
            )
            content = (completion.choices[0].message.content or "").strip()
        except Exception:
            logger.warning("聊天摘要失敗（session=%s），下次再試", session_id, exc_info=True)
            return
        if not content:
            return
        if summary is None:
            summary = ChatSummary(session_id=session_id)
            session.add(summary)
        summary.content = content
        summary.covered_until_id = fold[-1].id
        summary.model = self.settings.chat_summary_model
        session.commit()

