from __future__ import annotations

import pytest

from backend.tests.api_fixtures import api  # noqa: F401  (pytest fixture)


def test_health(api):
    response = api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_add_list_remove_flow(api):
    created = api.post("/api/watchlist", json={"stock_id": " 2454 "})
    api.post("/api/watchlist", json={"stock_id": "2330"})

    assert created.status_code == 201
    assert created.json()["stock_id"] == "2454"
    assert created.json()["stock_name"] == "聯發科"
    assert [i["stock_id"] for i in api.get("/api/watchlist").json()] == ["2330", "2454"]

    removed = api.delete("/api/watchlist/2454")
    assert removed.status_code == 200
    assert removed.json()["stock_id"] == "2454"
    assert [i["stock_id"] for i in api.get("/api/watchlist").json()] == ["2330"]


def test_add_duplicate_is_409(api):
    api.post("/api/watchlist", json={"stock_id": "2330"})

    response = api.post("/api/watchlist", json={"stock_id": "2330"})

    assert response.status_code == 409
    assert response.json()["error"] == "WatchlistAlreadyExistsError"


def test_readd_after_remove_is_allowed(api):
    api.post("/api/watchlist", json={"stock_id": "2330"})
    api.delete("/api/watchlist/2330")

    assert api.post("/api/watchlist", json={"stock_id": "2330"}).status_code == 201


@pytest.mark.parametrize("stock_id, status, error", [
    ("2330.TW", 422, "InvalidStockIdError"),
    ("8888", 404, "StockNotFoundError"),        # FinMind 查無此代號
    ("9998", 502, "FinMindQuotaExceededError"),  # FinMind 額度用完
])
def test_add_errors(api, stock_id, status, error):
    response = api.post("/api/watchlist", json={"stock_id": stock_id})

    assert response.status_code == status
    assert response.json()["error"] == error
    assert response.json()["detail"]


@pytest.mark.parametrize("stock_id, status", [("2330", 404), ("abc", 422)])
def test_remove_errors(api, stock_id, status):
    assert api.delete(f"/api/watchlist/{stock_id}").status_code == status
