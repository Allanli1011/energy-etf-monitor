from datetime import UTC, date, datetime

import httpx

from energy_etf_monitor.ingestion.uscf import UscfPcfConnector, UscfPcfParser, derive_implied_flow
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

