"""新聞過濾。

規格（Stage 2 補充 spec）
========================

``NewsFilter``：可替換的過濾介面，輸入/輸出皆為 ``get_news`` 格式的 DataFrame
（date, stock_id, title, link, source）。之後若改用 LLM 判斷相關性，實作同一介面
傳給 ``build_stock_signals(news_filter=...)`` 即可，不需改其他程式。

``RuleBasedNewsFilter(excluded_title_markers)``（預設實作）：
1. 排除標題含任一 marker 的新聞（預設論壇「股市爆料同學會」）
2. 標題結尾若是「 - {該列 source}」就去掉（同一篇被不同網站轉載時，只有結尾來源不同）。
   只去掉與該列 source 相同的結尾，避免誤刪標題本身含「 - 」的內容
3. 依 date 由新到舊排序，以清理後的標題去重，保留最新一則
輸出的 title 為清理後的標題。

註：原先討論的「只留標題含股票名稱或代號」實測無效——2330 七天 183 則全部符合
（FinMind 新聞本來就依代號查詢，論壇貼文也會自動加上「2330 台積電 -」前綴），故不採用。
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from backend.app.signals.config import SIGNALS


class NewsFilter(Protocol):
    def __call__(self, news: pd.DataFrame) -> pd.DataFrame: ...


class RuleBasedNewsFilter:
    def __init__(self, excluded_title_markers: tuple[str, ...] = SIGNALS.news_excluded_title_markers) -> None:
        self._markers = excluded_title_markers

    def __call__(self, news: pd.DataFrame) -> pd.DataFrame:
        if news.empty:
            return news.copy()
        kept = news[~news["title"].apply(lambda title: any(m in title for m in self._markers))]
        kept = kept.assign(
            date=pd.to_datetime(kept["date"]),
            title=[_strip_source(title, source) for title, source in zip(kept["title"], kept["source"])],
        )
        return (
            kept.sort_values("date", ascending=False, kind="stable")
            .drop_duplicates("title", keep="first")
            .reset_index(drop=True)
        )


def _strip_source(title: str, source: str) -> str:
    suffix = f" - {source}"
    return (title[: -len(suffix)] if source and title.endswith(suffix) else title).strip()
