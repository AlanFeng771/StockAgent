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
- month_revenue：460 天（約 15 個月），年增率需往回比 12 個月，再加連續月數判斷
- financial_statement：900 天（約 2.5 年），近四季 EPS 合計的年增率需 8 季，
  加上財報公布延遲 45~90 天
- valuation：365 天，本益比在近一年中的相對位置
- news：7 天；必須 <= 快取自動清理天數（``Settings.cache_max_age_days``），
  否則仍在使用的新聞快取會被刪除重抓

技術指標參數（沿用台股業界慣例，2026-10-01 使用者確認不看年線 MA240）
--------------------------------------------------------------------
- 均線 MA5 / MA20 / MA60
- RSI 14（Wilder 平滑）
- KD 9,3,3（台股算法：K = 2/3 前K + 1/3 RSV，D = 2/3 前D + 1/3 K，初始 50）
- MACD 12 / 26 / 9
- 布林通道 20 日 ± 2 倍標準差
- 均量 5 / 20 日
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LookbackDays:
    price: int = 180
    institutional: int = 60
    margin: int = 60
    month_revenue: int = 460
    financial_statement: int = 900
    valuation: int = 365
    news: int = 7


@dataclass(frozen=True)
class TechnicalParams:
    ma_periods: tuple[int, ...] = (5, 20, 60)
    rsi_period: int = 14
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
            self.rsi_period * self.ema_warmup_multiplier,
            self.macd_slow * self.ema_warmup_multiplier + self.macd_signal,
        )


LOOKBACK = LookbackDays()
TECHNICAL = TechnicalParams()
