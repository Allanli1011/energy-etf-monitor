from datetime import UTC, date, datetime

import httpx
import pytest

from energy_etf_monitor.ingestion.proshares import (
    ProSharesHoldingsConnector,
    ProSharesHoldingsParser,
)

SAMPLE_PROSHARES_HTML = """
<html>
  <body>
    <span id="snapshot-netAssets">$399,514,066</span>
    <span id="price-asOfDate">as of 6/12/2026</span>
    <span id="price-nav">$42.31</span>
    <table id="holdings">
      <thead>
        <tr>
          <th>Exposure Weight</th>
          <th>Ticker</th>
          <th>Description</th>
          <th>Exposure Value (Notional + GL)</th>
          <th>Market Value</th>
          <th>Shares/Contracts</th>
          <th>SEDOL Number</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>59.09%</td>
          <td>--</td>
          <td>BLOOMBERG WTI CRUDE OIL BALANCED SWAP - SG</td>
          <td>236,102,442</td>
          <td>--</td>
          <td>2,127,302</td>
          <td>--</td>
        </tr>
        <tr>
          <td>10.50%</td>
          <td>--</td>
          <td>WTI CRUDE FUTURE DEC26</td>
          <td>41,956,220</td>
          <td>--</td>
          <td>542</td>
          <td>--</td>
        </tr>
        <tr>
          <td>--</td>
          <td>--</td>
          <td>NET OTHER ASSETS / CASH</td>
          <td>--</td>
          <td>$399,552,067.84</td>
          <td>399,552,068</td>
          <td>--</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""


def test_proshares_parser_extracts_metric_and_holdings() -> None:
    snapshot = ProSharesHoldingsParser().parse(
        SAMPLE_PROSHARES_HTML,
        fund_ticker="UCO",
        fetched_at=datetime(2026, 6, 13, 12, tzinfo=UTC),
    )

    assert snapshot.metric.source == "proshares"
    assert snapshot.metric.fund_ticker == "UCO"
    assert snapshot.metric.report_date == date(2026, 6, 12)
    assert snapshot.metric.nav_per_share == 42.31
    assert snapshot.metric.total_net_assets == 399_514_066
    assert snapshot.metric.shares_outstanding == pytest.approx(399_514_066 / 42.31)
    assert snapshot.metric.implied_flow_usd is None

    assert len(snapshot.holdings) == 3
    future = snapshot.holdings[1]
    assert future.source == "proshares"
    assert future.holding_key == "clz26|2026-12-01|wti_crude_future_dec26"
    assert future.instrument_type == "Futures"
    assert future.ticker == "CLZ26"
    assert future.contract_month == date(2026, 12, 1)
    assert future.quantity == 542
    assert future.market_value == 41_956_220
    assert future.percent_nav == 10.5

    cash = snapshot.holdings[2]
    assert cash.instrument_type == "Cash"
    assert cash.market_value == 399_552_067.84
    assert cash.percent_nav is None


def test_proshares_connector_fetches_page_and_saves_raw(tmp_path) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        assert "Mozilla" in request.headers["User-Agent"]
        return httpx.Response(200, text=SAMPLE_PROSHARES_HTML)

    connector = ProSharesHoldingsConnector(
        raw_root_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        product_urls={"UCO": "https://example.test/uco"},
    )

    snapshot = connector.fetch_latest(fund_ticker="uco")

    assert snapshot.metric.fund_ticker == "UCO"
    assert seen_urls == ["https://example.test/uco"]
    assert list((tmp_path / "proshares_html").glob("*/*.html"))
