"""Canonicalization, hashing, and deduplication for news articles.

Syndicated wire stories appear many times across outlets; the panel should show *events*, not
copies. We collapse by exact URL hash, canonical URL, and a normalized title fingerprint within a
publish-time window.
"""

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from energy_etf_monitor.records import NewsArticle


def canonical_url(url: str) -> str:
    """Strip scheme/www/query noise so the same article at different URLs collapses together."""

    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}"


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


def title_fingerprint(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", "", title.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def deduplicate_articles(
    articles: Sequence[NewsArticle],
    *,
    title_window_hours: int = 24,
) -> list[NewsArticle]:
    """Keep the earliest article per dedup key (exact URL, canonical URL, or windowed title)."""

    ordered = sorted(articles, key=lambda article: _as_utc_naive(article.published_at))
    window = timedelta(hours=title_window_hours)
    kept: list[NewsArticle] = []
    seen_hashes: set[str] = set()
    seen_canonical: set[str] = set()
    fingerprint_times: dict[str, list[datetime]] = {}

    for article in ordered:
        canonical = article.canonical_url or canonical_url(article.url)
        if article.url_hash in seen_hashes or canonical in seen_canonical:
            continue
        fingerprint = title_fingerprint(article.title)
        published = _as_utc_naive(article.published_at)
        if any(
            abs((published - earlier).total_seconds()) <= window.total_seconds()
            for earlier in fingerprint_times.get(fingerprint, [])
        ):
            continue
        kept.append(article)
        seen_hashes.add(article.url_hash)
        seen_canonical.add(canonical)
        fingerprint_times.setdefault(fingerprint, []).append(published)

    return kept


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
