"""FinMind 資料擷取層。

規格（Stage 1 spec）
====================

``FinMindClient`` 封裝官方 ``FinMind.data.DataLoader``，把每個 dataset 包成一個
method，統一回傳欄位已正規化（snake_case、型別轉換）的 ``pandas.DataFrame``，
讓上層（indicators/signals）不需要認識 FinMind 原始欄位命名。

建構子
------
``FinMindClient(api_token: str | None = None, loader: DataLoader | None = None)``

- ``api_token``：FinMind API token；為 ``None`` 時以未登入（公開額度）呼叫。
- ``loader``：注入用的 ``DataLoader`` 實例，供測試以假物件替換；不帶時會自行建立
  ``DataLoader()`` 並在有 token 時呼叫 ``login_by_token``。

各 method 輸入輸出 contract
---------------------------
所有 method 的 ``start_date``/``end_date`` 皆為 ``"YYYY-MM-DD"`` 字串，對應
FinMind API 的日期格式。

- ``get_price(stock_id, start_date, end_date) -> DataFrame``
  欄位：date(datetime64), stock_id(str), open/high/low/close(float),
  volume(int), trading_money(int), turnover(int)
  （原始 FinMind 欄位 max/min/Trading_Volume/Trading_money/Trading_turnover
  重新命名為 high/low/volume/trading_money/turnover）

- ``get_institutional_investors(stock_id, start_date, end_date) -> DataFrame``
  欄位：date, stock_id, investor_type(str，對應原始「name」欄位，例如
  Foreign_Investor/Investment_Trust/Dealer_self), buy(int), sell(int),
  net(int，= buy - sell，為方便籌碼訊號層計算而新增的衍生欄位)

- ``get_margin_trading(stock_id, start_date, end_date) -> DataFrame``
  欄位：date, stock_id, margin_purchase_buy, margin_purchase_sell,
  margin_purchase_today_balance, margin_purchase_yesterday_balance,
  margin_purchase_cash_repayment, margin_purchase_limit, short_sale_buy,
  short_sale_sell, short_sale_today_balance, short_sale_yesterday_balance,
  short_sale_cash_repayment, short_sale_limit, offset_loan_and_short, note

- ``get_financial_statement(stock_id, start_date, end_date) -> DataFrame``
  欄位：date, stock_id, type(str，如"EPS"/"GrossProfit"), value(float),
  origin_name(str)（long format，一列一個財報科目，與FinMind原始格式相同）

- ``get_month_revenue(stock_id, start_date, end_date) -> DataFrame``
  欄位：date, stock_id, country, revenue(int), revenue_month(int),
  revenue_year(int), create_time(str)

- ``get_news(stock_id, start_date, end_date=None) -> DataFrame``
  欄位：date, stock_id, title, link, source
  （原本規格誤以為有description欄位，實際打真實API後確認FinMind
  taiwan_stock_news並無此欄位，已更正）
  **特殊限制**（實際打真實API才發現，與其他dataset不同）：FinMind的
  ``taiwan_stock_news`` 只接受單日查詢，一旦帶入非空的 ``end_date``
  就會回傳錯誤：「the dataset TaiwanStockNews size is too large, we only
  send one day data, so end_date parameter need be none.」。因此
  ``end_date`` 在本method是可選參數（預設 ``None``），對應底層SDK
  本身``end_date``預設空字串、可省略的行為：
    - 省略（``None``）：只查 ``start_date`` 當天單日新聞
    - 有帶值：視為日期範圍，內部逐日呼叫底層SDK（每次只傳
      ``start_date``、不傳 ``end_date``）再合併結果、依date排序後回傳，
      呼叫端不需感知這個底層限制。日期範圍越大，實際API呼叫次數越多，
      上層使用時應避免不必要地查過大範圍。

- ``get_valuation_ratios(stock_id, start_date, end_date) -> DataFrame``
  欄位：date, stock_id, pe_ratio(float，原始PER), pb_ratio(float，原始PBR),
  dividend_yield(float)

錯誤情境 contract（依官方SDK原始碼 ``FinMind/utility/request.py`` 與
``FinMind/data/finmind_api.py`` 的行為歸納，見程式內 ``_call`` 的docstring）
--------------------------------------------------------------------------
- 股票代號不存在、或日期範圍內沒有資料：FinMind API 回 HTTP 200、
  ``data`` 為空陣列，**不是錯誤**，method 回傳「只有欄位、零列」的空
  DataFrame（而不是完全沒有欄位的空DataFrame，確保呼叫端可以安全存取
  ``df["close"]`` 等欄位）。
- API 回應 HTTP 非200（例如 token 無效 401/403、額度超過 402）：SDK 底層
  會丟出內容為 ``f"Final response status: {code}, text: {text}"`` 的裸
  ``Exception``。本client攔截後依狀態碼轉成：
    - 402 → ``FinMindQuotaExceededError``
    - 401 或 403 → ``FinMindAuthError``
    - 其他 → ``FinMindAPIError``（catch-all）
- API 回 HTTP 200 但JSON沒有 ``data`` 欄位（格式異常）：SDK會丟出內容為
  ``f"FinMind API unexpected response: {msg}"`` 的裸 ``Exception``，本
  client一律轉成 ``FinMindAPIError``。
"""

