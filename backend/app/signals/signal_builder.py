"""彙整技術/籌碼/基本面訊號與新聞，產出交給 LLM 的「事實清單」。

規格（Stage 2 spec）
====================

``build_stock_signals(stock_id, data, signal_params=SIGNALS) -> StockSignals``

``data`` 為 ``StockRawData``：各 ``FinMindClient`` method 的輸出原樣傳入（不需事先排序），
抓資料由上層（Stage 4 pipeline）負責，本函式不打 API。

流程
----
1. 股價 → ``adjust_prices``（除權息 + 面額變更）→ ``compute_technical`` → ``detect_technical_signals``
2. ``detect_chip_signals``（法人、融資，股價用還原後的資料）
3. ``detect_fundamental_signals``（月營收、財報、估值）
4. 股票基本資料：``resolve_stock_profile``（名稱、產業、市場、升降單位類別）
5. 支撐壓力與填息價：``build_price_levels``（需技術面算得出來；升降單位依 profile.kind，
   查無基本資料時用 ``other``＝不對齊）
6. 新聞：經 ``news_filter``（預設 ``RuleBasedNewsFilter``：排除論壇貼文、去掉結尾來源後去重、
   由新到舊）過濾後，最多 ``news_max_items`` 則。之後改用 LLM 過濾時傳入同介面的實作即可

輸出 ``StockSignals``
---------------------
- ``stock_id``
- ``data_freshness``：各來源最新資料日期，沒有資料為 None。鍵固定為
  price / institutional / margin / revenue（營收所屬月份 1 日）/ financials（季底日）/
  valuation / news。讓 LLM 與使用者知道每類資料新到哪一天
- ``profile``：股票基本資料；查無為 None
- ``technical`` / ``chip`` / ``fundamental`` / ``price_levels``：各面向結果；算不出來為 None
- ``unavailable``：{面向: 原因}，每個為 None 的面向都必須有原因，避免 LLM 自行腦補：
  - technical：「無股價資料」或「股價資料不足（N 筆，需 M 筆）」
  - chip：「無三大法人與融資融券資料」
  - fundamental：「無月營收、財報與估值資料（ETF 等標的屬正常）」
  - profile：「查無股票基本資料」
  - price_levels：與 technical 相同原因
- ``news``：``NewsItem``（date, title, source, link）清單

``StockSignals.model_dump_json()`` 必須是合法 JSON（NaN / inf 輸出為 null）。這是 Pydantic v2 的
預設行為（``ser_json_inf_nan="null"``），且設定只作用在該 model 本身、不會傳給巢狀 model，
所以不要在任何訊號 model 上改成 "constants"；由測試把關。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, ConfigDict

from backend.app.data_sources.stock_profile import StockProfile, resolve_stock_profile
from backend.app.indicators.price_adjust import adjust_prices
from backend.app.indicators.technical import compute_technical
from backend.app.signals.chip_signals import ChipSignals, detect_chip_signals
from backend.app.signals.config import SIGNALS, TECHNICAL, SignalParams
from backend.app.signals.fundamental_signals import FundamentalSignals, detect_fundamental_signals
from backend.app.signals.news_filter import NewsFilter, RuleBasedNewsFilter
from backend.app.signals.price_levels import PriceLevels, build_price_levels
from backend.app.signals.technical_signals import TechnicalSignals, detect_technical_signals

FRESHNESS_KEYS = ("price", "institutional", "margin", "revenue", "financials", "valuation", "news")


class StockRawData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    stock_info: pd.DataFrame
    prices: pd.DataFrame
    dividends: pd.DataFrame
    splits: pd.DataFrame
    institutional: pd.DataFrame
    margin: pd.DataFrame
    revenue: pd.DataFrame
    financials: pd.DataFrame
    valuation: pd.DataFrame
    news: pd.DataFrame


class NewsItem(BaseModel):
    date: date
    title: str
    source: str
    link: str


class StockSignals(BaseModel):
    stock_id: str
    profile: StockProfile | None
    data_freshness: dict[str, date | None]
    price_levels: PriceLevels | None
    technical: TechnicalSignals | None
    chip: ChipSignals | None
    fundamental: FundamentalSignals | None
    unavailable: dict[str, str]
    news: list[NewsItem]


def build_stock_signals(
    stock_id: str,
    data: StockRawData,
    signal_params: SignalParams = SIGNALS,
    news_filter: NewsFilter | None = None,
) -> StockSignals:
    unavailable: dict[str, str] = {}

    profile = resolve_stock_profile(data.stock_info, stock_id) if not data.stock_info.empty else None
    if profile is None:
        unavailable["profile"] = "查無股票基本資料"

    adjusted = adjust_prices(data.prices, data.dividends, data.splits)
    technical = price_levels = None
    if adjusted.empty:
        unavailable["technical"] = "無股價資料"
    else:
        indicators = compute_technical(adjusted)
        technical = detect_technical_signals(indicators, TECHNICAL, signal_params)
        if technical is None:
            unavailable["technical"] = (
                f"股價資料不足（{len(adjusted)} 筆，需 {TECHNICAL.required_price_rows()} 筆）"
            )
        else:
            kind = profile.kind if profile else "other"
            price_levels = build_price_levels(indicators, data.dividends, data.splits, kind, signal_params)
    if price_levels is None:
        unavailable["price_levels"] = unavailable["technical"]

    chip = detect_chip_signals(data.institutional, data.margin, adjusted, signal_params)
    if chip is None:
        unavailable["chip"] = "無三大法人與融資融券資料"

    fundamental = detect_fundamental_signals(data.revenue, data.financials, data.valuation, signal_params)
    if fundamental is None:
        unavailable["fundamental"] = "無月營收、財報與估值資料（ETF 等標的屬正常）"

    news_filter = news_filter or RuleBasedNewsFilter(signal_params.news_excluded_title_markers)
    news = _to_news_items(news_filter(data.news), signal_params.news_max_items)
    freshness = {
        "price": _latest_date(adjusted),
        "institutional": chip.as_of_institutional if chip else None,
        "margin": chip.as_of_margin if chip else None,
        "revenue": fundamental.as_of_revenue if fundamental else None,
        "financials": fundamental.as_of_financials if fundamental else None,
        "valuation": fundamental.as_of_valuation if fundamental else None,
        "news": news[0].date if news else None,
    }
    return StockSignals(
        stock_id=stock_id, profile=profile, data_freshness=freshness, price_levels=price_levels,
        technical=technical, chip=chip,
        fundamental=fundamental, unavailable=unavailable, news=news,
    )


def _latest_date(df: pd.DataFrame) -> date | None:
    return None if df.empty else pd.Timestamp(df["date"].max()).date()


def _to_news_items(news: pd.DataFrame, limit: int) -> list[NewsItem]:
    """news 已由 news_filter 依新到舊排序並去重。"""
    if news.empty:
        return []
    latest = news.head(limit)
    return [
        NewsItem(date=row.date.date(), title=row.title, source=row.source, link=row.link)
        for row in latest.itertuples(index=False)
    ]
