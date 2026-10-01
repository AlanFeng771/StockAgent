from __future__ import annotations

import pandas as pd

from backend.app.signals.news_filter import RuleBasedNewsFilter


def make_news(rows):
    """rows: [(date, title, source)]"""
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "stock_id": "2330", "title": t, "link": f"https://x/{i}", "source": s}
         for i, (d, t, s) in enumerate(rows)],
        columns=["date", "stock_id", "title", "link", "source"],
    )


def test_excludes_forum_posts_by_title_marker():
    news = make_news([
        ("2026-10-01", "2330 台積電 - 高雄仁武綠廊一次啟用3座公園- 股市爆料同學會 - CMoney", "CMoney"),
        ("2026-10-01", "台積電收2510元追平天花板價 - Yahoo股市", "Yahoo股市"),
    ])

    result = RuleBasedNewsFilter()(news)

    assert list(result["title"]) == ["台積電收2510元追平天花板價"]


def test_strips_trailing_source_and_dedupes_reposts_keeping_newest():
    news = make_news([
        ("2026-09-30", "台積電法說會釋利多 - cmoney.tw", "cmoney.tw"),
        ("2026-10-01", "台積電法說會釋利多 - CMoney", "CMoney"),
        ("2026-09-29", "其他新聞 - 自由財經", "自由財經"),
    ])

    result = RuleBasedNewsFilter()(news)

    assert list(result["title"]) == ["台積電法說會釋利多", "其他新聞"]
    assert result.iloc[0]["source"] == "CMoney"


def test_only_strips_suffix_matching_own_source():
    news = make_news([("2026-10-01", "外資：AI需求強 - 摩根士丹利", "Yahoo股市")])

    result = RuleBasedNewsFilter()(news)

    assert result.iloc[0]["title"] == "外資：AI需求強 - 摩根士丹利"


def test_markers_are_configurable():
    news = make_news([
        ("2026-10-01", "某論壇貼文 - 股市爆料同學會 - CMoney", "CMoney"),
        ("2026-10-01", "業配文 - 理財網", "理財網"),
    ])

    result = RuleBasedNewsFilter(excluded_title_markers=("業配",))(news)

    assert list(result["title"]) == ["某論壇貼文 - 股市爆料同學會"]


def test_empty_news_returns_empty_with_columns():
    result = RuleBasedNewsFilter()(make_news([]))

    assert result.empty
    assert list(result.columns) == ["date", "stock_id", "title", "link", "source"]


def test_does_not_mutate_input():
    news = make_news([("2026-10-01", "新聞 - Yahoo股市", "Yahoo股市")])
    snapshot = news.copy()

    RuleBasedNewsFilter()(news)

    pd.testing.assert_frame_equal(news, snapshot)
