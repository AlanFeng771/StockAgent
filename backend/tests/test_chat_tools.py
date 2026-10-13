from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from backend.app.chat.quote import PriceQuote
from backend.app.chat.tools import (
    FORBIDDEN_ACTIONS,
    TOOLS,
    QuoteNotFoundError,
    ToolContext,
    format_price,
    openai_tool_schemas,
)
from backend.app.db import crud
from backend.app.db.crud import (
    InvalidStockIdError,
    ReportNotFoundError,
    WatchlistAlreadyExistsError,
    WatchlistNotFoundError,
)
from backend.app.pipeline.analyze_stock import StockNotFoundError
from backend.app.pipeline.watchlist import add_stock_to_watchlist
from backend.tests.api_fixtures import PROFILES, SIGNALS, memory_session_factory
from backend.tests.test_crud import make_result


class FakeQuotes:
    def get_latest_quote(self, stock_id):
        if stock_id != "2330":
            return None
        return PriceQuote(stock_id="2330", date=date(2026, 10, 9), open=1000, high=1020, low=995, close=1015,
                          prev_close=1000, change=15, change_pct=1.5, volume_lots=30000,
                          note="非即時價，為 2026-10-09 收盤")


@pytest.fixture
def ctx():
    factory = memory_session_factory()
    with factory() as session:
        def run_analysis(stock_id):
            return crud.save_report(session, make_result(SIGNALS, stock_id=stock_id, generated_at=datetime(2026, 10, 13, 9)))

        yield ToolContext(session=session, stock_lookup=PROFILES.get, quote_provider=FakeQuotes(),
                          run_analysis=run_analysis)


def call(ctx, name, **args):
    tool = TOOLS[name]
    return tool.handler(ctx, tool.args_model(**args))


# ---------------------------------------------------------------------------
# 權限分級（使用者確認：寫死在程式）
# ---------------------------------------------------------------------------

def test_permission_levels():
    levels = {name: tool.level for name, tool in TOOLS.items()}

    assert levels == {
        "list_watchlist": "auto",
        "add_watchlist_stock": "auto",
        "remove_watchlist_stock": "confirm",
        "get_latest_price": "auto",
        "get_stock_report": "auto",
        "get_report_history": "auto",
        "analyze_stock": "confirm",
    }


def test_confirm_tools_have_describe_and_format():
    for tool in TOOLS.values():
        if tool.level == "confirm":
            assert tool.describe is not None and tool.format_result is not None


def test_forbidden_actions_are_not_tools_and_have_guidance():
    names = {action.name for action in FORBIDDEN_ACTIONS}

    assert {"analyze_watchlist", "trade", "change_settings"} <= names
    assert not names & set(TOOLS)
    assert all(action.guidance for action in FORBIDDEN_ACTIONS)


def test_openai_tool_schemas():
    schemas = {s["function"]["name"]: s for s in openai_tool_schemas()}

    assert set(schemas) == set(TOOLS)
    assert all(s["type"] == "function" for s in schemas.values())
    assert schemas["get_latest_price"]["function"]["parameters"]["required"] == ["stock_id"]
    assert schemas["get_latest_price"]["function"]["parameters"]["additionalProperties"] is False
    assert "按確認" in schemas["remove_watchlist_stock"]["function"]["description"]
    assert "按確認" not in schemas["add_watchlist_stock"]["function"]["description"]


def test_extra_arguments_rejected():
    with pytest.raises(ValidationError):
        TOOLS["get_latest_price"].args_model(stock_id="2330", force=True)


# ---------------------------------------------------------------------------
# 清單管理
# ---------------------------------------------------------------------------

def test_add_stock_to_watchlist_shared_logic(ctx):
    calls = []

    def lookup(stock_id):
        calls.append(stock_id)
        return PROFILES.get(stock_id)

    row = add_stock_to_watchlist(ctx.session, " 2330 ", lookup)
    assert (row.stock_id, row.stock_name) == ("2330", "台積電")

    with pytest.raises(WatchlistAlreadyExistsError):
        add_stock_to_watchlist(ctx.session, "2330", lookup)
    assert calls == ["2330"]  # 已在清單不再查 FinMind
    with pytest.raises(StockNotFoundError):
        add_stock_to_watchlist(ctx.session, "9999", lookup)
    with pytest.raises(InvalidStockIdError):
        add_stock_to_watchlist(ctx.session, "abc", lookup)


