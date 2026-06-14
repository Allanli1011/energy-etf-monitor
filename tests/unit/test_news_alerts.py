from datetime import UTC, datetime

from energy_etf_monitor.news.alerts import alert_worthy
from energy_etf_monitor.records import NewsArticle


def _article(*, importance: float, confidence: float, direction: str, suffix: str) -> NewsArticle:
    published = datetime(2026, 6, 12, 9, tzinfo=UTC)
    return NewsArticle(
        source="gdelt",
        report_date=published.date(),
        knowledge_date=published,
        published_at=published,
        url=f"https://a.com/{suffix}",
        url_hash=f"hash-{suffix}",
        title=f"headline {suffix}",
        impact_direction=direction,
        importance_score=importance,
        confidence=confidence,
    )


def test_alert_worthy_requires_importance_confidence_and_clear_direction() -> None:
    articles = [
        _article(importance=85, confidence=0.6, direction="Bullish", suffix="keep"),
        _article(importance=85, confidence=0.6, direction="Neutral", suffix="neutral"),
        _article(importance=40, confidence=0.9, direction="Bearish", suffix="low-imp"),
        _article(importance=90, confidence=0.3, direction="Bearish", suffix="low-conf"),
        _article(importance=90, confidence=0.8, direction="Bearish", suffix="keep2"),
    ]

    alerts = alert_worthy(articles)

    assert {article.url_hash for article in alerts} == {"hash-keep", "hash-keep2"}
