"""LLM 分析報告的輸出格式（OpenAI Structured Outputs 依此 schema 強制格式）。

規格（Stage 3 spec，2026-10-01 使用者確認欄位：計畫原欄位＋目標價、停損價、建議持有多久）
================================================================================

Structured Outputs 的 strict 模式要求所有欄位都是必填，「可以沒有」用 ``X | None`` 表示，
因此本檔不使用預設值。所有價格（PricePoint.price）必須取自事實清單的價位
（price_levels 的 price / chart_price、現價 close、填息價 fill_price），由
``report_generator`` 事後驗證，不符者列入 warnings。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PricePoint(BaseModel):
    price: float = Field(description="價格，必須取自提供的價位清單")
    basis: str = Field(description="依據的價位來源，例如「MA20」「20日最低（2026-09-15）」「填息價」")
    condition: str = Field(description="執行條件，例如「回測不破分批買進」「跌破收盤確認」")


class Judgement(BaseModel):
    aspect: Literal["technical", "chip", "fundamental", "news", "price_levels"]
    point: str = Field(description="判斷依據，需能對應到事實清單中的訊號或數值")
    bias: Literal["bullish", "bearish", "neutral"]


class StockReport(BaseModel):
    summary: str = Field(description="一到兩句話的總結")
    overall_bias: Literal["bullish", "bearish", "neutral"]
    entry_points: list[PricePoint] = Field(description="買點；不建議進場時為空陣列")
    exit_points: list[PricePoint] = Field(description="賣點（獲利了結或減碼）；沒有合適價位時為空陣列")
    target_price: PricePoint | None = Field(description="目標價；上方沒有可用價位時為 null")
    stop_loss: PricePoint | None = Field(description="停損價；沒有合適價位時為 null")
    holding_period: Literal["short_term", "swing", "long_term", "not_recommended"] = Field(
        description="short_term=數日至2週、swing=數週至3個月、long_term=3個月以上、not_recommended=不建議持有"
    )
    holding_period_reason: str
    long_term_suitable: bool
    long_term_reason: str
    risks: list[str] = Field(description="主要風險，至少一項")
    rationale: list[Judgement] = Field(description="判斷依據")
    confidence: Literal["low", "medium", "high"]
    confidence_reason: str
    data_limitations: list[str] = Field(description="資料缺漏或日期落差對判斷的限制；沒有則為空陣列")
