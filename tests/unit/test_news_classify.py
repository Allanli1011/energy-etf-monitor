from datetime import UTC, datetime

from energy_etf_monitor.news.classify import RuleBasedClassifier, classify_article, is_relevant
from energy_etf_monitor.records import NewsArticle


def _article(title: str) -> NewsArticle:
    published = datetime(2026, 6, 12, 12, tzinfo=UTC)
    return NewsArticle(
        source="gdelt",
        report_date=published.date(),
        knowledge_date=published,
        published_at=published,
        url="https://example.com/a",
        url_hash="hash",
        title=title,
    )


def test_inventory_surprise_draw_is_bullish_with_spread_impact() -> None:
    result = classify_article(
        _article("US crude oil inventories post surprise 5 million barrel draw")
    )
    assert result.commodity == "WTI"
    assert result.catalyst_type == "inventory"
    assert result.impact_direction == "Bullish"
    assert result.spread_impact_direction == "Bullish"
    assert result.importance_score >= 70
    assert result.confidence >= 0.5


def test_inventory_build_is_bearish() -> None:
    result = classify_article(
        _article("EIA reports surprise crude inventory build of 4 million barrels")
    )
    assert result.catalyst_type == "inventory"
    assert result.impact_direction == "Bearish"


def test_opec_output_cut_is_bullish() -> None:
    result = classify_article(_article("OPEC+ agrees to deepen output cuts through 2027"))
    assert result.catalyst_type == "opec"
    assert result.impact_direction == "Bullish"
    assert result.spread_impact_direction == "Bullish"


def test_refinery_outage_is_bullish_for_products() -> None:
    result = classify_article(_article("Gulf Coast refinery outage shuts 250,000 bpd of gasoline"))
    assert result.catalyst_type == "refinery_outage"
    assert result.commodity == "RBOB"
    assert result.impact_direction == "Bullish"
    # refinery outages are a flat-price/product story, not a clean curve signal
    assert result.spread_impact_direction is None


def test_geopolitical_disruption_is_high_importance_bullish() -> None:
    result = classify_article(_article("Drone attack on oil tanker in Strait of Hormuz"))
    assert result.catalyst_type == "geopolitics"
    assert result.impact_direction == "Bullish"
    assert result.importance_score >= 80


def test_natural_gas_is_detected() -> None:
    result = classify_article(_article("Cold snap drives natural gas demand to record high"))
    assert result.commodity == "NATGAS"


def test_irrelevant_article_is_marked_unknown() -> None:
    article = _article("Local bakery wins small business award")
    assert is_relevant(article) is False
    result = classify_article(article)
    assert result.impact_direction == "Unknown"
    assert result.importance_score == 0.0


def test_rule_based_classifier_matches_function() -> None:
    article = _article("OPEC+ output cut")
    assert RuleBasedClassifier().classify(article).impact_direction == classify_article(
        article
    ).impact_direction
