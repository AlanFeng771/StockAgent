from __future__ import annotations

import pandas as pd

from backend.app.data_sources.stock_profile import resolve_stock_profile


def make_info(rows):
    df = pd.DataFrame(rows, columns=["stock_id", "stock_name", "industry_category", "market", "date"])
    df["date"] = pd.to_datetime(df["date"])
    return df


INFO = make_info([
    # 真實資料：同代號多個產業別、多個日期
    ("2330", "台積電", "半導體業", "twse", "2026-10-01"),
    ("2330", "台積電", "電子工業", "twse", "2026-10-01"),
    # 真實資料：舊列名稱前有空白、最新列名稱後有星號
    ("6763", " 綠界科技", "電子商務業", "tpex", "2023-06-29"),
    ("6763", "綠界科技*", "數位雲端類", "tpex", "2026-10-01"),
    ("0056", "元大高股息", "ETF", "twse", "2026-10-01"),
    ("006201", "元大富櫃50", "上櫃ETF", "tpex", "2026-10-01"),
    ("00679B", "元大美債20年", "上櫃指數股票型基金(ETF)", "tpex", "2026-10-01"),
    ("01001T", "土銀富邦R1", "受益證券", "twse", None),
    ("9105", "泰金寶-DR", "存託憑證", "twse", "2024-12-04"),
])


def test_unknown_stock_returns_none():
    assert resolve_stock_profile(INFO, "9999") is None


def test_multiple_industries_on_latest_date_are_merged():
    profile = resolve_stock_profile(INFO, "2330")

    assert profile.stock_name == "台積電"
    assert profile.industries == ["半導體業", "電子工業"]
    assert profile.market == "twse"
    assert profile.kind == "stock"


def test_uses_latest_rows_and_cleans_name():
    profile = resolve_stock_profile(INFO, "6763")

    assert profile.stock_name == "綠界科技"
    assert profile.industries == ["數位雲端類"]  # 舊日期的產業別不採用


def test_fund_kinds_cover_etf_variants_and_reits():
    for stock_id in ("0056", "006201", "00679B", "01001T"):
        assert resolve_stock_profile(INFO, stock_id).kind == "fund", stock_id


def test_rows_without_date_are_used_when_no_dated_rows():
    profile = resolve_stock_profile(INFO, "01001T")

    assert profile.stock_name == "土銀富邦R1"


def test_dated_rows_preferred_over_undated():
    info = make_info([
        ("1234", "舊名", "其他", "twse", None),
        ("1234", "新名", "其他", "twse", "2026-01-01"),
    ])

    assert resolve_stock_profile(info, "1234").stock_name == "新名"


def test_other_types_are_marked_other():
    assert resolve_stock_profile(INFO, "9105").kind == "other"
