"""GDELT 2.0 DOC API connector (free, no API key).

Fetches recent energy news as an article list and normalizes it into unclassified NewsArticle
records (classification happens downstream). Raw payloads are saved before parsing for replay.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.news.dedup import canonical_url, url_hash
from energy_etf_monitor.records import NewsArticle

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_QUERY = (
    '(crude OR "natural gas" OR OPEC OR gasoline OR "heating oil" OR brent OR WTI)'
)


class GdeltDocConnector:
    source = "gdelt"

    def __init__(
        self,
        *,
        query: str = DEFAULT_QUERY,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.query = query
        self.raw_store = raw_store
        self.client = client

    def fetch_articles(self, *, timespan: str = "1d", max_records: int = 75) -> list[NewsArticle]:
        fetched_at = datetime.now(UTC)
        params = {
            "query": self.query,
            "mode": "ArtList",
            "format": "json",
            "timespan": timespan,
            "maxrecords": str(max_records),
            "sort": "datedesc",
        }
        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(GDELT_DOC_URL, params=params)
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
                label="gdelt",
            )
        return self.normalize_articles(payload=payload, fetched_at=fetched_at)

    @staticmethod
    def normalize_articles(
        *,
        payload: dict[str, Any],
        fetched_at: datetime,
    ) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for item in payload.get("articles", []):
            url = item.get("url")
            title = item.get("title")
            seendate = item.get("seendate")
            if not url or not title or not seendate:
                continue
            # One malformed seendate must not discard the rest of the batch.
            try:
                published_at = _parse_seendate(seendate)
            except (TypeError, ValueError):
                continue
            articles.append(
                NewsArticle(
                    source=GdeltDocConnector.source,
                    report_date=published_at.date(),
                    knowledge_date=fetched_at,
                    published_at=published_at,
                    url=url,
                    url_hash=url_hash(url),
                    title=title,
                    canonical_url=canonical_url(url),
                    summary=None,
                    tone=_to_optional_float(item.get("tone")),
                )
            )
        return articles


def _parse_seendate(value: str) -> datetime:
    # GDELT seendate format: YYYYMMDDTHHMMSSZ
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _to_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