from __future__ import annotations

import pandas as pd
from FinMind.data import DataLoader


class FinMindClientError(Exception):
    """所有 FinMindClient 例外的共同基底類別。"""


class FinMindAuthError(FinMindClientError):
    """API token 無效或未提供（HTTP 401/403）。"""


class FinMindQuotaExceededError(FinMindClientError):
    """API 呼叫額度已用盡（HTTP 402）。"""


class FinMindAPIError(FinMindClientError):
    """其他無法分類的 FinMind API 錯誤（catch-all）。"""


_PRICE_COLUMNS = [
    "date", "stock_id", "open", "high", "low", "close",
    "volume", "trading_money", "turnover",
]
_INSTITUTIONAL_INVESTORS_COLUMNS = [
    "date", "stock_id", "investor_type", "buy", "sell", "net",
]
_MARGIN_TRADING_COLUMNS = [
    "date", "stock_id", "margin_purchase_buy", "margin_purchase_sell",
    "margin_purchase_today_balance", "margin_purchase_yesterday_balance",
    "margin_purchase_cash_repayment", "margin_purchase_limit",
    "short_sale_buy", "short_sale_sell", "short_sale_today_balance",
    "short_sale_yesterday_balance", "short_sale_cash_repayment",
    "short_sale_limit", "offset_loan_and_short", "note",
]
_FINANCIAL_STATEMENT_COLUMNS = ["date", "stock_id", "type", "value", "origin_name"]
_MONTH_REVENUE_COLUMNS = [
    "date", "stock_id", "country", "revenue", "revenue_month",
    "revenue_year", "create_time",
]
_NEWS_COLUMNS = ["date", "stock_id", "title", "link", "source"]
_VALUATION_RATIOS_COLUMNS = ["date", "stock_id", "pe_ratio", "pb_ratio", "dividend_yield"]