def test_add_and_list(ctx):
    assert call(ctx, "add_watchlist_stock", stock_id="2454") == {"added": {"stock_id": "2454", "stock_name": "聯發科"}}
    call(ctx, "add_watchlist_stock", stock_id="2330")

    assert call(ctx, "list_watchlist") == {"count": 2, "items": [
        {"stock_id": "2330", "stock_name": "台積電"}, {"stock_id": "2454", "stock_name": "聯發科"},
    ]}


def test_remove_describe_prechecks_and_handler(ctx):
    tool = TOOLS["remove_watchlist_stock"]
    with pytest.raises(WatchlistNotFoundError):
        tool.describe(ctx, tool.args_model(stock_id="2330"))

    call(ctx, "add_watchlist_stock", stock_id="2330")
    assert tool.describe(ctx, tool.args_model(stock_id="2330")) == "移除追蹤：2330 台積電"

    data = call(ctx, "remove_watchlist_stock", stock_id="2330")
    assert data == {"removed": {"stock_id": "2330", "stock_name": "台積電"}}
    assert tool.format_result(data) == "已移除追蹤：2330 台積電"
    assert crud.get_active_watchlist(ctx.session) == []


# ---------------------------------------------------------------------------
# 查詢
# ---------------------------------------------------------------------------

def test_latest_price(ctx):
    data = call(ctx, "get_latest_price", stock_id="2330")

    assert data["close"] == 1015 and data["date"] == "2026-10-09"
    assert "非即時" in data["note"]
    with pytest.raises(QuoteNotFoundError):
        call(ctx, "get_latest_price", stock_id="2454")


def test_stock_report_contains_report_and_facts(ctx):
    with pytest.raises(ReportNotFoundError):
        call(ctx, "get_stock_report", stock_id="2330")
    crud.save_report(ctx.session, make_result(SIGNALS))

    data = call(ctx, "get_stock_report", stock_id="2330")

    assert data["stock_id"] == "2330" and data["stock_name"] == "台積電"
    assert data["analysis_date"] == "2026-10-01" and data["llm_status"] == "success"
    assert data["report"]["summary"] == "測試摘要"
    assert data["facts"]["stock_id"] == "2330"
    assert "link" not in str(data["facts"]["news"])


def test_stock_report_by_date(ctx):
    crud.save_report(ctx.session, make_result(SIGNALS, analysis_date=date(2026, 9, 30)))
    crud.save_report(ctx.session, make_result(SIGNALS, analysis_date=date(2026, 10, 1)))

    data = call(ctx, "get_stock_report", stock_id="2330", analysis_date="2026-09-30")

    assert data["analysis_date"] == "2026-09-30"


def test_report_history(ctx):
    crud.save_report(ctx.session, make_result(SIGNALS, analysis_date=date(2026, 9, 30)))
    crud.save_report(ctx.session, make_result(SIGNALS, analysis_date=date(2026, 10, 1)))

    data = call(ctx, "get_report_history", stock_id="2330", start="2026-10-01")

    assert data["stock_id"] == "2330"
    assert [item["analysis_date"] for item in data["items"]] == ["2026-10-01"]
    item = data["items"][0]
    assert item["overall_bias"] == "neutral" and item["summary"] == "測試摘要"
    assert item["target_price"] is not None and item["stop_loss"] is not None


# ---------------------------------------------------------------------------
# 分析（危險）
# ---------------------------------------------------------------------------

def test_analyze_describe_and_format(ctx):
    tool = TOOLS["analyze_stock"]
    assert "2330 台積電" in tool.describe(ctx, tool.args_model(stock_id="2330"))
    assert "費用" in tool.describe(ctx, tool.args_model(stock_id="2330"))
    with pytest.raises(StockNotFoundError):
        tool.describe(ctx, tool.args_model(stock_id="9999"))

    data = call(ctx, "analyze_stock", stock_id="2330")
    message = tool.format_result(data)

    assert data["llm_status"] == "success"
    assert message.startswith("已完成分析：2330 台積電（資料日期 2026-10-01）")
    report = data["report"]
    stop = format_price(report["stop_loss"]["price"])
    for expected in ("測試摘要", "目標價", f"停損：{stop}（", "波段"):
        assert expected in message


def test_analyze_format_when_llm_failed():
    data = {"stock_id": "2330", "stock_name": "台積電", "analysis_date": "2026-10-01", "llm_status": "failed",
            "report": None, "report_error": "APITimeoutError", "warnings": []}

    message = TOOLS["analyze_stock"].format_result(data)

    assert "報告未產生" in message and "APITimeoutError" in message


@pytest.mark.parametrize("price, text", [(1015.0, "1015"), (110.85, "110.85"), (97.5, "97.5"), (0.01, "0.01")])
def test_format_price(price, text):
    assert format_price(price) == text
