"""訊號層共用的數值計算。"""

from __future__ import annotations


def pct_change(base: float, current: float) -> float:
    """變化百分比。先相減再相除並四捨五入到小數10位，避免浮點誤差讓「剛好等於門檻」
    被判成超過（例如 1050 / 1000 − 1 = 0.05000000000000004）。base 需非 0。"""
    return round((current - base) / base * 100, 10)


def ratio_pct(numerator: float, denominator: float) -> float:
    """比率百分比（numerator ÷ denominator × 100），同樣四捨五入到小數10位。denominator 需非 0。"""
    return round(numerator * 100 / denominator, 10)
