"""Post high-impact news alerts to a Slack or ntfy webhook.

Best-effort: callers decide whether to swallow failures. Both transports take a full webhook URL
(`alert_webhook_url`); Slack expects a JSON `{text}` body, ntfy a plain-text body.
"""

from collections.abc import Sequence

import httpx

from energy_etf_monitor.records import NewsArticle


def format_alert_message(articles: Sequence[NewsArticle]) -> str:
    lines = ["High-impact energy news:"]
    for article in articles:
        commodity = article.commodity or "energy"
        lines.append(
            f"[{round(article.importance_score)}/{article.impact_direction}] "
            f"{commodity}: {article.title}"
        )
    return "\n".join(lines)


def post_news_alerts(
    articles: Sequence[NewsArticle],
    *,
    webhook_url: str | None,
    kind: str = "slack",
    client: httpx.Client | None = None,
) -> int:
    """Post the alerts to the webhook; return how many were sent (0 if nothing to do)."""

    if not articles or not webhook_url:
        return 0
    message = format_alert_message(articles)

    owned_client = client or httpx.Client(timeout=15)
    close_client = client is None
    try:
        if kind == "ntfy":
            response = owned_client.post(webhook_url, content=message.encode("utf-8"))
        else:
            response = owned_client.post(webhook_url, json={"text": message})
        response.raise_for_status()
    finally:
        if close_client:
            owned_client.close()
    return len(articles)
