"""台股申報價格升降單位（tick size）與價位對齊。

規格（Stage 2 補充 spec）
========================

``tick_size(price, kind) -> float | None`` / ``round_to_tick(price, kind, mode="nearest") -> float``

- kind = ``stock``：證交所營業細則第62條（查證版本 115.09.24）
  未滿10元 0.01、10~未滿50 0.05、50~未滿100 0.1、100~未滿500 0.5、500~未滿1000 1、1000以上 5。
  上櫃股票暫採同表（只查到櫃買中心興櫃股票買賣辦法同表，上櫃條文待查證）
- kind = ``fund``：證交所受益憑證買賣辦法第7條第2項（114.09.30）
  ETF、主動式ETF、REITs：未滿50元 0.01、50元以上 0.05
- kind = ``other``（存託憑證、ETN 等，規則未查證）：tick_size 回 None，
  round_to_tick 只四捨五入到小數 2 位、不做對齊
- 級距以「對齊前的價格」判斷；mode：``nearest`` 四捨五入（剛好在中間時進位）、``down`` 無條件捨去、
  ``up`` 無條件進位。支撐用 down、壓力用 up，確保對齊後不會跨過現價
  （實測：現價 110.85、支撐 110.84 四捨五入到 0.5 級距會變成 111.0，反而高於現價）
- 對齊前先四捨五入到小數 8 位，去除 560 × 0.1 = 56.00000000000001 這類浮點雜訊，
  否則 up 會錯誤進位到 56.1
- 計算用 Decimal，避免浮點誤差產生 2175.0000000001 這類非法價格
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

_STOCK_BANDS = ((10, "0.01"), (50, "0.05"), (100, "0.1"), (500, "0.5"), (1000, "1"), (float("inf"), "5"))
_FUND_BANDS = ((50, "0.01"), (float("inf"), "0.05"))


def tick_size(price: float, kind: str) -> float | None:
    tick = _tick_decimal(price, kind)
    return None if tick is None else float(tick)


_ROUNDING = {"nearest": ROUND_HALF_UP, "down": ROUND_FLOOR, "up": ROUND_CEILING}


def round_to_tick(price: float, kind: str, mode: str = "nearest") -> float:
    rounding = _ROUNDING[mode]
    value = Decimal(str(price)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    tick = _tick_decimal(price, kind)
    if tick is None:
        return float(value.quantize(Decimal("0.01"), rounding=rounding))
    steps = (value / tick).quantize(Decimal("1"), rounding=rounding)
    return float(steps * tick)


def _tick_decimal(price: float, kind: str) -> Decimal | None:
    bands = {"stock": _STOCK_BANDS, "fund": _FUND_BANDS}.get(kind)
    if bands is None:
        return None
    for upper, tick in bands:
        if price < upper:
            return Decimal(tick)
    raise AssertionError("unreachable")
