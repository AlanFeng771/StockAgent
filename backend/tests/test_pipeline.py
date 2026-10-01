from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.app.config import Settings
from backend.app.data_sources import finmind_client as fc
from backend.app.data_sources.finmind_client import FinMindAuthError, FinMindQuotaExceededError
from backend.app.pipeline.analyze_stock import (
    AnalysisError,
    DataSourceError,
    NoPriceDataError,
    StockNotFoundError,
    analyze_stock,
)
from backend.tests.test_report_generator import FakeClient, make_report
from backend.tests.test_signal_builder import PRICE_DAYS, make_data
from backend.app.signals.signal_builder import build_stock_signals

TODAY = date(2026, 10, 1)
SETTINGS = Settings(_env_file=None, openai_api_key="sk-test", openai_model="gpt-4o")

METHOD_TO_FIELD = {
    "get_stock_info": "stock_info", "get_price": "prices", "get_dividend_result": "dividends",
    "get_split_price": "splits", "get_institutional_investors": "institutional", "get_margin_trading": "margin",
    "get_month_revenue": "revenue", "get_financial_statement": "financials",
    "get_valuation_ratios": "valuation", "get_news": "news",
}


class FakeFinMind:
    """依 StockRawData 欄位回傳測試資料；log 與 OpenAI 共用以驗證呼叫順序。"""

    def __init__(self, log, data=None, fail_on=None, error=None):
        self.log, self.data, self.fail_on, self.error = log, data or make_data(), fail_on, error

    def __getattr__(self, name):
        def method(*args):
            self.log.append(f"finmind.{name}")
            if name == self.fail_on:
                raise self.error
            return getattr(self.data, METHOD_TO_FIELD[name])
        return method


class LoggingOpenAI(FakeClient):
    def __init__(self, log, **kwargs):
        super().__init__(**kwargs)
        self.log = log

    def _parse(self, **kwargs):
        self.log.append("openai.parse")
        return super()._parse(**kwargs)


@pytest.fixture
def report():
    return make_report(build_stock_signals("2330", make_data()))


def run(log, report, **finmind_kwargs):
    return analyze_stock(
        "2330", today=TODAY, finmind_client=FakeFinMind(log, **finmind_kwargs),
        openai_client=LoggingOpenAI(log, parsed=report), settings=SETTINGS,
    )


# ---------------------------------------------------------------------------


def test_happy_path_flows_through_all_stages(report):
    log = []

    result = run(log, report)

    assert result.stock_id == "2330"
    assert result.analysis_date == PRICE_DAYS[-1].date()
    assert result.signals.profile.stock_name == "台積電"
    assert result.signals.technical is not None
    assert result.report.llm_status == "success"
    assert result.report.report == report
    assert result.generated_at is not None


def test_fetches_all_data_before_calling_llm_once(report):
    log = []

    run(log, report)

    assert log.count("openai.parse") == 1
    assert log[-1] == "openai.parse"
    assert set(f"finmind.{m}" for m in METHOD_TO_FIELD) <= set(log)


def test_analysis_date_is_latest_price_date_not_today(report):
    # 股價只到 09-30（例如盤中觸發，當天資料還沒出）
    data = make_data(prices=make_data().prices[lambda d: d["date"] <= "2026-09-30"])

    result = run([], report, data=data)

    assert result.analysis_date == date(2026, 9, 30)


def test_unknown_stock_raises_not_found(report):
    data = make_data(stock_info=pd.DataFrame(columns=fc._STOCK_INFO_COLUMNS),
                     prices=pd.DataFrame(columns=fc._PRICE_COLUMNS))

    with pytest.raises(StockNotFoundError):
        run([], report, data=data)


def test_known_stock_without_prices_raises_no_price_data(report):
    data = make_data(prices=pd.DataFrame(columns=fc._PRICE_COLUMNS))

    with pytest.raises(NoPriceDataError):
        run([], report, data=data)


def test_no_llm_call_when_analysis_cannot_proceed(report):
    log = []
    data = make_data(prices=pd.DataFrame(columns=fc._PRICE_COLUMNS))

    with pytest.raises(AnalysisError):
        run(log, report, data=data)

    assert "openai.parse" not in log


@pytest.mark.parametrize("error", [FinMindQuotaExceededError("402"), FinMindAuthError("Token is illegal")])
def test_finmind_errors_wrapped_with_original_cause(report, error):
    with pytest.raises(DataSourceError) as excinfo:
        run([], report, fail_on="get_margin_trading", error=error)

    assert excinfo.value.source_error is error


def test_llm_failure_does_not_raise_and_keeps_signals():
    log = []
    result = analyze_stock(
        "2330", today=TODAY, finmind_client=FakeFinMind(log),
        openai_client=LoggingOpenAI(log, error=RuntimeError("timeout")), settings=SETTINGS,
    )

    assert result.report.llm_status == "failed"
    assert result.signals.technical is not None


def test_insufficient_prices_still_produces_result(report):
    data = make_data(prices=make_data().prices.tail(30))

    result = run([], report, data=data)

    assert result.signals.technical is None
    assert "technical" in result.signals.unavailable
