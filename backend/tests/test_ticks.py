from __future__ import annotations

import pytest

from backend.app.signals.ticks import round_to_tick, tick_size


@pytest.mark.parametrize("price, expected", [
    (9.99, 0.01), (10.0, 0.05), (49.99, 0.05), (50.0, 0.1), (99.9, 0.1),
    (100.0, 0.5), (499.5, 0.5), (500.0, 1.0), (999.0, 1.0), (1000.0, 5.0), (2510.0, 5.0),
])
def test_stock_tick_bands_boundaries(price, expected):
    assert tick_size(price, "stock") == expected


@pytest.mark.parametrize("price, expected", [(49.99, 0.01), (50.0, 0.05), (56.85, 0.05)])
def test_fund_tick_bands(price, expected):
    assert tick_size(price, "fund") == expected


def test_other_kind_has_no_tick():
    assert tick_size(30.0, "other") is None


@pytest.mark.parametrize("price, kind, expected", [
    (2173.59, "stock", 2175.0),   # 2330 還原後的 60 日最低
    (2172.49, "stock", 2170.0),
    (2172.5, "stock", 2175.0),    # 剛好在中間：進位
    (53.4162, "fund", 53.40),     # 0056 06-23 還原後最高
    (53.43, "fund", 53.45),
    (48.6012, "fund", 48.60),
    (12.37, "stock", 12.35),
    (7.123, "stock", 7.12),
    (30.126, "other", 30.13),
])
def test_round_to_tick(price, kind, expected):
    assert round_to_tick(price, kind) == expected


def test_round_result_has_no_float_noise():
    # 0.1 級距的價位用浮點運算容易產生 53.300000000000004
    assert repr(round_to_tick(53.33, "stock")) == "53.3"


@pytest.mark.parametrize("price, kind, mode, expected", [
    (2173.59, "stock", "down", 2170.0),
    (2173.59, "stock", "up", 2175.0),
    (2175.0, "stock", "down", 2175.0),   # 本來就合法不變
    (2175.0, "stock", "up", 2175.0),
    (110.84, "stock", "down", 110.5),
    (110.84, "stock", "up", 111.0),
    (53.4162, "fund", "down", 53.40),
    (53.4162, "fund", "up", 53.45),
    (30.126, "other", "down", 30.12),
    (30.121, "other", "up", 30.13),
])
def test_round_to_tick_directional(price, kind, mode, expected):
    assert round_to_tick(price, kind, mode) == expected
