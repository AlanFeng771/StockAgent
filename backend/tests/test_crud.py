from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.app.db import crud
from backend.app.db.crud import (
    InvalidStockIdError,
    WatchlistAlreadyExistsError,
    WatchlistNotFoundError,
)
from backend.app.db.database import create_db_engine, init_db, make_session_factory
from backend.app.db.models import Watchlist
from backend.app.llm.report_generator import ReportResult
from backend.app.pipeline.analyze_stock import AnalysisResult
from backend.app.signals.signal_builder import build_stock_signals
from backend.tests.test_report_generator import make_report
from backend.tests.test_signal_builder import make_data


@pytest.fixture
def session():
    engine = create_db_engine("sqlite://")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture(scope="module")
def signals():
    return build_stock_signals("2330", make_data())


def make_result(signals, analysis_date=date(2026, 10, 1), generated_at=None, status="success", stock_id="2330"):
    report = make_report(signals) if status == "success" else None
    return AnalysisResult(
        stock_id=stock_id, analysis_date=analysis_date,
        generated_at=generated_at or datetime(2026, 10, 1, 17, 0),
        signals=signals,
        report=ReportResult(
            llm_status=status, report=report, error=None if report else "未設定 OPENAI_API_KEY",
            warnings=["w1"], initial_warnings=["w0", "w1"], repair_attempts=1,
            model="gpt-4o", prompt_version="abc123def456", prompt_tokens=6000, completion_tokens=600,
        ),
    )


# ---------------------------------------------------------------------------
# 連線設定
# ---------------------------------------------------------------------------

def test_file_database_uses_wal_and_creates_folder(tmp_path):
    db_file = tmp_path / "nested" / "stock.db"
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    init_db(engine)

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    assert db_file.exists()


def test_in_memory_database_shared_across_sessions():
    engine = create_db_engine("sqlite://")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as s1:
        crud.add_watchlist(s1, "2330", "台積電")
    with factory() as s2:
        assert [w.stock_id for w in crud.get_active_watchlist(s2)] == ["2330"]


# ---------------------------------------------------------------------------
# 股票代號
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("2330", "2330"), (" 0056 ", "0056"), ("00981a", "00981A"), ("01001T", "01001T"), ("123456", "123456"),
])
def test_normalize_stock_id(raw, expected):
    assert crud.normalize_stock_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "233", "2330.TW", "台積電", "1234567", "2330; DROP TABLE", "AB12"])
def test_invalid_stock_id_rejected(raw):
    with pytest.raises(InvalidStockIdError):
        crud.normalize_stock_id(raw)


# ---------------------------------------------------------------------------
# 追蹤清單
# ---------------------------------------------------------------------------

def test_add_and_list_sorted(session):
    crud.add_watchlist(session, "2454", "聯發科")
    crud.add_watchlist(session, " 2330 ", "台積電")

    assert [(w.stock_id, w.stock_name) for w in crud.get_active_watchlist(session)] == [
        ("2330", "台積電"), ("2454", "聯發科"),
    ]


def test_add_duplicate_active_raises(session):
    crud.add_watchlist(session, "2330", "台積電")

    with pytest.raises(WatchlistAlreadyExistsError):
        crud.add_watchlist(session, "2330", "台積電")


def test_readd_removed_restores_same_row(session):
    original = crud.add_watchlist(session, "2330", "台積電")
    crud.remove_watchlist(session, "2330")

    restored = crud.add_watchlist(session, "2330", "台積電(新)")

    assert restored.id == original.id
    assert restored.is_active is True
    assert restored.stock_name == "台積電(新)"
    assert session.query(Watchlist).count() == 1


def test_remove_soft_deletes(session):
    crud.add_watchlist(session, "2330", "台積電")

    removed = crud.remove_watchlist(session, "2330")

    assert removed.is_active is False
    assert crud.get_active_watchlist(session) == []
    assert crud.get_watchlist_item(session, "2330") is None


@pytest.mark.parametrize("setup", ["never_added", "already_removed"])
def test_remove_missing_raises(session, setup):
    if setup == "already_removed":
        crud.add_watchlist(session, "2330", "台積電")
        crud.remove_watchlist(session, "2330")

    with pytest.raises(WatchlistNotFoundError):
        crud.remove_watchlist(session, "2330")


