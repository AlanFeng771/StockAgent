"""訊號層共用資料結構（技術/籌碼/基本面共用，最後由 signal_builder 彙整給 LLM）。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

Bias = Literal["bullish", "bearish", "neutral"]


class Signal(BaseModel):
    """一個已觸發的訊號（事實），由規則引擎確定性產生。

    - ``name``：機器可讀代號，例如 ``kd_golden_cross``
    - ``category``：``trend`` / ``momentum`` / ``volume`` / ``volatility`` 等分類
    - ``bias``：業界慣用的解讀方向；沒有公認方向的（如爆量、突破布林上軌）為 neutral，
      交給 LLM 綜合判斷
    - ``description``：給人與 LLM 看的中文描述
    - ``date`` / ``days_ago``：訊號發生日與距最新交易日幾個交易日（0 = 最新交易日）
    - ``value`` / ``threshold``：觸發時的數值與門檻（沒有則為 None）
    """

    name: str
    category: str
    bias: Bias
    description: str
    date: date
    days_ago: int
    value: float | None = None
    threshold: float | None = None
