from __future__ import annotations

from backend.app.config import Settings
from backend.app.signals.config import LOOKBACK, SIGNALS, TECHNICAL, TechnicalParams


def estimate_min_trading_days(calendar_days: int) -> int:
    """保守估計：週一到週五，再扣 15 天國定假日（春節連假可達一週以上）。"""
    return calendar_days * 5 // 7 - 15


def test_price_lookback_covers_technical_indicator_warmup():
    assert estimate_min_trading_days(LOOKBACK.price) >= TECHNICAL.required_price_rows()


def test_required_rows_tracks_parameter_changes():
    """改指標參數（例如加入 MA120）時，必要筆數要跟著變，讓上一條測試能擋住回溯不足。"""
    assert TechnicalParams(ma_periods=(5, 20, 120)).required_price_rows() >= 121


def test_required_rows_dominated_by_macd_warmup_with_defaults():
    # 3 × 26 + 9 + 1 = 88
    assert TECHNICAL.required_price_rows() == 88


def test_news_lookback_within_cache_retention():
    assert LOOKBACK.news <= Settings(_env_file=None).cache_max_age_days


def test_month_revenue_lookback_covers_yoy():
    # 年增率需要 12 個月前的同月資料，再加上至少 3 個月判斷趨勢
    assert LOOKBACK.month_revenue >= 15 * 30


def test_financial_statement_lookback_covers_eight_quarters_with_publication_lag():
    assert LOOKBACK.financial_statement >= 8 * 91 + 90


def test_rsi_periods_follow_taiwan_app_convention():
    # 2026-10-01 使用者確認：與看盤App一致，用 RSI6 / RSI12
    assert TECHNICAL.rsi_periods == (6, 12)


def test_volume_ratios_are_configurable_with_defaults():
    assert SIGNALS.volume_surge_ratio == 2.0
    assert SIGNALS.volume_shrink_ratio == 0.5
    assert SIGNALS.volume_shrink_ratio < 1 < SIGNALS.volume_surge_ratio
