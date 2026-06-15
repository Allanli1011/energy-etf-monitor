from datetime import UTC, date, datetime

import httpx

from energy_etf_monitor.ingestion.uscf import (
    UscfHoldingsConnector,
    UscfHoldingsParser,
    UscfPcfConnector,
    UscfPcfParser,
    derive_implied_flow,
)
from energy_etf_monitor.records import FundDailyMetric

SAMPLE_USO_PCF = """Fund,USO
As Of,2026-06-12
NAV,81.25
Shares Outstanding,10000000
Total Net Assets,812500000

Holdings
Name,Ticker,Asset Type,Contract Month,Quantity,Market Value,Percent of NAV
Crude Oil Future Aug 2026,CL,Futures,Aug 2026,8500,345000000,42.46
Crude Oil Future Sep 2026,CL,Futures,2026-09,7700,302000000,37.17
Cash,USD,Cash,,165500000,165500000,20.37
"""

SAMPLE_USCF_DAILY_PRICE = [
    {
        "symbol": "USO",
        "displaydate": "2026-06-12T05:00:00",
        "nav": 126.36,
        "navextended": 126.36148,
        "navtotal": 1_961_585_522.89,
        "so": 15_523_603,
        "cr": 5_000,
    }
]

SAMPLE_USCF_HOLDINGS = [
    {
        "fundsymbol": "USO",
        "name": "WTI CRUDE FUTURE Aug26",
        "shares": 20_734,
        "marketvalue": 1_728_178_900,
        "weight": 0.8810,
        "asofdate": "2026-06-12T05:00:00",
        "primaryidentifier": "CLQ6",
        "identifiertodisplay": "CLQ6",
        "holdingtype": "Futures",
        "holdingtypeabbrev": "FUT",
        "possessionname": "Hold",
    },
    {
        "fundsymbol": "USO",
        "name": "TRS SOC GEN SGIXCWTI 12192025",
        "shares": 977_427.59,
        "marketvalue": 111_729_650.07,
        "weight": 0.0570,
        "asofdate": "2026-06-12T05:00:00",
        "primaryidentifier": "SGIXCWTIT",
        "identifiertodisplay": "SGIXCWTIT",
        "holdingtype": "Swap",
        "holdingtypeabbrev": "SWAP",
        "possessionname": "Hold",
    },
]


def test_uscf_pcf_parser_extracts_metric_and_holdings() -> None:
    snapshot = UscfPcfParser().parse(
        SAMPLE_USO_PCF,
        fund_ticker="USO",
        fetched_at=datetime(2026, 6, 13, 12, tzinfo=UTC),
    )

    assert snapshot.metric.fund_ticker == "USO"
    assert snapshot.metric.report_date == date(2026, 6, 12)
    assert snapshot.metric.knowledge_date == datetime(2026, 6, 13, 12, tzinfo=UTC)
    assert snapshot.metric.nav_per_share == 81.25
    assert snapshot.metric.shares_outstanding == 10_000_000
    assert snapshot.metric.total_net_assets == 812_500_000
    assert len(snapshot.holdings) == 3
    assert snapshot.holdings[0].holding_key == "cl|2026-08-01|crude_oil_future_aug_2026"
    assert snapshot.holdings[0].contract_month == date(2026, 8, 1)
    assert snapshot.holdings[0].quantity == 8_500
    assert snapshot.holdings[0].market_value == 345_000_000
    assert snapshot.holdings[0].percent_nav == 42.46


def test_uscf_holdings_parser_extracts_official_metric_flow_and_contracts() -> None:
    snapshot = UscfHoldingsParser().parse(
        daily_price=SAMPLE_USCF_DAILY_PRICE,
        holdings=SAMPLE_USCF_HOLDINGS,
        fund_ticker="USO",
        fetched_at=datetime(2026, 6, 13, 12, tzinfo=UTC),
    )

    assert snapshot.metric.source == "uscf"
    assert snapshot.metric.fund_ticker == "USO"
    assert snapshot.metric.report_date == date(2026, 6, 12)
    assert snapshot.metric.nav_per_share == 126.36148
    assert snapshot.metric.shares_outstanding == 15_523_603
    assert snapshot.metric.total_net_assets == 1_961_585_522.89
    assert snapshot.metric.implied_flow_usd == 631_807.4
    assert len(snapshot.holdings) == 2
    assert snapshot.holdings[0].holding_key == "clq6|2026-08-01|wti_crude_future_aug26"
    assert snapshot.holdings[0].contract_month == date(2026, 8, 1)
    assert snapshot.holdings[0].quantity == 20_734
    assert snapshot.holdings[0].market_value == 1_728_178_900
    assert snapshot.holdings[0].percent_nav == 88.1
    assert snapshot.holdings[1].contract_month is None


def test_uscf_holdings_connector_fetches_tokenized_official_api_and_saves_raw(tmp_path) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(str(request.url))
        if str(request.url) == "https://www.uscfinvestments.com/site-template/assets/javascript/api_key.php":
            return httpx.Response(
                200,
                text=(
                    "var token = 'test-token';"
                    "var api_url_v2 = 'https://secure.example.test/api/v1/';"
                ),
            )
        assert request.headers["Authorization"] == "Bearer test-token"
        if str(request.url) == "https://secure.example.test/api/v1/dailyprice/USO":
            return httpx.Response(200, json=SAMPLE_USCF_DAILY_PRICE)
        if str(request.url) == "https://secure.example.test/api/v1/holding/USO/full":
            return httpx.Response(200, json=SAMPLE_USCF_HOLDINGS)
        raise AssertionError(f"Unexpected URL: {request.url}")

    connector = UscfHoldingsConnector(
        raw_root_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    snapshot = connector.fetch_latest(fund_ticker="USO")

    assert snapshot.metric.fund_ticker == "USO"
    assert any(path.endswith("/dailyprice/USO") for path in seen_paths)
    assert any(path.endswith("/holding/USO/full") for path in seen_paths)
    assert list((tmp_path / "uscf_api").glob("*/*.json"))


def test_derive_implied_flow_uses_current_nav_and_share_delta() -> None:
    previous = FundDailyMetric(
        source="uscf",
        fund_ticker="USO",
        report_date=date(2026, 6, 11),
        knowledge_date=datetime(2026, 6, 12, tzinfo=UTC),
        nav_per_share=80,
        shares_outstanding=9_500_000,
        total_net_assets=760_000_000,
    )
    current = FundDailyMetric(
        source="uscf",
        fund_ticker="USO",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        nav_per_share=81.25,
        shares_outstanding=10_000_000,
        total_net_assets=812_500_000,
    )

    enriched = derive_implied_flow(current=current, previous=previous)

    assert enriched.implied_flow_usd == 40_625_000


def test_uscf_connector_fetches_configured_pcf_url_and_saves_raw(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/uso.csv"
        return httpx.Response(200, text=SAMPLE_USO_PCF)

    connector = UscfPcfConnector(
        fund_ticker="USO",
        pcf_url="https://example.test/uso.csv",
        raw_root_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    snapshot = connector.fetch_latest()

    assert snapshot.metric.fund_ticker == "USO"
    assert list((tmp_path / "uscf_pcf").glob("*/*.csv"))

