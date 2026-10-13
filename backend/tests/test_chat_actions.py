from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.chat.actions import (
    ActionExpiredError,
    ActionNotFoundError,
    ActionNotPendingError,
    cancel_action,
    confirm_action,
    create_pending_action,
    expire_stale_actions,
    list_pending_actions,
)
from backend.app.db import crud
from backend.app.db.models import PendingAction
from backend.app.pipeline.jobs import AnalysisBusyError
from backend.tests.test_chat_tools import ctx  # noqa: F401

NOW = datetime(2026, 10, 13, 10, 0)


def pending_remove(ctx, session_id="s1", now=NOW):
    crud.add_watchlist(ctx.session, "2330", "台積電")
    return create_pending_action(ctx.session, session_id, "remove_watchlist_stock", {"stock_id": "2330"},
                                 "移除追蹤：2330 台積電", now=now, ttl_minutes=10)


def messages(ctx, session_id="s1"):
    return [(m.role, m.content) for m in crud.get_chat_history(ctx.session, session_id)]


def test_create_pending_action(ctx):
    action = pending_remove(ctx)

    assert len(action.id) == 32 and action.status == "pending"
    assert action.expires_at == NOW + timedelta(minutes=10)
    assert crud.get_watchlist_item(ctx.session, "2330") is not None  # 建立時不執行


def test_confirm_executes_frozen_arguments_and_records_message(ctx):
    action = pending_remove(ctx)

    outcome = confirm_action(ctx.session, action.id, ctx, now=NOW + timedelta(minutes=5))

    assert outcome.status == "done" and outcome.message == "已移除追蹤：2330 台積電"
    assert crud.get_watchlist_item(ctx.session, "2330") is None
    assert ctx.session.get(PendingAction, action.id).status == "done"
    assert messages(ctx) == [("action", "已移除追蹤：2330 台積電")]


def test_confirm_twice_runs_once(ctx):
    action = pending_remove(ctx)
    confirm_action(ctx.session, action.id, ctx, now=NOW)

    with pytest.raises(ActionNotPendingError):
        confirm_action(ctx.session, action.id, ctx, now=NOW)


def test_confirm_unknown_action(ctx):
    with pytest.raises(ActionNotFoundError):
        confirm_action(ctx.session, "0" * 32, ctx, now=NOW)


def test_confirm_after_expiry(ctx):
    action = pending_remove(ctx)

    with pytest.raises(ActionExpiredError):
        confirm_action(ctx.session, action.id, ctx, now=NOW + timedelta(minutes=11))

    assert ctx.session.get(PendingAction, action.id).status == "expired"
    assert crud.get_watchlist_item(ctx.session, "2330") is not None
    assert messages(ctx) == [("action", "已過期（未確認）：移除追蹤：2330 台積電")]


def test_cancel(ctx):
    action = pending_remove(ctx)

    outcome = cancel_action(ctx.session, action.id, now=NOW)

    assert outcome.status == "cancelled" and outcome.message == "已取消：移除追蹤：2330 台積電"
    assert crud.get_watchlist_item(ctx.session, "2330") is not None
    assert messages(ctx) == [("action", "已取消：移除追蹤：2330 台積電")]
    with pytest.raises(ActionNotPendingError):
        confirm_action(ctx.session, action.id, ctx, now=NOW)


def test_failed_execution_is_recorded(ctx):
    action = pending_remove(ctx)
    crud.remove_watchlist(ctx.session, "2330")  # 確認前已被別處移除

    outcome = confirm_action(ctx.session, action.id, ctx, now=NOW)

    assert outcome.status == "failed"
    assert outcome.message.startswith("執行失敗：移除追蹤：2330 台積電")
    assert ctx.session.get(PendingAction, action.id).status == "failed"
    assert messages(ctx)[-1] == ("action", outcome.message)


def test_busy_analysis_returns_to_pending(ctx):
    def busy(stock_id):
        raise AnalysisBusyError("已有分析在執行中")

    ctx.run_analysis = busy
    action = create_pending_action(ctx.session, "s1", "analyze_stock", {"stock_id": "2330"}, "分析 2330",
                                   now=NOW, ttl_minutes=10)

    with pytest.raises(AnalysisBusyError):
        confirm_action(ctx.session, action.id, ctx, now=NOW)

    assert ctx.session.get(PendingAction, action.id).status == "pending"
    assert messages(ctx) == []


def test_confirm_analysis_shows_report_summary(ctx):
    action = create_pending_action(ctx.session, "s1", "analyze_stock", {"stock_id": "2330"}, "分析 2330",
                                   now=NOW, ttl_minutes=10)

    outcome = confirm_action(ctx.session, action.id, ctx, now=NOW)

    assert outcome.status == "done" and outcome.message.startswith("已完成分析：2330 台積電")


def test_expire_and_list_only_own_session(ctx):
    old = pending_remove(ctx, now=NOW - timedelta(minutes=20))
    fresh = create_pending_action(ctx.session, "s1", "analyze_stock", {"stock_id": "2330"}, "分析 2330",
                                  now=NOW, ttl_minutes=10)
    other = create_pending_action(ctx.session, "s2", "analyze_stock", {"stock_id": "2330"}, "分析 2330",
                                  now=NOW - timedelta(minutes=20), ttl_minutes=10)

    assert [a.id for a in list_pending_actions(ctx.session, "s1", now=NOW)] == [fresh.id]
    assert ctx.session.get(PendingAction, old.id).status == "expired"
    assert ctx.session.get(PendingAction, other.id).status == "pending"  # 別的 session 不動
    assert expire_stale_actions(ctx.session, "s1", now=NOW) == []  # 已處理過不重複寫紀錄
    assert messages(ctx) == [("action", "已過期（未確認）：移除追蹤：2330 台積電")]
