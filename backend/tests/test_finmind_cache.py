from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.app.data_sources.cache import FinMindCache
from backend.app.data_sources.finmind_client import FinMindClient, FinMindQuotaExceededError

TODAY = datetime(2026, 10, 1, 15, 0)
RECENT = {"stock_id": "2330", "start_date": "2026-09-01", "end_date": "2026-10-01"}
HISTORICAL = {"stock_id": "2330", "start_date": "2026-01-01", "end_date": "2026-09-01"}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return Clock(TODAY)


@pytest.fixture
def cache(tmp_path, clock):
    return FinMindCache(tmp_path, ttl_seconds=3600, final_after_days=3, now=clock)


def sample_df():
    return pd.DataFrame([{"date": "2026-09-30", "stock_id": "2330", "close": 100.0}])


# ---------------------------------------------------------------------------
# FinMindCache 本身
# ---------------------------------------------------------------------------

def test_miss_returns_none(cache):
    assert cache.get("taiwan_stock_daily", RECENT) is None


def test_recent_range_hit_within_ttl(cache, clock):
    cache.set("taiwan_stock_daily", RECENT, sample_df())
    clock.now = TODAY + timedelta(minutes=59)

    df = cache.get("taiwan_stock_daily", RECENT)

    pd.testing.assert_frame_equal(df, sample_df())


def test_recent_range_expires_after_ttl(cache, clock):
    cache.set("taiwan_stock_daily", RECENT, sample_df())
    clock.now = TODAY + timedelta(minutes=61)

    assert cache.get("taiwan_stock_daily", RECENT) is None


def test_historical_range_never_expires(cache, clock):
    cache.set("taiwan_stock_daily", HISTORICAL, sample_df())
    clock.now = TODAY + timedelta(days=30)

    assert cache.get("taiwan_stock_daily", HISTORICAL) is not None


def test_range_end_exactly_at_final_cutoff_is_final(cache, clock):
    params = {"stock_id": "2330", "start_date": "2026-09-28"}  # 今天10/01 - 3天
    cache.set("taiwan_stock_news", params, sample_df())
    clock.now = TODAY + timedelta(days=1)

    assert cache.get("taiwan_stock_news", params) is not None


def test_range_end_one_day_after_cutoff_uses_ttl(cache, clock):
    params = {"stock_id": "2330", "start_date": "2026-09-29"}
    cache.set("taiwan_stock_news", params, sample_df())
    clock.now = TODAY + timedelta(hours=2)

    assert cache.get("taiwan_stock_news", params) is None


def test_different_params_or_dataset_are_separate_entries(cache):
    cache.set("taiwan_stock_daily", RECENT, sample_df())

    assert cache.get("taiwan_stock_daily", {**RECENT, "stock_id": "2454"}) is None
    assert cache.get("taiwan_stock_per_pbr", RECENT) is None


def test_empty_dataframe_is_cached(cache):
    cache.set("taiwan_stock_news", HISTORICAL, pd.DataFrame())

    df = cache.get("taiwan_stock_news", HISTORICAL)

    assert df is not None
    assert df.empty


def test_corrupted_file_is_treated_as_miss_and_removed(cache, tmp_path):
    cache.set("taiwan_stock_daily", HISTORICAL, sample_df())
    [path] = list(tmp_path.glob("*.pkl"))
    path.write_bytes(b"not a pickle")

    assert cache.get("taiwan_stock_daily", HISTORICAL) is None
    assert not path.exists()


def test_cache_dir_is_created(tmp_path, clock):
    target = tmp_path / "nested" / "cache"

    FinMindCache(target, now=clock)

    assert target.is_dir()


# ---------------------------------------------------------------------------
# 與 FinMindClient 整合
# ---------------------------------------------------------------------------

def make_counting_client(cache, **responses):
    """每個 dataset 回傳固定結果，並記錄實際呼叫底層SDK的參數。"""
    calls = []

    def make_fn(name, result):
        def fn(**kwargs):
            calls.append((name, kwargs))
            if isinstance(result, Exception):
                raise result
            return result(kwargs) if callable(result) else result
        return fn

    loader = SimpleNamespace(**{name: make_fn(name, result) for name, result in responses.items()})
    return FinMindClient(loader=loader, cache=cache), calls


def raw_price():
    return pd.DataFrame([{
        "date": "2026-09-30", "stock_id": "2330",
        "Trading_Volume": 1000, "Trading_money": 500000,
        "open": 100.0, "max": 105.0, "min": 99.0, "close": 104.0,
        "spread": 1.5, "Trading_turnover": 300,
    }])


def test_client_second_identical_call_hits_cache(cache):
    client, calls = make_counting_client(cache, taiwan_stock_daily=raw_price())

    first = client.get_price("2330", "2026-09-01", "2026-10-01")
    second = client.get_price("2330", "2026-09-01", "2026-10-01")

    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second)


def test_client_errors_are_not_cached(cache):
    client, calls = make_counting_client(
        cache, taiwan_stock_daily=Exception("Final response status: 402, text: limit"),
    )

    for _ in range(2):
        with pytest.raises(FinMindQuotaExceededError):
            client.get_price("2330", "2026-09-01", "2026-10-01")

    assert len(calls) == 2


def test_client_news_refetches_only_recent_days(cache, clock):
    def news(kwargs):
        return pd.DataFrame([{
            "date": kwargs["start_date"], "stock_id": "2330", "title": f"新聞{kwargs['start_date']}",
            "link": "https://example.com", "source": "cnyes",
        }])

    client, calls = make_counting_client(cache, taiwan_stock_news=news)
    client.get_news("2330", "2026-09-25", "2026-10-01")  # 7天，首次全抓
    assert len(calls) == 7

    calls.clear()
    clock.now = TODAY + timedelta(hours=2)  # 超過TTL
    df = client.get_news("2330", "2026-09-25", "2026-10-01")

    # 09-25~09-28 已定案（<= 今天-3天）從快取讀；09-29~10-01 過期重抓
    assert [kwargs["start_date"] for _, kwargs in calls] == ["2026-09-29", "2026-09-30", "2026-10-01"]
    assert len(df) == 7


def test_client_without_cache_always_calls_loader():
    client, calls = make_counting_client(None, taiwan_stock_daily=raw_price())

    client.get_price("2330", "2026-09-01", "2026-10-01")
    client.get_price("2330", "2026-09-01", "2026-10-01")

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 自動清理：建立快取時刪除超過 max_age_days 未更新的檔案
# ---------------------------------------------------------------------------

def set_file_age(path, clock, days):
    timestamp = (clock.now - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_init_removes_files_older_than_max_age(tmp_path, clock):
    cache = FinMindCache(tmp_path, now=clock)
    cache.set("taiwan_stock_daily", HISTORICAL, sample_df())
    cache.set("taiwan_stock_news", RECENT, sample_df())
    old_path, new_path = sorted(tmp_path.glob("*.pkl"), key=lambda p: "daily" not in p.name)
    set_file_age(old_path, clock, days=15)
    set_file_age(new_path, clock, days=13)

    FinMindCache(tmp_path, max_age_days=14, now=clock)

    assert not old_path.exists()
    assert new_path.exists()


def test_init_cleanup_ignores_non_cache_files(tmp_path, clock):
    keep = tmp_path / ".gitkeep"
    keep.write_text("")
    set_file_age(keep, clock, days=100)

    FinMindCache(tmp_path, max_age_days=14, now=clock)

    assert keep.exists()
