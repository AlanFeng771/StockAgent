"""FinMind 原始回應的本機檔案快取。

規格（Stage 1 cache spec）
==========================

目的：降低 FinMind API 呼叫次數（官方上限：註冊帶 token 600 次/小時）。
省下的呼叫主要來自兩處：
- 新聞逐日呼叫：已過去的日子從快取讀，不再重抓
- 同一查詢重跑（開發時反覆跑 analyze_one）：在有效期內全部從快取讀

``FinMindCache(cache_dir, ttl_seconds=3600, final_after_days=3, max_age_days=14, now=None)``

各參數的實際值由 ``backend/app/config.py`` 的 ``Settings`` 統一管理（``CACHE_*``），
這裡的預設值只供單獨使用/測試。

- ``cache_dir``：快取檔目錄（預設用 ``data/cache/``，已被 git 忽略），不存在會自動建立
- ``ttl_seconds``：「近期資料」的有效秒數，過期就重抓
- ``final_after_days``：查詢區間的結束日 <= 今天 - N 天，視為「已定案的歷史資料」，
  永久有效、不再重抓（FinMind 當天/隔天的資料可能尚未更新完整，所以留緩衝天數）
- ``max_age_days``：建立實例時自動刪除超過N天未更新（依檔案修改時間）的快取檔。
  大部分查詢的結束日每天不同，舊檔不會再被讀到，不清理會一直累積；
  誤刪的代價只是重抓一次。需 >= 新聞回溯天數，否則仍在用的新聞檔會被刪掉重抓
- ``now``：回傳目前時間的函式，供測試注入；預設 ``datetime.now``

快取鍵與有效期
--------------
- 鍵 = dataset 名稱（SDK method 名）+ 呼叫參數，同參數才算命中
- 區間結束日 = 參數中的 ``end_date``，沒有時用 ``start_date``（新聞單日查詢）
- 區間結束日 <= 今天 - ``final_after_days`` → 永久有效
- 否則 → 寫入後 ``ttl_seconds`` 內有效

行為 contract
-------------
- ``get(dataset, params) -> DataFrame | None``：命中且有效回傳 DataFrame，否則 None
- ``set(dataset, params, df)``：寫入。空 DataFrame 也要快取（假日沒有新聞是有效結果）
- 呼叫失敗（例外）不寫入快取，由呼叫端保證（只有成功取得結果才呼叫 ``set``）
- 快取檔損毀/無法讀取 → 視為未命中並刪除該檔，不丟例外
- 存的是 SDK 原始回應（欄位正規化前），正規化邏輯修改後不需清快取

儲存格式：pickle（保留 DataFrame 型別，免額外依賴）。pickle 讀取不受信任的檔案有
執行任意程式碼的風險，此目錄只存放本程式自己寫入的檔案，不要放入外來檔案。
"""

from __future__ import annotations

import hashlib
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd


class FinMindCache:
    def __init__(
        self,
        cache_dir: str | Path,
        ttl_seconds: int = 3600,
        final_after_days: int = 3,
        max_age_days: int = 14,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = timedelta(seconds=ttl_seconds)
        self._final_after_days = final_after_days
        self._now = now or datetime.now
        self._remove_older_than(timedelta(days=max_age_days))

    def get(self, dataset: str, params: dict) -> pd.DataFrame | None:
        path = self._path(dataset, params)
        if not path.exists():
            return None
        try:
            with path.open("rb") as f:
                fetched_at, df = pickle.load(f)
        except Exception:
            path.unlink(missing_ok=True)
            return None
        if self._is_final(params) or self._now() - fetched_at <= self._ttl:
            return df
        return None

    def set(self, dataset: str, params: dict, df: pd.DataFrame) -> None:
        with self._path(dataset, params).open("wb") as f:
            pickle.dump((self._now(), df), f)

    def _remove_older_than(self, max_age: timedelta) -> None:
        cutoff = (self._now() - max_age).timestamp()
        for path in self._dir.glob("*.pkl"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    def _is_final(self, params: dict) -> bool:
        range_end = params.get("end_date") or params.get("start_date")
        if not range_end:
            return False
        cutoff = self._now().date() - timedelta(days=self._final_after_days)
        return pd.Timestamp(range_end).date() <= cutoff

    def _path(self, dataset: str, params: dict) -> Path:
        key = json.dumps({"dataset": dataset, **params}, sort_keys=True)
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._dir / f"{dataset}_{digest}.pkl"
