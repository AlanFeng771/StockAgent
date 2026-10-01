"""分析規則參數集中管理處。

與 ``backend/app/config.py``（執行環境設定，讀 .env）分開：這裡放的是影響
分析結論的參數，修改時需同步檢視 Stage 2 測試。

規格（Stage 2 spec）
====================

資料回溯期間（日曆天）
----------------------
除新聞外，FinMind 每個 dataset 不論查詢區間多長都只算 1 次 API 呼叫，所以
回溯期間可以放寬；新聞逐日呼叫，天數 = 呼叫次數。

- price：180 天（約 120 個交易日），涵蓋技術指標暖機需求（見 ``required_price_rows``）
  除權息、面額變更與股價使用同一區間（只需要股價區間內的事件）
- institutional / margin：60 天，連續買賣超等籌碼訊號用
- month_revenue：1130 天（約 37 個月），年增率需往回比 12 個月，連續成長月數最多可量到約 25 個月。
  原本 460 天（15 個月）只能量到 3 個月，實測 2330 實際連續 25 個月以上（2026-10-01 調整）
- financial_statement：900 天（約 2.5 年），近四季 EPS 合計的年增率需 8 季，
  加上財報公布延遲 45~90 天
- valuation：365 天，本益比在近一年中的相對位置
- news：7 天；必須 <= 快取自動清理天數（``Settings.cache_max_age_days``），
  否則仍在使用的新聞快取會被刪除重抓

技術指標參數（沿用台股業界慣例，2026-10-01 使用者確認不看年線 MA240）
--------------------------------------------------------------------
- 均線 MA5 / MA20 / MA60
- RSI 6 / 12（Wilder 平滑；2026-10-01 使用者確認與看盤App一致，原本設計的 RSI14 不用）
- KD 9,3,3（台股算法：K = 2/3 前K + 1/3 RSV，D = 2/3 前D + 1/3 K，初始 50）
- MACD 12 / 26 / 9
- 布林通道 20 日 ± 2 倍標準差
- 均量 5 / 20 日
- 指標一律以還原價計算（2026-10-01 使用者確認）。與看盤App（原始價）對照：用原始價
  重算時 2330 的 MA20/MA60/KD/RSI6/RSI12/MACD 與App一致，差異完全來自還原價。
  App 上標示「MACD」的數值對應本專案的 ``macd_signal``

訊號判斷參數
------------
- 爆量：當日成交量 > ``volume_surge_ratio`` × 20日均量（預設 2.0）
- 量縮：當日成交量 < ``volume_shrink_ratio`` × 20日均量（預設 0.5）
  兩者無統一業界標準，2026-10-01 使用者確認先用預設值、需可調整
  「20日均量」用**前一日**的 20 日均量（不含當天），避免當天爆量拉高均量而稀釋倍數
- 交叉訊號回看最近 ``cross_lookback_days`` 個交易日（預設 5，含最新交易日），
  每筆附發生日與 days_ago（2026-10-01 使用者確認）
- RSI 過熱/超賣：RSI6 80/20、RSI12 70/30（短週期波動大，門檻放寬；2026-10-01 使用者確認）
- KD 過熱/超賣：K 80/20

籌碼面（2026-10-01 使用者確認）
- 外資/投信連續買超或賣超 >= ``chip_streak_days``（預設 3）天產生訊號
- 法人買賣力道（外資＋投信近 ``chip_sum_days`` 日合計 ÷ 同期成交量）只當數值給 LLM，不設門檻
- 融資近 ``chip_sum_days`` 日增減 > ``margin_change_pct``（預設 5%）且股價反向 → 訊號
- 券資比 > ``short_margin_ratio_pct``（預設 30%）→ 訊號（neutral，交給 LLM）
- 自營商（含避險）只列數值不產生訊號：ETF 造市避險量大且不代表看法
  （實測 0056 2026-09-30 自營商避險賣超 1,574 萬股，同日外資買超 370 萬股）

基本面（2026-10-01 使用者確認；ROE 需資產負債表，MVP 先不做）
- 月營收年增率 > ``revenue_yoy_high_pct``（20%）偏多、< ``revenue_yoy_low_pct``（−10%）偏空
- 月營收年增率連續 ``revenue_streak_months``（3）個月為正 / 為負
- 月營收創近 12 個月新高；月增率只列數值（季節性大）
- 單季 EPS 年增率 > ``eps_yoy_high_pct``（20%）偏多；單季 EPS < 0 偏空
- 單季毛利率較去年同季增減 > ``gross_margin_change_pp``（2 個百分點）
- 本益比在近一年的百分位 < ``per_low_percentile``（20）偏多、> ``per_high_percentile``（80）偏空；
  有效天數 < ``per_min_days``（60）不判斷；殖利率只列數值

彙整（signal_builder）
- 新聞最多保留 ``news_max_items``（20）則最新標題給 LLM，控制 prompt 長度
- 支撐壓力取近 ``price_level_windows``（20、60）個交易日的最高/最低（2026-10-01 使用者確認）
- 標題含 ``news_excluded_title_markers`` 任一字串的新聞排除（預設論壇「股市爆料同學會」：
  實測 2330 七天 183 則中 93 則是論壇貼文，部分與公司無關）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LookbackDays:
    price: int = 180
    institutional: int = 60
    margin: int = 60
    month_revenue: int = 1130
    financial_statement: int = 900
    valuation: int = 365
    news: int = 7


@dataclass(frozen=True)
class TechnicalParams:
    ma_periods: tuple[int, ...] = (5, 20, 60)
    rsi_periods: tuple[int, ...] = (6, 12)
    kd_period: int = 9
    kd_smooth: int = 3  # K、D 的平滑係數 1/3
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    volume_ma_periods: tuple[int, ...] = (5, 20)

    # EMA 類指標（MACD、RSI 的 Wilder 平滑）需要暖機：初始值的權重經過 N 筆後
    # 剩 (1-α)^N。取 3 倍週期時，EMA26（α=2/27）的初始值權重約 0.25%，可忽略
    ema_warmup_multiplier: int = 3

    def required_price_rows(self) -> int:
        """所有技術指標都算得出穩定數值所需的最少交易日筆數（+1 供判斷「穿越」需要前一天）。"""
        return 1 + max(
            max(self.ma_periods),
            self.bollinger_period,
            max(self.volume_ma_periods),
            self.kd_period * self.ema_warmup_multiplier,
            max(self.rsi_periods) * self.ema_warmup_multiplier,
            self.macd_slow * self.ema_warmup_multiplier + self.macd_signal,
        )


@dataclass(frozen=True)
class SignalParams:
    volume_surge_ratio: float = 2.0
    volume_shrink_ratio: float = 0.5
    cross_lookback_days: int = 5
    # (RSI 週期, 過熱門檻, 超賣門檻)，週期需與 TechnicalParams.rsi_periods 一致
    rsi_thresholds: tuple[tuple[int, float, float], ...] = ((6, 80.0, 20.0), (12, 70.0, 30.0))
    kd_overbought: float = 80.0
    kd_oversold: float = 20.0
    chip_streak_days: int = 3
    chip_sum_days: int = 5
    margin_change_pct: float = 5.0
    short_margin_ratio_pct: float = 30.0
    revenue_yoy_high_pct: float = 20.0
    revenue_yoy_low_pct: float = -10.0
    revenue_streak_months: int = 3
    eps_yoy_high_pct: float = 20.0
    gross_margin_change_pp: float = 2.0
    per_low_percentile: float = 20.0
    per_high_percentile: float = 80.0
    per_min_days: int = 60
    news_max_items: int = 20
    price_level_windows: tuple[int, ...] = (20, 60)
    news_excluded_title_markers: tuple[str, ...] = ("股市爆料同學會",)


LOOKBACK = LookbackDays()
TECHNICAL = TechnicalParams()
SIGNALS = SignalParams()