def test_watchlist_functions_validate_stock_id(session):
    with pytest.raises(InvalidStockIdError):
        crud.add_watchlist(session, "2330.TW", "x")


# ---------------------------------------------------------------------------
# 分析報告
# ---------------------------------------------------------------------------

def test_save_report_keeps_traceability_fields(session, signals):
    row = crud.save_report(session, make_result(signals))

    assert row.id is not None
    assert (row.model, row.prompt_version) == ("gpt-4o", "abc123def456")
    assert (row.warnings, row.initial_warnings, row.repair_attempts) == (["w1"], ["w0", "w1"], 1)
    assert (row.prompt_tokens, row.completion_tokens) == (6000, 600)
    assert crud.to_stock_report(row) == make_report(signals)
    assert crud.to_stock_signals(row) == signals


def test_failed_report_saved_without_report_json(session, signals):
    row = crud.save_report(session, make_result(signals, status="pending"))

    assert row.llm_status == "pending"
    assert row.report_json is None
    assert crud.to_stock_report(row) is None
    assert row.error == "未設定 OPENAI_API_KEY"


def test_reruns_are_all_kept_and_latest_returned(session, signals):
    first = crud.save_report(session, make_result(signals, generated_at=datetime(2026, 10, 1, 17, 0)))
    second = crud.save_report(session, make_result(signals, generated_at=datetime(2026, 10, 1, 20, 0)))

    assert crud.get_latest_report(session, "2330").id == second.id
    all_runs = crud.get_report_history(session, "2330", all_runs=True)
    assert [r.id for r in all_runs] == [second.id, first.id]


def test_latest_report_for_specific_date(session, signals):
    older = crud.save_report(session, make_result(signals, analysis_date=date(2026, 9, 30),
                                                  generated_at=datetime(2026, 9, 30, 17, 0)))
    crud.save_report(session, make_result(signals, analysis_date=date(2026, 10, 1),
                                          generated_at=datetime(2026, 10, 1, 17, 0)))

    assert crud.get_latest_report(session, "2330", date(2026, 9, 30)).id == older.id
    assert crud.get_latest_report(session, "2330", date(2026, 9, 1)) is None
    assert crud.get_latest_report(session, "9999") is None


def test_history_one_per_day_by_default_within_range(session, signals):
    base = datetime(2026, 9, 28, 17, 0)
    ids = {}
    for offset in range(4):
        day = date(2026, 9, 28) + timedelta(days=offset)
        crud.save_report(session, make_result(signals, analysis_date=day, generated_at=base + timedelta(days=offset)))
        ids[day] = crud.save_report(session, make_result(
            signals, analysis_date=day, generated_at=base + timedelta(days=offset, hours=2))).id

    history = crud.get_report_history(session, "2330", start=date(2026, 9, 29), end=date(2026, 9, 30))

    assert [(r.analysis_date, r.id) for r in history] == [
        (date(2026, 9, 30), ids[date(2026, 9, 30)]), (date(2026, 9, 29), ids[date(2026, 9, 29)]),
    ]


def test_latest_reports_for_active_watchlist_only(session, signals):
    crud.add_watchlist(session, "2330", "台積電")
    crud.add_watchlist(session, "2454", "聯發科")   # 沒有報告
    crud.add_watchlist(session, "0056", "元大高股息")
    crud.remove_watchlist(session, "0056")         # 已移除
    crud.save_report(session, make_result(signals, stock_id="2330"))
    crud.save_report(session, make_result(signals, stock_id="0056"))

    assert [r.stock_id for r in crud.get_latest_reports(session)] == ["2330"]


# ---------------------------------------------------------------------------
# 聊天紀錄
# ---------------------------------------------------------------------------

def test_chat_history_order_and_limit(session):
    for i in range(5):
        crud.add_chat_message(session, "s1", "user" if i % 2 == 0 else "assistant", f"m{i}", related_stock_id="2330")
    crud.add_chat_message(session, "s2", "user", "other session")

    history = crud.get_chat_history(session, "s1", limit=3)

    assert [m.content for m in history] == ["m2", "m3", "m4"]
    assert history[0].related_stock_id == "2330"
