from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import openai
import pytest

from backend.app.chat.actions import create_pending_action
from backend.app.chat.chat_service import (
    ChatInputError,
    ChatLLMError,
    ChatNotConfiguredError,
    ChatService,
)
from backend.app.config import Settings
from backend.app.db import crud
from backend.app.db.models import ChatSummary, PendingAction
from backend.tests.test_chat_tools import ctx  # noqa: F401

NOW = datetime(2026, 10, 13, 10, 0)


def tool_call(name, args, call_id="call_1"):
    arguments = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments))


def completion(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class ScriptedClient:
    """依序回傳預先排好的回應；摘要模型的呼叫另外回傳固定摘要。記錄每次呼叫參數。"""

    def __init__(self, *responses, summary="摘要內容", error=None, summary_error=None):
        self.responses = list(responses)
        self.calls, self.summary_calls = [], []
        self.summary, self.error, self.summary_error = summary, error, summary_error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        kwargs = copy.deepcopy(kwargs)
        if kwargs["model"] == "gpt-4o-mini":
            self.summary_calls.append(kwargs)
            if self.summary_error:
                raise self.summary_error
            return completion(self.summary)
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.responses.pop(0)


def settings(**overrides):
    values = dict(openai_api_key="sk-test", chat_model="gpt-4o", chat_summary_model="gpt-4o-mini")
    values.update(overrides)
    return Settings(_env_file=None, **values)


def service(client, **overrides):
    return ChatService(settings=settings(**overrides), client=client, now=lambda: NOW)


def history(ctx, session_id="s1"):
    return [(m.role, m.content) for m in crud.get_chat_history(ctx.session, session_id, limit=500)]


# ---------------------------------------------------------------------------
# 基本對話
# ---------------------------------------------------------------------------

def test_plain_reply_saved_with_system_prompt(ctx):
    client = ScriptedClient(completion("你好"))

    reply = service(client).send(ctx, "s1", "  嗨  ")

    assert reply.reply == "你好" and reply.actions_taken == [] and reply.pending_actions == []
    assert history(ctx) == [("user", "嗨"), ("assistant", "你好")]
    request = client.calls[0]
    assert request["model"] == "gpt-4o"
    assert request["messages"][0]["role"] == "system"
    assert "2026-10-13" in request["messages"][0]["content"]  # 今天日期
    assert "儀表板" in request["messages"][0]["content"]  # 禁止事項的引導
    assert request["messages"][-1] == {"role": "user", "content": "嗨"}
    assert {t["function"]["name"] for t in request["tools"]} >= {"list_watchlist", "analyze_stock"}


@pytest.mark.parametrize("api_key", [None, "your_openai_api_key_here"])
def test_missing_key(ctx, api_key):
    with pytest.raises(ChatNotConfiguredError):
        service(ScriptedClient(), openai_api_key=api_key).send(ctx, "s1", "嗨")
    assert history(ctx) == []


@pytest.mark.parametrize("message", ["", "   ", "字" * 2001])
def test_invalid_message(ctx, message):
    with pytest.raises(ChatInputError):
        service(ScriptedClient()).send(ctx, "s1", message)


def test_api_error_raises_chat_llm_error(ctx):
    client = ScriptedClient(error=openai.APITimeoutError(request=None))

    with pytest.raises(ChatLLMError):
        service(client).send(ctx, "s1", "嗨")
    assert history(ctx) == [("user", "嗨")]


def test_history_is_sent_in_order(ctx):
    client = ScriptedClient(completion("一"), completion("二"))
    chat = service(client)
    chat.send(ctx, "s1", "問一")
    chat.send(ctx, "s1", "問二")

    sent = [(m["role"], m["content"]) for m in client.calls[1]["messages"][1:]]
    assert sent == [("user", "問一"), ("assistant", "一"), ("user", "問二")]


# ---------------------------------------------------------------------------
# 工具分派
# ---------------------------------------------------------------------------

def test_auto_tool_executes_and_result_sent_back(ctx):
    client = ScriptedClient(
        completion(tool_calls=[tool_call("add_watchlist_stock", {"stock_id": "2454"})]),
        completion("已加入 2454 聯發科"),
    )

    reply = service(client).send(ctx, "s1", "把2454加入追蹤")

    assert reply.reply == "已加入 2454 聯發科"
    assert crud.get_watchlist_item(ctx.session, "2454") is not None
    log = reply.actions_taken[0]
    assert (log.tool, log.level, log.status, log.arguments) == ("add_watchlist_stock", "auto", "executed", {"stock_id": "2454"})

    second = client.calls[1]["messages"]
    assistant, tool_message = second[-2], second[-1]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0] == {"id": "call_1", "type": "function", "function": {
        "name": "add_watchlist_stock", "arguments": json.dumps({"stock_id": "2454"})}}
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_1"
    assert json.loads(tool_message["content"]) == {"ok": True, "data": {"added": {"stock_id": "2454", "stock_name": "聯發科"}}}


