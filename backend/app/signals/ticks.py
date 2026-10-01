"""台股申報價格升降單位（tick size）與價位對齊。

規格（Stage 2 補充 spec）
========================

``tick_size(price, kind) -> float | None`` / ``round_to_tick(price, kind) -> float``

- kind = ``stock``：證交所營業細則第62條（查證版本 115.09.24）
  未滿10元 0.01、10~未滿50 0.05、50~未滿100 0.1、100~未滿500 0.5、500~未滿1000 1、1000以上 5。
  上櫃股票暫採同表（只查到櫃買中心興櫃股票買賣辦法同表，上櫃條文待查證）
- kind = ``fund``：證交所受益憑證買賣辦法第7條第2項（114.09.30）
  ETF、主動式ETF、REITs：未滿50元 0.01、50元以上 0.05
- kind = ``other``（存託憑證、ETN 等，規則未查證）：tick_size 回 None，
  round_to_tick 只四捨五入到小數 2 位、不做對齊
- 級距以「對齊前的價格」判斷；對齊方式為四捨五入到最近的合法價格（剛好在中間時進位）
- 計算用 Decimal，避免浮點誤差產生 2175.0000000001 這類非法價格
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_STOCK_BANDS = ((10, "0.01"), (50, "0.05"), (100, "0.1"), (500, "0.5"), (1000, "1"), (float("inf"), "5"))
_FUND_BANDS = ((50, "0.01"), (float("inf"), "0.05"))


def tick_size(price: float, kind: str) -> float | None:
    tick = _tick_decimal(price, kind)
    return None if tick is None else float(tick)


def round_to_tick(price: float, kind: str) -> float:
    value = Decimal(str(price))
    tick = _tick_decimal(price, kind)
    if tick is None:
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    steps = (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(steps * tick)


def _tick_decimal(price: float, kind: str) -> Decimal | None:
    bands = {"stock": _STOCK_BANDS, "fund": _FUND_BANDS}.get(kind)
    if bands is None:
        return None
    for upper, tick in bands:
        if price < upper:
            return Decimal(tick)
    raise AssertionError("unreachable")
