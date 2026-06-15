from datetime import UTC, datetime
from pathlib import Path

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.marketaux import MarketauxConnector
from energy_etf_monitor.ingestion.rss import RssNewsConnector


def test_marketaux_normalizes_articles() -> None:
    payload = {
        "data": [
            {
                "url": "https://www.example.com/oil-1/",
                "title": "Crude rallies on supply fears",
                "description": "OPEC signals cuts",
                "published_at": "2026-06-12T09:30:00.000000Z",
                "source": "example.com",
            },
            {"title": "missing url", "published_at": "2026-06-12T09:30:00Z"},
        ]
    }

    rows = MarketauxConnector.normalize_articles(
        payload=payload, fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC)
    )

    assert len(rows) == 1
    assert rows[0].source == "marketaux"
    assert rows[0].published_at == datetime(2026, 6, 12, 9, 30, tzinfo=UTC)
    assert rows[0].summary == "OPEC signals cuts"
    assert rows[0].canonical_url == "example.com/oil-1"


def test_marketaux_skips_malformed_timestamp() -> None:
    payload = {
        "data": [
            {"url": "https://a.com/1", "title": "Good", "published_at": "2026-06-12T09:00:00Z"},
            # unparseable timestamp must not discard the whole batch
            {"url": "https://a.com/2", "title": "Bad", "published_at": "not-a-time"},
        ]
    }

    rows = MarketauxConnector.normalize_articles(
        payload=payload, fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC)
    )

    assert [row.title for row in rows] == ["Good"]


def test_marketaux_fetch_uses_token_and_saves_raw(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_token"] == "mx-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "url": "https://a.com/1",
                        "title": "OPEC cuts",
                        "published_at": "2026-06-12T09:00:00Z",
                    }
                ]
            },
        )

    connector = MarketauxConnector(
        api_key="mx-key",
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = connector.fetch_articles()

    assert len(rows) == 1
    assert list((tmp_path / "news").glob("*/*marketaux*.json"))


def test_rss_normalizes_feed_items() -> None:
    xml_text = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>EIA: crude inventories drop sharply</title>
        <link>https://www.eia.gov/todayinenergy/detail.php?id=1</link>
        <pubDate>Fri, 12 Jun 2026 13:00:00 GMT</pubDate>
        <description>Weekly draw</description>
      </item>
      <item>
        <title>No link item</title>
      </item>
    </channel></rss>
    """

    rows = RssNewsConnector.normalize_feed(
        xml_text=xml_text, source="eia", fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC)
    )

    assert len(rows) == 1
    assert rows[0].source == "eia"
    assert rows[0].title == "EIA: crude inventories drop sharply"
    assert rows[0].published_at == datetime(2026, 6, 12, 13, tzinfo=UTC)
    assert rows[0].summary == "Weekly draw"


def test_rss_normalizes_atom_feed() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom: natural gas prices climb</title>
        <link rel="alternate" href="https://example.com/atom-1"/>
        <published>2026-06-12T13:00:00Z</published>
        <summary>Cold snap lifts demand</summary>
      </entry>
    </feed>
    """

    rows = RssNewsConnector.normalize_feed(
        xml_text=xml_text, source="opec", fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC)
    )

    assert len(rows) == 1
    assert rows[0].title == "Atom: natural gas prices climb"
    assert rows[0].url == "https://example.com/atom-1"
    assert rows[0].published_at == datetime(2026, 6, 12, 13, tzinfo=UTC)
    assert rows[0].summary == "Cold snap lifts demand"


def test_rss_returns_empty_on_malformed_xml() -> None:
    rows = RssNewsConnector.normalize_feed(
        xml_text="<rss><channel><item><title>oops",  # truncated / unparseable
        source="x",
        fetched_at=datetime(2026, 6, 12, 14, tzinfo=UTC),
    )

    assert rows == []


def test_rss_fetch_saves_raw_payload(tmp_path: Path) -> None:
    xml_text = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Oil up</title><link>https://a.com/1</link>"
        "<pubDate>Fri, 12 Jun 2026 13:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=xml_text)

    connector = RssNewsConnector(
        feed_url="https://feeds.example.com/energy.xml",
        source="example",
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = connector.fetch_articles()

    assert len(rows) == 1
    assert list((tmp_path / "news").glob("*/*rss_example*.xml"))
