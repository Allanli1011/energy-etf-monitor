"""Rule-based news impact classifier (the free, deterministic default).

Labels each article with the affected commodity, catalyst type, price/spread impact direction,
an importance score, confidence, and a one-line rationale. This is intentionally a transparent
keyword model: an LLM-backed classifier can implement the same ``NewsClassifier`` interface later
without changing storage, dedup, or the dashboard.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from energy_etf_monitor.records import NewsArticle


def _matches(text: str, keyword: str) -> bool:
    # Anchor on a leading word boundary so "war" does not match inside "award" while still
    # catching inflections ("cut" -> "cuts", "draw" -> "drawdown") and "+" suffixes ("opec+").
    return re.search(r"\b" + re.escape(keyword), text) is not None

# Commodity detection runs most-specific first so "brent crude" maps to BRENT, not WTI.
_COMMODITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("BRENT", ("brent",)),
    ("NATGAS", ("natural gas", "nat gas", "henry hub", "lng")),
    ("RBOB", ("gasoline", "rbob", "pump price")),
    ("HEATING_OIL", ("heating oil", "diesel", "distillate", "gasoil")),
    ("WTI", ("wti", "crude", "oil", "cushing", "shale")),
)

_BULLISH_TERMS = (
    "cut", "cuts", "draw", "drawdown", "outage", "shutdown", "shuts", "disruption",
    "sanction", "embargo", "attack", "strike", "freeze", "shortage", "surge", "spike",
    "tighten", "halt", "blockade", "force majeure", "deepen", "below expectations",
)
_BEARISH_TERMS = (
    "build", "builds", "glut", "oversupply", "surplus", "boost output", "raise output",
    "raises output", "increase production", "ramp up", "weak demand", "demand slump",
    "slowdown", "plunge", "slump", "above expectations", "record production",
)


@dataclass(frozen=True)
class Catalyst:
    name: str
    keywords: tuple[str, ...]
    base_importance: float
    default_direction: str
    affects_spread: bool
    default_commodity: str = "WTI"


# Ordered by precedence: the first catalyst whose keyword appears wins.
_CATALYSTS: tuple[Catalyst, ...] = (
    Catalyst("geopolitics", ("war", "attack", "drone", "hormuz", "russia", "ukraine",
                             "iran", "middle east", "conflict", "missile"), 82, "Bullish", True),
    Catalyst("sanctions", ("sanction", "embargo", "import ban", "export ban"), 78, "Bullish", True),
    Catalyst("opec", ("opec", "opec+", "saudi", "output cut", "production cut", "quota"),
             80, "Bullish", True),
    Catalyst("refinery_outage", ("refinery", "outage", "shutdown", "fire", "maintenance"),
             66, "Bullish", False, default_commodity="RBOB"),
    Catalyst("inventory", ("inventory", "inventories", "stockpile", "stocks", "storage",
                           "eia report", "api report", "draw", "build"), 70, "Neutral", True),
    Catalyst("weather", ("hurricane", "storm", "cold snap", "freeze", "heat wave", "polar"),
             56, "Bullish", False),
    Catalyst("shipping", ("tanker", "strait", "canal", "suez", "blockade", "shipping"),
             60, "Bullish", False),
    Catalyst("demand", ("recession", "demand", "consumption", "growth"), 50, "Neutral", False),
    Catalyst("rates", ("fed", "rate hike", "rate cut", "interest rate", "inflation"),
             45, "Neutral", False),
    Catalyst("usd", ("dollar", "greenback", "currency"), 44, "Neutral", False),
)


class NewsClassifier(Protocol):
    def classify(self, article: NewsArticle) -> NewsArticle: ...


class RuleBasedClassifier:
    def classify(self, article: NewsArticle) -> NewsArticle:
        return classify_article(article)


def is_relevant(article: NewsArticle) -> bool:
    text = _text(article)
    return _detect_catalyst(text) is not None or _detect_commodity(text) is not None


def classify_article(article: NewsArticle) -> NewsArticle:
    text = _text(article)
    catalyst = _detect_catalyst(text)
    commodity = _detect_commodity(text) or (catalyst.default_commodity if catalyst else None)

    if catalyst is None and commodity is None:
        return article.model_copy(
            update={
                "importance_score": 0.0,
                "impact_direction": "Unknown",
                "confidence": 0.0,
                "rationale": "No energy catalyst detected",
            }
        )

    polarity = _detect_polarity(text)
    direction = polarity or (catalyst.default_direction if catalyst else "Neutral")
    base = catalyst.base_importance if catalyst else 40.0
    importance = min(100.0, base + (10.0 if polarity else 0.0))
    if catalyst is not None and polarity is not None:
        confidence = 0.6
    elif catalyst is not None:
        confidence = 0.45
    else:
        confidence = 0.3
    spread_direction = direction if (catalyst is not None and catalyst.affects_spread) else None
    catalyst_name = catalyst.name if catalyst else None
    rationale = _rationale(catalyst_name, direction, commodity)

    return article.model_copy(
        update={
            "commodity": commodity,
            "catalyst_type": catalyst_name,
            "impact_direction": direction,
            "spread_impact_direction": spread_direction,
            "importance_score": importance,
            "confidence": confidence,
            "rationale": rationale,
        }
    )


def _text(article: NewsArticle) -> str:
    return f"{article.title} {article.summary or ''}".lower()


def _detect_commodity(text: str) -> str | None:
    for name, keywords in _COMMODITY_KEYWORDS:
        if any(_matches(text, keyword) for keyword in keywords):
            return name
    return None


def _detect_catalyst(text: str) -> Catalyst | None:
    for catalyst in _CATALYSTS:
        if any(_matches(text, keyword) for keyword in catalyst.keywords):
            return catalyst
    return None


def _detect_polarity(text: str) -> str | None:
    bullish = any(_matches(text, term) for term in _BULLISH_TERMS)
    bearish = any(_matches(text, term) for term in _BEARISH_TERMS)
    if bullish and bearish:
        return "Mixed"
    if bullish:
        return "Bullish"
    if bearish:
        return "Bearish"
    return None


def _rationale(catalyst_name: str | None, direction: str, commodity: str | None) -> str:
    catalyst_label = (catalyst_name or "energy").replace("_", " ")
    return f"{catalyst_label} catalyst — {direction.lower()} for {commodity or 'energy'}"
