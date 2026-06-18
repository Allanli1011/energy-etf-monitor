from datetime import UTC, date, datetime

import httpx

import energy_etf_monitor.ingestion.wisdomtree as wisdomtree
from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.wisdomtree import (
    WISDOMTREE_FUNDLIST_PARAMS,
    WISDOMTREE_PRODUCTS_URL,
    WisdomTreeFundListConnector,
    parse_wisdomtree_fundlist_metrics,
)

SAMPLE_FUNDLIST = [
    {
        "exchangeTicker": "BRNG",
        "name": "WisdomTree Brent Crude Oil",
        "fundCurrency": "USD",
        "baseCCY": "USD",
        "listingCCY": "GBP",
        "AUM": 695_517_504,
        "AUMusd": 695_517_504,
        "NAV": 56.33905,
        "NAVusd": 56.33905,
        "SharesOutstanding": 12_345_212,
        "NAV_Date": "2026-06-15",
    },
    {
        "exchangeTicker": "BRNT",
        "name": "WisdomTree Brent Crude Oil",
        "fundCurrency": "USD",
        "baseCCY": "USD",
        "listingCCY": "USD",
        "AUM": 934_914_624,
        "AUMusd": 934_914_646.29,
        "NAV": 75.73095,
        "NAVusd": 75.73095,
        "SharesOutstanding": 12_345_212,
        "NAV_Date": "2026-06-15",
    },
    {
        "exchangeTicker": "SBRT",
        "name": "WisdomTree Brent Crude Oil 1x Daily Short",
        "fundCurrency": "USD",
        "baseCCY": "USD",
        "listingCCY": "USD",
        "AUM": 52_609_684,
        "NAV": 9.37389,
        "SharesOutstanding": 5_612_366,
        "AUM_DateTime": "2026-06-15T00:00:00Z",
    },
]


def test_wisdomtree_parser_selects_same_ticker_usd_listing() -> None:
    metrics = parse_wisdomtree_fundlist_metrics(
        SAMPLE_FUNDLIST,
        fund_tickers=["BRNT", "SBRT", "MISSING"],
        fetched_at=datetime(2026, 6, 16, 8, tzinfo=UTC),
    )

    assert [metric.fund_ticker for metric in metrics] == ["BRNT", "SBRT"]
    brnt = metrics[0]
    assert brnt.source == "wisdomtree_fundlist"
    assert brnt.report_date == date(2026, 6, 15)
    assert brnt.nav_per_share == 75.73095
    assert brnt.total_net_assets == 934_914_646.29
    assert brnt.shares_outstanding == 12_345_212

    sbrt = metrics[1]
    assert sbrt.report_date == date(2026, 6, 15)
    assert sbrt.total_net_assets == 52_609_684


def test_wisdomtree_connector_fetches_fundlist_and_saves_raw(tmp_path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["user_agent"] = request.headers["User-Agent"]
        expected_params = {k: str(v) for k, v in WISDOMTREE_FUNDLIST_PARAMS.items()}
        assert dict(request.url.params) == expected_params
        return httpx.Response(200, json=SAMPLE_FUNDLIST)

    connector = WisdomTreeFundListConnector(
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        fundlist_url="https://example.test/fundlist/data/",
    )

    metrics = connector.fetch_metrics(fund_tickers=["BRNT"])

    assert metrics[0].fund_ticker == "BRNT"
    assert "Mozilla" in seen["user_agent"]
    assert list((tmp_path / "wisdomtree_fundlist").glob("*/*.json"))


def test_wisdomtree_connector_uses_browser_tls_fallback_for_403(monkeypatch) -> None:
    browser_tls_calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    def fake_browser_tls(url: str, params: dict[str, object]) -> list[dict[str, object]]:
        browser_tls_calls.append((url, params))
        return SAMPLE_FUNDLIST

    monkeypatch.setattr(wisdomtree, "_fetch_with_browser_tls", fake_browser_tls)
    connector = WisdomTreeFundListConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        fundlist_url="https://example.test/fundlist/data/",
    )

    metrics = connector.fetch_metrics(fund_tickers=["BRNT"])

    assert [metric.fund_ticker for metric in metrics] == ["BRNT"]
    assert browser_tls_calls == [
        ("https://example.test/fundlist/data/", WISDOMTREE_FUNDLIST_PARAMS)
    ]


def test_browser_tls_fetch_warms_products_page_and_retries_impersonations(
    monkeypatch,
) -> None:
    from curl_cffi import requests as curl_requests

    calls: list[tuple[str, str, object | None]] = []

    class FakeResponse:
        def __init__(self, *, status_code: int = 200, payload: object | None = None) -> None:
            self.status_code = status_code
            self.payload = payload or []

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> object:
            return self.payload

    class FakeSession:
        def __init__(self, *, impersonate: str, timeout: int) -> None:
            self.impersonate = impersonate
            self.timeout = timeout
            self.headers: dict[str, str] = {}
            self.closed = False

        def get(self, url: str, *, params: object | None = None, **kwargs) -> FakeResponse:
            _ = kwargs
            calls.append((self.impersonate, url, params))
            if url == WISDOMTREE_PRODUCTS_URL:
                return FakeResponse()
            if self.impersonate == "chrome146":
                return FakeResponse(status_code=403)
            return FakeResponse(payload=SAMPLE_FUNDLIST)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(wisdomtree, "_BROWSER_TLS_IMPERSONATIONS", ("chrome146", "chrome120"))
    monkeypatch.setattr(curl_requests, "Session", FakeSession)

    payload = wisdomtree._fetch_with_browser_tls(
        "https://example.test/fundlist/data/",
        WISDOMTREE_FUNDLIST_PARAMS,
    )

    assert payload == SAMPLE_FUNDLIST
    assert calls == [
        ("chrome146", WISDOMTREE_PRODUCTS_URL, None),
        ("chrome146", "https://example.test/fundlist/data/", WISDOMTREE_FUNDLIST_PARAMS),
        ("chrome120", WISDOMTREE_PRODUCTS_URL, None),
        ("chrome120", "https://example.test/fundlist/data/", WISDOMTREE_FUNDLIST_PARAMS),
    ]
