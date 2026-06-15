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
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            # A single malformed feed yields no articles instead of aborting every other feed.
            return []
        articles: list[NewsArticle] = []
        for entry in _iter_feed_entries(root):
            title = (_child_text(entry, "title") or "").strip()
            link = (_entry_link(entry) or "").strip()
            if not title or not link:
                continue
            published_at = _parse_pubdate(_entry_pubdate(entry), fallback=fetched_at)
            summary = _entry_summary(entry)
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


def _local_name(tag: str) -> str:
    """Strip any XML namespace so RSS and Atom tags compare by local name."""

    return tag.rsplit("}", 1)[-1]


def _iter_feed_entries(root: ElementTree.Element) -> list[ElementTree.Element]:
    """Collect RSS <item> and Atom <entry> elements regardless of namespace."""

    return [element for element in root.iter() if _local_name(element.tag) in ("item", "entry")]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name and child.text:
            return child.text
    return None


def _entry_link(element: ElementTree.Element) -> str | None:
    """Resolve a link from RSS (<link>url</link>) or Atom (<link href=... rel=alternate/>)."""

    fallback: str | None = None
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = child.get("href")
        if href:
            if child.get("rel") in (None, "alternate"):
                return href
            fallback = fallback or href
        elif child.text and child.text.strip():
            return child.text.strip()
    return fallback


def _entry_pubdate(element: ElementTree.Element) -> str | None:
    # RSS uses pubDate; Atom uses published/updated.
    for name in ("pubDate", "published", "updated"):
        value = _child_text(element, name)
        if value:
            return value
    return None


def _entry_summary(element: ElementTree.Element) -> str | None:
    # RSS uses description; Atom uses summary/content.
    for name in ("description", "summary", "content"):
        value = _child_text(element, name)
        if value:
            return value
    return None


def _parse_pubdate(value: str | None, *, fallback: datetime) -> datetime:
    if not value:
        return fallback
    text = value.strip()
    parsed: datetime | None = None
    try:  # RFC 822 (RSS pubDate, e.g. "Fri, 12 Jun 2026 13:00:00 GMT")
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:  # ISO 8601 (Atom published/updated)
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
