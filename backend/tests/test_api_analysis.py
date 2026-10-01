from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.pipeline.jobs import AnalysisJobManager
from backend.tests.api_fixtures import TEST_SETTINGS, api, memory_session_factory  # noqa: F401


def test_run_single_saves_and_returns_report(api):
    response = api.post("/api/analysis/run/2330", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["stock_id"] == "2330"
    assert body["signals"] is not None
    assert api.get("/api/reports/2330/latest").json()["id"] == body["id"]


@pytest.mark.parametrize("stock_id, status, error", [
    ("9999", 404, "StockNotFoundError"),
    ("1101", 422, "NoPriceDataError"),
    ("9998", 502, "DataSourceError"),
    ("abc", 422, "InvalidStockIdError"),
])
def test_run_single_errors(api, stock_id, status, error):
    response = api.post(f"/api/analysis/run/{stock_id}", json={})

    assert response.status_code == status
    assert response.json()["error"] == error


def test_run_watchlist_in_background_and_status(api):
    for stock_id in ("2330", "2454"):
        api.post("/api/watchlist", json={"stock_id": stock_id})

    started = api.post("/api/analysis/run", json={})
    status = api.get("/api/analysis/status").json()

    assert started.status_code == 202
    assert api.analyzer.calls == ["2330", "2454"]
    assert status["state"] == "done"
    assert status["succeeded"] == ["2330", "2454"]
    assert [r["stock_id"] for r in api.get("/api/reports/latest").json()] == ["2330", "2454"]


def test_status_idle_before_any_run(api):
    assert api.get("/api/analysis/status").json()["state"] == "idle"


def test_busy_returns_409():
    deferred = []  # 背景工作先不執行，模擬「執行中」
    app = create_app(
        settings=TEST_SETTINGS, session_factory=memory_session_factory(),
        analyzer=lambda s: None, stock_lookup=lambda s: None, jobs=AnalysisJobManager(deferred.append),
    )
    client = TestClient(app)

    assert client.post("/api/analysis/run", json={}).status_code == 202
    busy = client.post("/api/analysis/run", json={})
    single = client.post("/api/analysis/run/2330", json={})

    assert busy.status_code == 409 and busy.json()["error"] == "AnalysisBusyError"
    assert single.status_code == 409


# ---------------------------------------------------------------------------
# 安全性
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/analysis/run", "/api/analysis/run/2330", "/api/watchlist"])
def test_post_without_json_content_type_is_415(api, path):
    # 模擬惡意網頁的跨站「簡單請求」：表單或 text/plain
    form = api.post(path, data={"stock_id": "2330"})
    plain = api.post(path, content="{}", headers={"Content-Type": "text/plain"})

    assert form.status_code == 415
    assert plain.status_code == 415
    assert api.analyzer.calls == []


def test_untrusted_host_rejected():
    app = create_app(settings=Settings(_env_file=None), session_factory=memory_session_factory(),
                     analyzer=lambda s: None, stock_lookup=lambda s: None)
    client = TestClient(app, base_url="http://evil.example.com")

    assert client.get("/api/health").status_code == 400


def test_no_cors_headers(api):
    response = api.options("/api/watchlist", headers={
        "Origin": "http://evil.example.com", "Access-Control-Request-Method": "POST",
    })

    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_importing_main_does_not_create_database(tmp_path, monkeypatch):
    db_file = tmp_path / "should_not_exist.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    import backend.app.config as config
    config.get_settings.cache_clear()
    try:
        import backend.app.main as main
        assert importlib.reload(main).app is not None
        assert not db_file.exists()
    finally:
        config.get_settings.cache_clear()


@pytest.mark.parametrize("path", ["/api/analysis/run", "/api/analysis/run/{stock_id}", "/api/watchlist"])
def test_post_endpoints_declare_json_body_for_swagger(api, path):
    # 沒宣告 request body 時，/docs（Swagger UI）不會送 Content-Type: application/json，會被 415 擋下
    operation = api.get("/openapi.json").json()["paths"][path]["post"]

    assert "application/json" in operation["requestBody"]["content"]
