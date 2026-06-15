from datetime import UTC, datetime
from pathlib import Path

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.gdelt import GdeltDocConnector


def test_normalize_articles_parses_seendate_and_builds_url_hash() -> None:
    payload = {
        "articles": [
            {
                "url": "https://www.reuters.com/markets/oil-1/",
                "title": "Crude jumps on OPEC cut",
                "seendate": "20260612T130000Z",
                "domain": "reuters.com",
            },
            # missing title -> skipped
            {"url": "https://x.com/y", "seendate": "20260612T130000Z"},
        ]
    }

    rows = GdeltDocConnector.normalize_articles(
        payload=payload,
        fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.source == "gdelt"
    assert row.title == "Crude jumps on OPEC cut"
    assert row.published_at == datetime(2026, 6, 12, 13, tzinfo=UTC)
    assert row.report_date.isoformat() == "2026-06-12"
    assert row.knowledge_date == datetime(2026, 6, 12, 14, tzinfo=UTC)
    assert row.canonical_url == "reuters.com/markets/oil-1"
    assert row.url_hash


def test_normalize_articles_skips_malformed_seendate() -> None:
    payload = {
        "articles": [
            {"url": "https://a.com/1", "title": "Good", "seendate": "20260612T130000Z"},
            # off-format seendate must not discard the whole batch
            {"url": "https://a.com/2", "title": "Bad date", "seendate": "2026-06-12"},
        ]
    }

    rows = GdeltDocConnector.normalize_articles(
        payload=payload,
        fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC),
    )

    assert [row.title for row in rows] == ["Good"]


def test_fetch_articles_queries_doc_api_and_saves_raw_payload(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/v2/doc/doc")
        assert request.url.params["mode"] == "ArtList"
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://a.com/1",
                        "title": "OPEC cuts output",
                        "seendate": "20260612T090000Z",
                    }
                ]
            },
        )

    connector = GdeltDocConnector(
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = connector.fetch_articles(timespan="1d", max_records=10)

    assert len(rows) == 1
    assert list((tmp_path / "news").glob("*/*gdelt*.json"))
