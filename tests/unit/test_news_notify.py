from datetime import UTC, datetime

import httpx
import pytest

from energy_etf_monitor.news.notify import format_alert_message, post_news_alerts
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
        commodity="WTI",
        impact_direction="Bullish",
        importance_score=85,
        confidence=0.7,
    )


def test_format_alert_message_lists_articles() -> None:
    message = format_alert_message([_article("OPEC cuts output")])
    assert "High-impact energy news:" in message
    assert "[85/Bullish] WTI: OPEC cuts output" in message


def test_post_news_alerts_slack_sends_json_text() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, text="ok")

    sent = post_news_alerts(
        [_article("OPEC cuts output")],
        webhook_url="https://hooks.slack.com/services/x",
        kind="slack",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert sent == 1
    assert "application/json" in captured["content_type"]
    assert "OPEC cuts output" in captured["body"]


def test_post_news_alerts_ntfy_sends_plain_body() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, text="ok")

    sent = post_news_alerts(
        [_article("Refinery outage")],
        webhook_url="https://ntfy.sh/my-energy-topic",
        kind="ntfy",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert sent == 1
    assert "Refinery outage" in captured["body"]


def test_post_news_alerts_noop_without_url_or_articles() -> None:
    assert post_news_alerts([], webhook_url="https://x", kind="slack") == 0
    assert post_news_alerts([_article("x")], webhook_url=None, kind="slack") == 0


def test_post_news_alerts_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unsupported webhook kind"):
        post_news_alerts([_article("x")], webhook_url="https://x", kind="discord")
