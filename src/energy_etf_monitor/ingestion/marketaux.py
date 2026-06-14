"""Marketaux news connector (optional; free tier needs an API key).

Normalizes Marketaux articles into unclassified NewsArticle records, same as the GDELT connector,
so they flow through the shared relevance -> dedup -> classify pipeline.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.news.dedup import canonical_url, url_hash
from energy_etf_monitor.records import NewsArticle

MARKETAUX_URL = "https://api.marketaux.com/v1/news/all"
DEFAULT_SEARCH = "oil OR crude OR OPEC OR gas OR gasoline OR energy"


class MarketauxConnector:
    source = "marketaux"

    def __init__(
        self,
        *,
        api_key: str,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.raw_store = raw_store
        self.client = client

    def fetch_articles(self, *, search: str = DEFAULT_SEARCH, limit: int = 50) -> list[NewsArticle]:
        fetched_at = datetime.now(UTC)
        params = {
            "api_token": self.api_key,
            "search": search,
            "language": "en",
            "limit": str(limit),
        }
        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(MARKETAUX_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        finally:
            if close_client:
                client.close()

        if self.raw_store:
            self.raw_store.save_json(
                source="news",
                payload=payload,
                fetched_at=fetched_at,
                label="marketaux",
            )
        return self.normalize_articles(payload=payload, fetched_at=fetched_at)

    @staticmethod
    def normalize_articles(*, payload: dict[str, Any], fetched_at: datetime) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for item in payload.get("data", []):
            url = item.get("url")
            title = item.get("title")
            published_raw = item.get("published_at")
            if not url or not title or not published_raw:
                continue
            published_at = _parse_iso(published_raw)
            articles.append(
                NewsArticle(
                    source=MarketauxConnector.source,
                    report_date=published_at.date(),
                    knowledge_date=fetched_at,
                    published_at=published_at,
                    url=url,
                    url_hash=url_hash(url),
                    title=title,
                    canonical_url=canonical_url(url),
                    summary=item.get("description"),
                )
            )
        return articles


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
