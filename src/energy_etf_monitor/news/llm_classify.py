"""Optional LLM-backed news classifier (requires the `llm` extra + an Anthropic API key).

Implements the same ``NewsClassifier`` interface as the rule-based default and forces structured
output via a tool call. On any API/parse error it falls back to the deterministic rule-based
classifier, so the pipeline degrades safely rather than dropping articles.
"""

from typing import Any

from energy_etf_monitor.news.classify import classify_article
from energy_etf_monitor.records import NewsArticle

_VALID_DIRECTIONS = ("Bullish", "Bearish", "Neutral", "Mixed", "Unknown")

CLASSIFY_TOOL = {
    "name": "record_impact",
    "description": "Record the energy-futures impact classification of a news headline.",
    "input_schema": {
        "type": "object",
        "properties": {
            "commodity": {
                "type": "string",
                "description": "Primary affected commodity, e.g. WTI, BRENT, NATGAS, RBOB, "
                "HEATING_OIL, or ENERGY if unclear.",
            },
            "catalyst_type": {"type": "string"},
            "impact_direction": {"type": "string", "enum": list(_VALID_DIRECTIONS)},
            "spread_impact_direction": {"type": "string", "enum": list(_VALID_DIRECTIONS)},
            "importance_score": {"type": "number", "description": "0-100"},
            "confidence": {"type": "number", "description": "0-1"},
            "rationale": {"type": "string", "description": "One sentence."},
        },
        "required": ["commodity", "impact_direction", "importance_score", "confidence"],
    },
}

_SYSTEM = (
    "You classify the short-term impact of a news headline on energy futures. Score flat price and "
    "calendar-spread impact separately when they differ. Be conservative on importance and "
    "confidence. Always call the record_impact tool."
)


class LlmNewsClassifier:
    def __init__(self, *, api_key: str, model: str, client: Any | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

    def classify(self, article: NewsArticle) -> NewsArticle:
        try:
            client = self._ensure_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=512,
                system=_SYSTEM,
                tools=[CLASSIFY_TOOL],
                tool_choice={"type": "tool", "name": "record_impact"},
                messages=[{"role": "user", "content": _prompt(article)}],
            )
            payload = _extract_tool_input(response)
        except Exception:
            # Any API/parse failure degrades to the deterministic rule-based labels.
            return classify_article(article)
        return _apply(article, payload)

    def _ensure_client(self) -> Any:
        if self._client is None:  # pragma: no cover - exercised only with the real SDK installed
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client


def _prompt(article: NewsArticle) -> str:
    body = f"Headline: {article.title}"
    if article.summary:
        body += f"\nSummary: {article.summary}"
    return body


def _extract_tool_input(response: Any) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError("No tool_use block in LLM response")


def _apply(article: NewsArticle, payload: dict[str, Any]) -> NewsArticle:
    direction = payload.get("impact_direction", "Unknown")
    if direction not in _VALID_DIRECTIONS:
        direction = "Unknown"
    spread = payload.get("spread_impact_direction")
    if spread is not None and spread not in _VALID_DIRECTIONS:
        spread = None
    importance = _clamp(float(payload.get("importance_score", 0.0)), 0.0, 100.0)
    confidence = _clamp(float(payload.get("confidence", 0.0)), 0.0, 1.0)
    return article.model_copy(
        update={
            "commodity": payload.get("commodity") or article.commodity,
            "catalyst_type": payload.get("catalyst_type"),
            "impact_direction": direction,
            "spread_impact_direction": spread,
            "importance_score": importance,
            "confidence": confidence,
            "rationale": payload.get("rationale"),
        }
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
