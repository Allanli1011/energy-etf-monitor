"""Generic RSS news connector (stdlib only) for official/publisher feeds.

Operators configure trusted feed URLs (EIA Today in Energy, OPEC, OilPrice, etc.). Items are
normalized into unclassified NewsArticle records for the shared classification pipeline.
"""

# RSS feeds are operator-configured and trusted; stdlib ElementTree is sufficient here.
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.news.dedup import canonical_url, url_hash
from energy_etf_monitor.records import NewsArticle

# A small free default set; override per deployment.
DEFAULT_FEEDS: tuple[tuple[str, str], ...] = (
    ("eia", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("oilprice", "https://oilprice.com/rss/main"),
)


class RssNewsConnector:
    def __init__(
        self,
        *,
        feed_url: str,
        source: str,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.feed_url = feed_url
        self.source = source
        self.raw_store = raw_store
        self.client = client

    def fetch_articles(self) -> list[NewsArticle]:
        fetched_at = datetime.now(UTC)
        client = self.client or httpx.Client(timeout=30, follow_redirects=True)
        close_client = self.client is None
        try:
            response = client.get(self.feed_url)
            response.raise_for_status()
            text = response.text
        finally:
            if close_client:
                client.close()

        if self.raw_store:
            self.raw_store.save_text(
                source="news",
                text=text,
                fetched_at=fetched_at,
                label=f"rss_{self.source}",
                extension="xml",
            )
        return self.normalize_feed(xml_text=text, source=self.source, fetched_at=fetched_at)

    @staticmethod
    def normalize_feed(*, xml_text: str, source: str, fetched_at: datetime) -> list[NewsArticle]:
        root = ElementTree.fromstring(xml_text)
        articles: list[NewsArticle] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            published_at = _parse_pubdate(item.findtext("pubDate"), fallback=fetched_at)
            summary = item.findtext("description")
            articles.append(
                NewsArticle(
                    source=source,
                    report_date=published_at.date(),
                    knowledge_date=fetched_at,
                    published_at=published_at,
                    url=link,
                    url_hash=url_hash(link),
                    title=title,
                    canonical_url=canonical_url(link),
                    summary=summary.strip() if summary else None,
                )
            )
        return articles


def _parse_pubdate(value: str | None, *, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
