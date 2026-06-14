"""Select alert-worthy news: only high-importance items with a clear, confident direction."""

from collections.abc import Sequence

from energy_etf_monitor.records import NewsArticle

_DIRECTIONAL = frozenset({"Bullish", "Bearish"})


def alert_worthy(
    articles: Sequence[NewsArticle],
    *,
    min_importance: float = 75.0,
    min_confidence: float = 0.5,
) -> list[NewsArticle]:
    return [
        article
        for article in articles
        if article.importance_score >= min_importance
        and article.confidence >= min_confidence
        and article.impact_direction in _DIRECTIONAL
    ]
