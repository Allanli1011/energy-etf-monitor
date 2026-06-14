from datetime import UTC, datetime
from types import SimpleNamespace

from energy_etf_monitor.news.llm_classify import LlmNewsClassifier
from energy_etf_monitor.records import NewsArticle


def _article(title: str) -> NewsArticle:
    published = datetime(2026, 6, 12, 9, tzinfo=UTC)
    return NewsArticle(
        source="gdelt",
        report_date=published.date(),
        knowledge_date=published,
        published_at=published,
        url="https://a.com/x",
        url_hash="h",
        title=title,
    )


class _FakeMessages:
    def __init__(self, tool_input):
        self._tool_input = tool_input
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._tool_input is None:
            raise RuntimeError("api down")
        block = SimpleNamespace(type="tool_use", input=self._tool_input)
        return SimpleNamespace(content=[block])


class _FakeClient:
    def __init__(self, tool_input):
        self.messages = _FakeMessages(tool_input)


def test_llm_classifier_applies_tool_output() -> None:
    client = _FakeClient(
        {
            "commodity": "NATGAS",
            "catalyst_type": "weather",
            "impact_direction": "Bullish",
            "spread_impact_direction": "Neutral",
            "importance_score": 72,
            "confidence": 0.65,
            "rationale": "Cold snap lifts heating demand",
        }
    )
    classifier = LlmNewsClassifier(api_key="x", model="claude-haiku-4-5-20251001", client=client)

    result = classifier.classify(_article("Polar vortex to grip US Northeast"))

    assert result.commodity == "NATGAS"
    assert result.impact_direction == "Bullish"
    assert result.importance_score == 72
    assert result.confidence == 0.65
    # forced the tool
    assert client.messages.calls[0]["tool_choice"]["name"] == "record_impact"


def test_llm_classifier_clamps_out_of_range_and_sanitizes_direction() -> None:
    client = _FakeClient(
        {
            "commodity": "WTI",
            "impact_direction": "VeryBullish",
            "importance_score": 250,
            "confidence": 9,
        }
    )
    classifier = LlmNewsClassifier(api_key="x", model="m", client=client)

    result = classifier.classify(_article("Crude spikes"))

    assert result.impact_direction == "Unknown"
    assert result.importance_score == 100.0
    assert result.confidence == 1.0


def test_llm_classifier_falls_back_to_rules_on_api_error() -> None:
    client = _FakeClient(None)  # create() raises
    classifier = LlmNewsClassifier(api_key="x", model="m", client=client)

    result = classifier.classify(_article("OPEC+ agrees to deepen output cuts"))

    # rule-based fallback still produces a sensible label
    assert result.catalyst_type == "opec"
    assert result.impact_direction == "Bullish"
