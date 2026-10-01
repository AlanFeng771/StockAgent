from __future__ import annotations

from datetime import date, datetime

from backend.app.db import crud
from backend.tests.api_fixtures import SIGNALS, api  # noqa: F401
from backend.tests.test_crud import make_result


def save(api, stock_id="2330", analysis_date=date(2026, 10, 1), hour=17, status="success"):
    with api.session_factory() as session:
        return crud.save_report(session, make_result(
            SIGNALS, stock_id=stock_id, analysis_date=analysis_date, status=status,
            generated_at=datetime(analysis_date.year, analysis_date.month, analysis_date.day, hour),
        )).id


def test_latest_report_detail_includes_signals_and_traceability(api):
    save(api, hour=17)
    latest_id = save(api, hour=20)

    body = api.get("/api/reports/2330/latest").json()

    assert body["id"] == latest_id
    assert body["stock_name"] == "台積電"
    assert body["report"]["summary"]
    assert body["signals"]["price_levels"] is not None
    assert body["prompt_version"] == "abc123def456"
    assert body["warnings"] == ["w1"]


def test_latest_report_404_when_none(api):
    assert api.get("/api/reports/2330/latest").status_code == 404


def test_pending_report_has_null_report(api):
    save(api, status="pending")

    body = api.get("/api/reports/2330/latest").json()

    assert body["llm_status"] == "pending"
    assert body["report"] is None


def test_history_one_per_day_by_default_and_all_runs(api):
    save(api, analysis_date=date(2026, 9, 30), hour=17)
    save(api, analysis_date=date(2026, 10, 1), hour=17)
    save(api, analysis_date=date(2026, 10, 1), hour=20)

    default = api.get("/api/reports/2330/history").json()
    ranged = api.get("/api/reports/2330/history", params={"start": "2026-10-01", "end": "2026-10-01"}).json()
    all_runs = api.get("/api/reports/2330/history", params={"all_runs": True}).json()

    assert [r["analysis_date"] for r in default] == ["2026-10-01", "2026-09-30"]
    assert "signals" not in default[0]
    assert len(ranged) == 1
    assert len(all_runs) == 3


def test_latest_reports_for_watchlist(api):
    api.post("/api/watchlist", json={"stock_id": "2330"})
    api.post("/api/watchlist", json={"stock_id": "2454"})
    save(api, stock_id="2330")

    body = api.get("/api/reports/latest").json()

    assert [r["stock_id"] for r in body] == ["2330"]


def test_invalid_stock_id_is_422(api):
    assert api.get("/api/reports/2330.TW/latest").status_code == 422
