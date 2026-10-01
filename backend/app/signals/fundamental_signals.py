"""基本面訊號判斷（月營收、財報、估值）。

規格（Stage 2 spec）
====================

``detect_fundamental_signals(revenue, financials, valuation, signal_params=SIGNALS) -> FundamentalSignals | None``

輸入（皆不需事先排序）
----------------------
- ``revenue``：``get_month_revenue`` 的輸出。**營收所屬期間用 revenue_year / revenue_month**，
  不用 date：實測 date 是公布月份（date=2026-01-01 那筆是 2025 年 12 月營收）；
  create_time 實測有空值與事後補登，不使用。同一期間重複時取最後一筆
- ``financials``：``get_financial_statement`` 的輸出（long format，date = 季底日）。
  實測 EPS 為**單季**數值（含第四季，非全年累計）
- ``valuation``：``get_valuation_ratios`` 的輸出
三者皆空 → 回傳 None（ETF 如 0056 實測無財報與月營收）。各來源缺資料時，對應的
snapshot 為 None、不產生該來源的訊號。

輸出 ``FundamentalSignals``
---------------------------
- ``as_of_revenue``（營收所屬月份 1 日）/ ``as_of_financials``（季底日）/ ``as_of_valuation``
- ``snapshot``（算不出來時為 None）：
  - 月營收：``revenue``（元）、``revenue_yoy_pct``（對去年同月）、``revenue_mom_pct``（對上個月；
    上個月缺資料 → None）、``revenue_yoy_streak``（年增率連續為正的月數為正值、連續為負為負值；
    最新一期年增率為 0 或算不出 → 0）、``revenue_yoy_streak_capped``（1.0 = 連續區間一路延伸到
    資料最早可算年增率的月份，實際可能更長，訊號描述會標示「至少」；0.0 = 區間在資料範圍內結束）
  - 財報（最新一季）：``eps``、``eps_yoy_pct``（對去年同季；去年同季 EPS <= 0 時成長率無意義 → None）、
    ``ttm_eps``（最近 4 季加總；不足 4 個連續季度 → None）、``gross_margin_pct``（GrossProfit ÷ Revenue）、
    ``gross_margin_change_pp``（對去年同季，百分點）、``operating_margin_pct``（OperatingIncome ÷ Revenue）
  - 估值（最新一日）：``pe_ratio``、``pb_ratio``、``dividend_yield``、``pe_percentile``
    （近一年中**今天以外** PER > 0 的日子裡，PER 比今天低的比例 ×100；今天 PER <= 0、
    或今天以外的有效天數 < per_min_days → None）

訊號（門檻比較一律嚴格大於/小於）
--------------------------------
- ``revenue_yoy_growth``（bullish）：年增率 > revenue_yoy_high_pct
- ``revenue_yoy_decline``（bearish）：年增率 < revenue_yoy_low_pct
- ``revenue_growth_streak`` / ``revenue_decline_streak``：連續月數 >= revenue_streak_months；
  value = 月數，date = 連續區間第一個月，days_ago = 距最新一期的月數
- ``revenue_12m_high``（bullish）：最新月營收嚴格大於前 11 個月（需有連續 12 個月資料）
- ``eps_yoy_growth``（bullish）：單季 EPS 年增率 > eps_yoy_high_pct
- ``eps_negative``（bearish）：單季 EPS < 0
- ``gross_margin_up`` / ``gross_margin_down``：毛利率較去年同季變化 > / < ±gross_margin_change_pp
- ``pe_low``（bullish）/ ``pe_high``（bearish）：pe_percentile < per_low_percentile / > per_high_percentile
category 一律為 ``fundamental``；訊號依 (days_ago, name) 排序。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from pydantic import BaseModel

from backend.app.signals.calc import pct_change, ratio_pct
from backend.app.signals.config import SIGNALS, SignalParams
from backend.app.signals.models import Signal


class FundamentalSignals(BaseModel):
    stock_id: str
    as_of_revenue: date | None
    as_of_financials: date | None
    as_of_valuation: date | None
    snapshot: dict[str, float | None]
    signals: list[Signal]


def detect_fundamental_signals(
    revenue: pd.DataFrame,
    financials: pd.DataFrame,
    valuation: pd.DataFrame,
    signal_params: SignalParams = SIGNALS,
) -> FundamentalSignals | None:
    sources = [df for df in (revenue, financials, valuation) if not df.empty]
    if not sources:
        return None
    snapshot: dict[str, float | None] = {}
    signals: list[Signal] = []
    as_of_revenue = _revenue_part(revenue, signal_params, snapshot, signals)
    as_of_financials = _financials_part(financials, signal_params, snapshot, signals)
    as_of_valuation = _valuation_part(valuation, signal_params, snapshot, signals)
    signals.sort(key=lambda s: (s.days_ago, s.name))
    return FundamentalSignals(
        stock_id=str(sources[0]["stock_id"].iloc[0]),
        as_of_revenue=as_of_revenue, as_of_financials=as_of_financials, as_of_valuation=as_of_valuation,
        snapshot=snapshot, signals=signals,
    )


def _signal(name, bias, description, when, days_ago=0, value=None, threshold=None) -> Signal:
    return Signal(
        name=name, category="fundamental", bias=bias, description=description, date=when, days_ago=days_ago,
        value=None if value is None else float(value), threshold=None if threshold is None else float(threshold),
    )


def _month_start(period: pd.Period) -> date:
    return date(period.year, period.month, 1)


def _revenue_part(revenue, params, snapshot, signals) -> date | None:
    keys = ("revenue", "revenue_yoy_pct", "revenue_mom_pct", "revenue_yoy_streak", "revenue_yoy_streak_capped")
    if revenue.empty:
        snapshot.update(dict.fromkeys(keys))
        return None

    periods = [pd.Period(year=int(y), month=int(m), freq="M")
               for y, m in zip(revenue["revenue_year"], revenue["revenue_month"])]
    by_period = pd.Series(revenue["revenue"].astype(float).values, index=periods)
    by_period = by_period[~by_period.index.duplicated(keep="last")].sort_index()
    latest = by_period.index[-1]

    def change(period, months_back):
        base = period - months_back
        if base not in by_period.index or period not in by_period.index or not by_period[base]:
            return None
        return pct_change(by_period[base], by_period[period])

    yoy = change(latest, 12)
    streak, capped = 0, False
    if yoy:
        direction = 1 if yoy > 0 else -1
        period = latest
        while (value := change(period, 12)) is not None and value * direction > 0:
            streak += 1
            period -= 1
        capped = value is None  # 一路連續到資料最早可算的月份，實際可能更長
        streak *= direction

    snapshot["revenue"] = float(by_period[latest])
    snapshot["revenue_yoy_pct"] = yoy
    snapshot["revenue_mom_pct"] = change(latest, 1)
    snapshot["revenue_yoy_streak"] = float(streak)
    snapshot["revenue_yoy_streak_capped"] = 1.0 if capped else 0.0

    when = _month_start(latest)
    if yoy is not None and yoy > params.revenue_yoy_high_pct:
        signals.append(_signal("revenue_yoy_growth", "bullish", "月營收年增率高成長", when,
                               value=yoy, threshold=params.revenue_yoy_high_pct))
    elif yoy is not None and yoy < params.revenue_yoy_low_pct:
        signals.append(_signal("revenue_yoy_decline", "bearish", "月營收年增率明顯衰退", when,
                               value=yoy, threshold=params.revenue_yoy_low_pct))

    if abs(streak) >= params.revenue_streak_months:
        growing = streak > 0
        signals.append(_signal(
            "revenue_growth_streak" if growing else "revenue_decline_streak",
            "bullish" if growing else "bearish",
            f"月營收連續{'至少' if capped else ''} {abs(streak)} 個月年增{'成長' if growing else '衰退'}",
            _month_start(latest - (abs(streak) - 1)), days_ago=abs(streak) - 1,
            value=abs(streak), threshold=params.revenue_streak_months,
        ))

    previous_year = [latest - i for i in range(1, 12)]
    if all(p in by_period.index for p in previous_year) and by_period[latest] > by_period[previous_year].max():
        signals.append(_signal("revenue_12m_high", "bullish", "月營收創近 12 個月新高", when,
                               value=by_period[latest]))
    return when


def _financials_part(financials, params, snapshot, signals) -> date | None:
    keys = ("eps", "eps_yoy_pct", "ttm_eps", "gross_margin_pct", "gross_margin_change_pp", "operating_margin_pct")
    if financials.empty:
        snapshot.update(dict.fromkeys(keys))
        return None

    table = financials.pivot_table(index="date", columns="type", values="value", aggfunc="last").sort_index()
    latest = table.index[-1]
    last_year = pd.Timestamp(latest.year - 1, latest.month, latest.day)

    def get(quarter, column):
        if quarter not in table.index or column not in table.columns or pd.isna(table.at[quarter, column]):
            return None
        return float(table.at[quarter, column])

    def margin(quarter, column):
        numerator, revenue = get(quarter, column), get(quarter, "Revenue")
        return None if numerator is None or not revenue else ratio_pct(numerator, revenue)

    eps, eps_last_year = get(latest, "EPS"), get(last_year, "EPS")
    eps_yoy = pct_change(eps_last_year, eps) if eps is not None and eps_last_year and eps_last_year > 0 else None

    quarters = [pd.Period(q, freq="Q") for q in table.index]
    ttm_eps = None
    if len(quarters) >= 4 and quarters[-4:] == [quarters[-1] - i for i in (3, 2, 1, 0)]:
        recent_eps = [get(q, "EPS") for q in table.index[-4:]]
        if None not in recent_eps:
            ttm_eps = round(sum(recent_eps), 10)

    gross_margin, gross_margin_last_year = margin(latest, "GrossProfit"), margin(last_year, "GrossProfit")
    gross_change = (None if gross_margin is None or gross_margin_last_year is None
                    else round(gross_margin - gross_margin_last_year, 10))

    snapshot.update({
        "eps": eps, "eps_yoy_pct": eps_yoy, "ttm_eps": ttm_eps, "gross_margin_pct": gross_margin,
        "gross_margin_change_pp": gross_change, "operating_margin_pct": margin(latest, "OperatingIncome"),
    })

    when = latest.date()
    if eps_yoy is not None and eps_yoy > params.eps_yoy_high_pct:
        signals.append(_signal("eps_yoy_growth", "bullish", "單季 EPS 較去年同季高成長", when,
                               value=eps_yoy, threshold=params.eps_yoy_high_pct))
    if eps is not None and eps < 0:
        signals.append(_signal("eps_negative", "bearish", "單季 EPS 為負（虧損）", when, value=eps, threshold=0.0))
    if gross_change is not None and gross_change > params.gross_margin_change_pp:
        signals.append(_signal("gross_margin_up", "bullish", "單季毛利率較去年同季提升", when,
                               value=gross_change, threshold=params.gross_margin_change_pp))
    elif gross_change is not None and gross_change < -params.gross_margin_change_pp:
        signals.append(_signal("gross_margin_down", "bearish", "單季毛利率較去年同季下滑", when,
                               value=gross_change, threshold=-params.gross_margin_change_pp))
    return when


def _valuation_part(valuation, params, snapshot, signals) -> date | None:
    keys = ("pe_ratio", "pb_ratio", "dividend_yield", "pe_percentile")
    if valuation.empty:
        snapshot.update(dict.fromkeys(keys))
        return None

    valuation = valuation.sort_values("date").reset_index(drop=True)
    last = valuation.iloc[-1]
    as_of = pd.Timestamp(last["date"])
    pe = float(last["pe_ratio"])

    window = valuation.iloc[:-1]
    # pd.Timedelta 在 pandas 2.3.3 + numpy 2.5.3 會觸發 numpy 棄用警告（未來會變錯誤），改用標準函式庫
    window = window[(window["date"] > as_of - timedelta(days=365)) & (window["pe_ratio"] > 0)]
    percentile = None
    if pe > 0 and len(window) >= params.per_min_days:
        percentile = ratio_pct(int((window["pe_ratio"] < pe).sum()), len(window))

    snapshot.update({
        "pe_ratio": pe, "pb_ratio": float(last["pb_ratio"]),
        "dividend_yield": float(last["dividend_yield"]), "pe_percentile": percentile,
    })

    when = as_of.date()
    if percentile is not None and percentile < params.per_low_percentile:
        signals.append(_signal("pe_low", "bullish", "本益比處於近一年相對低檔", when,
                               value=percentile, threshold=params.per_low_percentile))
    elif percentile is not None and percentile > params.per_high_percentile:
        signals.append(_signal("pe_high", "bearish", "本益比處於近一年相對高檔", when,
                               value=percentile, threshold=params.per_high_percentile))
    return when