class FinMindClient:
    def __init__(self, api_token: str | None = None, loader: DataLoader | None = None) -> None:
        self._loader = loader if loader is not None else DataLoader()
        if loader is None and api_token:
            self._loader.login_by_token(api_token)

    def _call(self, dataset_fn, columns: list[str], **kwargs) -> pd.DataFrame:
        """呼叫底層 FinMind SDK method，並把裸 Exception 轉成分類過的例外。

        SDK 對非200回應或缺少 "data" 欄位的異常回應，一律只會丟出訊息裡帶有
        狀態碼或錯誤說明的普通 ``Exception``（見 FinMind/utility/request.py
        的 ``request_get`` 與 FinMind/data/finmind_api.py 的 ``_extract_data``）
        ，本function依訊息內容重新分類成本模組定義的例外類別。
        """
        try:
            df = dataset_fn(**kwargs)
        except FinMindClientError:
            raise
        except Exception as exc:
            message = str(exc)
            if "402" in message:
                raise FinMindQuotaExceededError(message) from exc
            if "401" in message or "403" in message:
                raise FinMindAuthError(message) from exc
            raise FinMindAPIError(message) from exc

        if df is None or df.empty:
            return pd.DataFrame(columns=columns)
        return df

    def get_price(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._call(
            self._loader.taiwan_stock_daily,
            _PRICE_COLUMNS,
            stock_id=stock_id, start_date=start_date, end_date=end_date,
        )
        if df.empty:
            return df
        df = df.rename(columns={
            "max": "high",
            "min": "low",
            "Trading_Volume": "volume",
            "Trading_money": "trading_money",
            "Trading_turnover": "turnover",
        })
        df["date"] = pd.to_datetime(df["date"])
        return df[_PRICE_COLUMNS]

    def get_institutional_investors(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._call(
            self._loader.taiwan_stock_institutional_investors,
            _INSTITUTIONAL_INVESTORS_COLUMNS,
            stock_id=stock_id, start_date=start_date, end_date=end_date,
        )
        if df.empty:
            return df
        df = df.rename(columns={"name": "investor_type"})
        df["net"] = df["buy"] - df["sell"]
        df["date"] = pd.to_datetime(df["date"])
        return df[_INSTITUTIONAL_INVESTORS_COLUMNS]

    def get_margin_trading(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._call(
            self._loader.taiwan_stock_margin_purchase_short_sale,
            _MARGIN_TRADING_COLUMNS,
            stock_id=stock_id, start_date=start_date, end_date=end_date,
        )
        if df.empty:
            return df
        df = df.rename(columns={
            "MarginPurchaseBuy": "margin_purchase_buy",
            "MarginPurchaseSell": "margin_purchase_sell",
            "MarginPurchaseTodayBalance": "margin_purchase_today_balance",
            "MarginPurchaseYesterdayBalance": "margin_purchase_yesterday_balance",
            "MarginPurchaseCashRepayment": "margin_purchase_cash_repayment",
            "MarginPurchaseLimit": "margin_purchase_limit",
            "ShortSaleBuy": "short_sale_buy",
            "ShortSaleSell": "short_sale_sell",
            "ShortSaleTodayBalance": "short_sale_today_balance",
            "ShortSaleYesterdayBalance": "short_sale_yesterday_balance",
            "ShortSaleCashRepayment": "short_sale_cash_repayment",
            "ShortSaleLimit": "short_sale_limit",
            "OffsetLoanAndShort": "offset_loan_and_short",
            "Note": "note",
        })
        df["date"] = pd.to_datetime(df["date"])
        return df[_MARGIN_TRADING_COLUMNS]

    def get_financial_statement(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._call(
            self._loader.taiwan_stock_financial_statement,
            _FINANCIAL_STATEMENT_COLUMNS,
            stock_id=stock_id, start_date=start_date, end_date=end_date,
        )
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df[_FINANCIAL_STATEMENT_COLUMNS]

    def get_month_revenue(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._call(
            self._loader.taiwan_stock_month_revenue,
            _MONTH_REVENUE_COLUMNS,
            stock_id=stock_id, start_date=start_date, end_date=end_date,
        )
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df[_MONTH_REVENUE_COLUMNS]

    def get_news(self, stock_id: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        """對外維持日期範圍介面，內部逐日呼叫底層SDK並合併（見模組docstring）。

        ``end_date`` 為 ``None``（或省略）時僅查單日（等同 ``end_date=start_date``），
        對應底層 ``taiwan_stock_news`` 本身end_date就是可選、預設空字串的行為。
        """
        range_end = end_date or start_date
        frames = []
        for day in pd.date_range(start_date, range_end):
            day_str = day.strftime("%Y-%m-%d")
            df = self._call(
                self._loader.taiwan_stock_news,
                _NEWS_COLUMNS,
                stock_id=stock_id, start_date=day_str,
            )
            if not df.empty:
                frames.append(df)

        if not frames:
            return pd.DataFrame(columns=_NEWS_COLUMNS)
        df = pd.concat(frames, ignore_index=True)
        df["date"] = pd.to_datetime(df["date"])
        return df[_NEWS_COLUMNS].sort_values("date").reset_index(drop=True)

    def get_valuation_ratios(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._call(
            self._loader.taiwan_stock_per_pbr,
            _VALUATION_RATIOS_COLUMNS,
            stock_id=stock_id, start_date=start_date, end_date=end_date,
        )
        if df.empty:
            return df
        df = df.rename(columns={"PER": "pe_ratio", "PBR": "pb_ratio"})
        df["date"] = pd.to_datetime(df["date"])
        return df[_VALUATION_RATIOS_COLUMNS]
