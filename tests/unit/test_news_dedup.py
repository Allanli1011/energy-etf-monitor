from datetime import UTC, datetime

from energy_etf_monitor.news.dedup import (
    canonical_url,
    deduplicate_articles,
    title_fingerprint,
    url_hash,
)
from energy_etf_monitor.records import NewsArticle


def _article(*, url: str, title: str, published_hour: int, source: str = "gdelt") -> NewsArticle:
    published = datetime(2026, 6, 12, published_hour, tzinfo=UTC)
    return NewsArticle(
        source=source,
        report_date=published.date(),
        knowledge_date=published,
        published_at=published,
        url=url,
        url_hash=url_hash(url),
        title=title,
    )


def test_canonical_url_strips_scheme_www_query_and_trailing_slash() -> None:
    assert (
        canonical_url("https://www.Reuters.com/markets/oil/?utm_source=x")
        == "reuters.com/markets/oil"
    )
    assert canonical_url("http://reuters.com/markets/oil") == canonical_url(
        "https://www.reuters.com/markets/oil/"
    )


def test_url_hash_is_stable_across_equivalent_urls() -> None:
    assert url_hash("https://www.reuters.com/a/") == url_hash("http://reuters.com/a")


def test_title_fingerprint_normalizes_case_and_punctuation() -> None:
    assert title_fingerprint("OPEC+ cuts output!") == title_fingerprint("opec  cuts   output")


def test_deduplicate_collapses_same_url_and_keeps_earliest() -> None:
    articles = [
        _article(url="https://a.com/x", title="Crude jumps", published_hour=9),
        _article(url="https://www.a.com/x/", title="Crude jumps", published_hour=11),
    ]
    kept = deduplicate_articles(articles)
    assert len(kept) == 1
    assert kept[0].published_at.hour == 9


def test_deduplicate_collapses_syndicated_titles_within_window() -> None:
    articles = [
        _article(url="https://a.com/1", title="OPEC cuts output", published_hour=8, source="a"),
        _article(url="https://b.com/2", title="OPEC cuts output", published_hour=10, source="b"),
        # same headline but 2 days later -> a distinct event, must be kept
        NewsArticle(
            source="c",
            report_date=datetime(2026, 6, 14, 8, tzinfo=UTC).date(),
            knowledge_date=datetime(2026, 6, 14, 8, tzinfo=UTC),
            published_at=datetime(2026, 6, 14, 8, tzinfo=UTC),
            url="https://c.com/3",
            url_hash=url_hash("https://c.com/3"),
            title="OPEC cuts output",
        ),
    ]
    kept = deduplicate_articles(articles, title_window_hours=24)
    assert len(kept) == 2
    assert {article.source for article in kept} == {"a", "c"}
