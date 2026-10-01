"""API 測試共用：注入記憶體資料庫、假分析器、假股票查詢、同步背景執行。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.data_sources.finmind_client import FinMindQuotaExceededError
from backend.app.data_sources.stock_profile import StockProfile
from backend.app.db.database import create_db_engine, init_db, make_session_factory
from backend.app.main import create_app
from backend.app.pipeline.analyze_stock import DataSourceError, NoPriceDataError, StockNotFoundError
from backend.app.pipeline.jobs import AnalysisJobManager
from backend.app.signals.signal_builder import build_stock_signals
from backend.tests.test_crud import make_result
from backend.tests.test_signal_builder import make_data

TEST_SETTINGS = Settings(_env_file=None, api_allowed_hosts=["testserver", "127.0.0.1", "localhost"])
PROFILES = {
    "2330": StockProfile(stock_id="2330", stock_name="台積電", industries=["半導體業"], market="twse", kind="stock"),
    "2454": StockProfile(stock_id="2454", stock_name="聯發科", industries=["半導體業"], market="twse", kind="stock"),
    "0056": StockProfile(stock_id="0056", stock_name="元大高股息", industries=["ETF"], market="twse", kind="fund"),
}
SIGNALS = build_stock_signals("2330", make_data())


def fake_lookup(stock_id):
    if stock_id == "9998":
        raise FinMindQuotaExceededError("Final response status: 402")
    return PROFILES.get(stock_id)


class FakeAnalyzer:
    def __init__(self):
        self.calls = []

    def __call__(self, stock_id):
        self.calls.append(stock_id)
        if stock_id == "9999":
            raise StockNotFoundError("查無股票代號 9999")
        if stock_id == "1101":
            raise NoPriceDataError("1101 沒有股價資料")
        if stock_id == "9998":
            raise DataSourceError("FinMind 額度用完") from FinMindQuotaExceededError("402")
        return make_result(SIGNALS, stock_id=stock_id, generated_at=datetime.now(), analysis_date=date(2026, 10, 1))


def run_now(target):
    target()


def memory_session_factory():
    engine = create_db_engine("sqlite://")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def api():
    factory = memory_session_factory()
    analyzer = FakeAnalyzer()
    app = create_app(
        settings=TEST_SETTINGS, session_factory=factory, analyzer=analyzer, stock_lookup=fake_lookup,
        jobs=AnalysisJobManager(run_now),
    )
    client = TestClient(app)
    client.analyzer = analyzer
    client.session_factory = factory
    return client