def test_multiple_tool_calls_in_one_message(ctx):
    client = ScriptedClient(
        completion(tool_calls=[tool_call("add_watchlist_stock", {"stock_id": "2454"}, "a"),
                               tool_call("list_watchlist", {}, "b")]),
        completion("完成"),
    )

    reply = service(client).send(ctx, "s1", "加入並列出")

    tool_messages = [m for m in client.calls[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["a", "b"]
    assert json.loads(tool_messages[1]["content"])["data"]["count"] == 1
    assert [log.tool for log in reply.actions_taken] == ["add_watchlist_stock", "list_watchlist"]


def test_tool_error_is_reported_to_llm(ctx):
    client = ScriptedClient(completion(tool_calls=[tool_call("get_stock_report", {"stock_id": "2330"})]),
                            completion("查無報告"))

    reply = service(client).send(ctx, "s1", "2330 報告")

    content = json.loads(client.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False and "尚無分析報告" in content["error"]
    assert reply.actions_taken[0].status == "failed"


@pytest.mark.parametrize("name, args", [
    ("analyze_watchlist", {}),                      # 禁止事項不是工具
    ("get_latest_price", "{not json"),              # 參數不是 JSON
    ("get_latest_price", {"stock_id": "2330", "x": 1}),  # 多餘參數
    ("get_latest_price", {"stock_id": "abc"}),      # 代號格式錯（handler 正規化時拒絕 → failed）
])
def test_bad_tool_calls_do_not_crash(ctx, name, args):
    client = ScriptedClient(completion(tool_calls=[tool_call(name, args)]), completion("抱歉"))

    reply = service(client).send(ctx, "s1", "測試")

    assert reply.reply == "抱歉"
    assert json.loads(client.calls[1]["messages"][-1]["content"])["ok"] is False
    assert reply.actions_taken[0].status in ("rejected", "failed")


def test_confirm_tool_creates_pending_action_without_executing(ctx):
    crud.add_watchlist(ctx.session, "2330", "台積電")
    client = ScriptedClient(completion(tool_calls=[tool_call("remove_watchlist_stock", {"stock_id": "2330"})]),
                            completion("請按確認"))

    reply = service(client).send(ctx, "s1", "移除2330")

    assert crud.get_watchlist_item(ctx.session, "2330") is not None  # 沒有執行
    log = reply.actions_taken[0]
    assert (log.level, log.status, log.summary) == ("confirm", "pending_confirmation", "移除追蹤：2330 台積電")
    assert [p.id for p in reply.pending_actions] == [log.action_id]
    assert reply.pending_actions[0].expires_at == NOW + timedelta(minutes=10)
    content = json.loads(client.calls[1]["messages"][-1]["content"])
    assert content["status"] == "pending_confirmation" and "按" in content["message"]


def test_confirm_tool_precheck_failure_creates_nothing(ctx):
    client = ScriptedClient(completion(tool_calls=[tool_call("remove_watchlist_stock", {"stock_id": "2330"})]),
                            completion("不在清單"))

    reply = service(client).send(ctx, "s1", "移除2330")

    assert reply.actions_taken[0].status == "failed" and reply.pending_actions == []
    assert ctx.session.query(PendingAction).count() == 0


def test_tool_rounds_are_capped(ctx):
    looping = [completion(tool_calls=[tool_call("list_watchlist", {}, f"c{i}")]) for i in range(2)]
    client = ScriptedClient(*looping, completion("停止"))

    reply = service(client, chat_max_tool_rounds=2).send(ctx, "s1", "一直查")

    assert reply.reply == "停止" and len(client.calls) == 3
    assert "tool_choice" not in client.calls[1]
    assert client.calls[2]["tool_choice"] == "none"


def test_action_messages_sent_as_assistant_records(ctx):
    crud.add_chat_message(ctx.session, "s1", "action", "已移除追蹤：2330 台積電")
    client = ScriptedClient(completion("好"))

    service(client).send(ctx, "s1", "剛剛做了什麼")

    assert {"role": "assistant", "content": "[動作紀錄] 已移除追蹤：2330 台積電"} in client.calls[0]["messages"]


def test_stale_pending_actions_expire_on_send(ctx):
    create_pending_action(ctx.session, "s1", "analyze_stock", {"stock_id": "2330"}, "分析 2330",
                          now=NOW - timedelta(minutes=30), ttl_minutes=10)
    client = ScriptedClient(completion("好"))

    reply = service(client).send(ctx, "s1", "嗨")

    assert reply.pending_actions == []
    assert history(ctx)[0] == ("action", "已過期（未確認）：分析 2330")


# ---------------------------------------------------------------------------
# 聊天摘要
# ---------------------------------------------------------------------------

def seed(ctx, count, session_id="s1"):
    for i in range(count):
        crud.add_chat_message(ctx.session, session_id, "user" if i % 2 == 0 else "assistant", f"m{i}")


def test_no_summary_below_threshold(ctx):
    seed(ctx, 26)  # 加上這輪 2 則 = 28 < 30
    client = ScriptedClient(completion("好"))

    service(client).send(ctx, "s1", "嗨")

    assert client.summary_calls == []


def test_summary_folds_old_messages_and_keeps_recent(ctx):
    seed(ctx, 28)  # 加上這輪 2 則 = 30 → 總結最舊 20 則
    client = ScriptedClient(completion("好"), completion("再好"))
    chat = service(client)

    chat.send(ctx, "s1", "嗨")

    summary_request = client.summary_calls[0]
    assert summary_request["model"] == "gpt-4o-mini"
    prompt_text = json.dumps(summary_request["messages"], ensure_ascii=False)
    assert "m0" in prompt_text and "m19" in prompt_text and "m20" not in prompt_text
    row = ctx.session.get(ChatSummary, "s1")
    assert row.content == "摘要內容" and row.model == "gpt-4o-mini"

    chat.send(ctx, "s1", "再問")
    sent = client.calls[1]["messages"]
    assert sent[1] == {"role": "system", "content": "先前對話摘要：\n摘要內容"}
    contents = [m["content"] for m in sent[2:]]
    assert contents[0] == "m20" and contents[-1] == "再問"


def test_summary_includes_previous_summary(ctx):
    seed(ctx, 28)
    client = ScriptedClient(*[completion("好") for _ in range(11)])
    chat = service(client)
    chat.send(ctx, "s1", "嗨")
    for i in range(10):  # 再 20 則 → 第二次總結
        chat.send(ctx, "s1", f"q{i}")

    assert len(client.summary_calls) == 2
    assert "摘要內容" in json.dumps(client.summary_calls[1]["messages"], ensure_ascii=False)


def test_summary_failure_does_not_break_reply(ctx):
    seed(ctx, 28)
    client = ScriptedClient(completion("好"), summary_error=openai.APITimeoutError(request=None))

    reply = service(client).send(ctx, "s1", "嗨")

    assert reply.reply == "好" and ctx.session.get(ChatSummary, "s1") is None


def test_context_capped_when_summary_keeps_failing(ctx):
    seed(ctx, 60)
    client = ScriptedClient(completion("好"), summary_error=openai.APITimeoutError(request=None))

    service(client).send(ctx, "s1", "嗨")

    assert len(client.calls[0]["messages"]) == 1 + 30  # system + 最多 recent + every 則
