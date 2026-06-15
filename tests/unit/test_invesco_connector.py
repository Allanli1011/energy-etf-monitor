from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx

from energy_etf_monitor.ingestion import invesco
from energy_etf_monitor.ingestion.invesco import (
    InvescoHoldingsConnector,
    InvescoHoldingsParser,
)

SAMPLE_INVESCO_PRICE = {
    "effectiveDate": "2026-06-12",
    "cusip": "46140H403",
    "currency": "USD",
    "nav": 20.607132,
    "marketValue": 265_832_822.82,
    "sharesOutstanding": 12_900_040,
    "closingPrice": 20.46,
}

SAMPLE_INVESCO_HOLDINGS = {
    "cusip": "46140H403",
    "effectiveDate": "2026-06-13",
    "effectiveBusinessDate": "2026-06-12",
    "totalNumberOfHoldings": 5,
    "holdings": [
        {
            "percentageOfTotalNetAssets": 110.644548,
            "localCurrencyName": "WTI CRUDE FUTURE Sep26CLU6 COMB",
        },
        {
            "percentageOfTotalNetAssets": 88.146309,
            "localCurrencyName": "Invesco Government &amp; Agency",
        },
        {
            "percentageOfTotalNetAssets": -110.644548,
            "localCurrencyName": "CONTRA FUTURE WTI CRUDE FUTURE SEP26CLU6 COMB",
        },
    ],
}


def test_invesco_parser_extracts_metric_and_holdings() -> None:
    snapshot = InvescoHoldingsParser().parse(
        price=SAMPLE_INVESCO_PRICE,
        holdings=SAMPLE_INVESCO_HOLDINGS,
        fund_ticker="DBO",
        fetched_at=datetime(2026, 6, 13, 12, tzinfo=UTC),
    )

    assert snapshot.metric.source == "invesco"
    assert snapshot.metric.fund_ticker == "DBO"
    assert snapshot.metric.report_date == date(2026, 6, 12)
    assert snapshot.metric.nav_per_share == 20.607132
    assert snapshot.metric.shares_outstanding == 12_900_040
    assert snapshot.metric.total_net_assets == 265_832_822.82
    assert snapshot.metric.implied_flow_usd is None

    future = snapshot.holdings[0]
    assert future.source == "invesco"
    assert future.holding_key == "clu26|2026-09-01|wti_crude_future_sep26clu6_comb"
    assert future.instrument_type == "Futures"
    assert future.ticker == "CLU26"
    assert future.contract_month == date(2026, 9, 1)
    assert future.percent_nav == 110.644548

    collateral = snapshot.holdings[1]
    assert collateral.holding_name == "Invesco Government & Agency"
    assert collateral.instrument_type == "Collateral"
    assert collateral.contract_month is None

    contra = snapshot.holdings[2]
    assert contra.instrument_type == "Contra Future"
    assert contra.percent_nav == -110.644548


def test_invesco_connector_fetches_api_payloads_and_saves_raw(tmp_path) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        assert request.headers["Origin"] == "https://www.invesco.com"
        if "/prices?" in str(request.url):
            return httpx.Response(200, json=SAMPLE_INVESCO_PRICE)
        if "/holdings/fund?" in str(request.url):
            return httpx.Response(200, json=SAMPLE_INVESCO_HOLDINGS)
        raise AssertionError(f"Unexpected URL: {request.url}")

    connector = InvescoHoldingsConnector(
        raw_root_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        products={
            "DBO": {
                "cusip": "46140H403",
                "locale": "en_US",
                "product_type": "ETF",
                "page_url": "https://example.test/dbo",
            }
        },
        api_base_url="https://dng-api.example.test/cache/v1/accounts",
    )

    snapshot = connector.fetch_latest(fund_ticker="dbo")

    assert snapshot.metric.fund_ticker == "DBO"
    assert any("/prices?" in url for url in seen_urls)
    assert any("/holdings/fund?" in url for url in seen_urls)
    assert list((tmp_path / "invesco_api").glob("*/*.json"))


def test_invesco_connector_falls_back_to_curl_for_406(tmp_path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(406, request=request)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "curl"
        assert "Accept-Language" not in cmd
        payload = SAMPLE_INVESCO_PRICE if "/prices?" in cmd[-1] else SAMPLE_INVESCO_HOLDINGS
        return SimpleNamespace(returncode=0, stdout=invesco.json.dumps(payload), stderr="")

    monkeypatch.setattr(invesco.shutil, "which", lambda name: "curl")
    monkeypatch.setattr(invesco.subprocess, "run", fake_run)

    connector = InvescoHoldingsConnector(
        raw_root_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        products={
            "DBO": {
                "cusip": "46140H403",
                "locale": "en_US",
                "product_type": "ETF",
                "page_url": "https://example.test/dbo",
            }
        },
        api_base_url="https://dng-api.example.test/cache/v1/accounts",
    )

    snapshot = connector.fetch_latest(fund_ticker="DBO")

    assert snapshot.metric.total_net_assets == 265_832_822.82
    assert len(snapshot.holdings) == 3


def test_invesco_connector_uses_curl_without_injected_client(tmp_path, monkeypatch) -> None:
    seen_urls: list[str] = []

    def fake_run(cmd, **kwargs):
        seen_urls.append(cmd[-1])
        payload = SAMPLE_INVESCO_PRICE if "/prices?" in cmd[-1] else SAMPLE_INVESCO_HOLDINGS
        return SimpleNamespace(returncode=0, stdout=invesco.json.dumps(payload), stderr="")

    monkeypatch.setattr(invesco.shutil, "which", lambda name: "curl")
    monkeypatch.setattr(invesco.subprocess, "run", fake_run)

    connector = InvescoHoldingsConnector(raw_root_dir=tmp_path)

    snapshot = connector.fetch_latest(fund_ticker="DBO")

    assert snapshot.metric.fund_ticker == "DBO"
    assert any("/prices?" in url for url in seen_urls)
    assert any("/holdings/fund?" in url for url in seen_urls)
