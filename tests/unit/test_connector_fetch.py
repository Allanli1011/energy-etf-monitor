from datetime import date
from pathlib import Path

import httpx
import pytest

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.cftc import CftcCotConnector
from energy_etf_monitor.ingestion.cme import CmeSettlementCurveProvider
from energy_etf_monitor.ingestion.eia import EiaSeriesConnector
from energy_etf_monitor.ingestion.fred import FredSeriesConnector


def test_eia_fetch_series_uses_api_key_and_saves_raw_payload(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/WCESTUS1")
        assert request.url.params["api_key"] == "eia-key"
        return httpx.Response(
            200,
            json={
                "response": {
                    "data": [{"period": "2026-06-05", "value": "1.5", "units": "MMBbl"}]
                }
            },
        )

    connector = EiaSeriesConnector(
        api_key="eia-key",
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = connector.fetch_series("WCESTUS1")

    assert len(rows) == 1
    assert list((tmp_path / "eia").glob("*/*.json"))


def test_fred_fetch_observations_uses_window_and_saves_raw_payload(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "fred-key"
        assert request.url.params["series_id"] == "DTWEXBGS"
        assert request.url.params["observation_start"] == "2026-01-01"
        assert request.url.params["observation_end"] == "2026-06-13"
        return httpx.Response(200, json={"observations": [{"date": "2026-06-12", "value": "99"}]})

    connector = FredSeriesConnector(
        api_key="fred-key",
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = connector.fetch_observations(
        "DTWEXBGS",
        observation_start="2026-01-01",
        observation_end="2026-06-13",
    )

    assert len(rows) == 1
    assert list((tmp_path / "fred").glob("*/*.json"))


def test_cftc_fetch_wti_positions_uses_app_token_and_saves_raw_payload(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-App-Token"] == "cftc-token"
        assert request.url.params["$where"] == "cftc_contract_market_code='067651'"
        return httpx.Response(
            200,
            json=[
                {
                    "report_date_as_yyyy_mm_dd": "2026-06-09T00:00:00.000",
                    "market_and_exchange_names": "CRUDE OIL, LIGHT SWEET",
                    "cftc_contract_market_code": "067651",
                    "open_interest_all": "100",
                }
            ],
        )

    connector = CftcCotConnector(
        app_token="cftc-token",
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = connector.fetch_wti_positions(limit=100)

    assert len(rows) == 1
    assert rows[0].swap_dealer_long is None
    assert list((tmp_path / "cftc").glob("*/*.json"))


def test_cme_provider_fetches_supported_curve_and_saves_raw_payload(tmp_path: Path) -> None:
    html = """
    <table>
      <tr><th>Contract Month</th><th>Settlement</th><th>Open Int</th></tr>
      <tr><td>JUL 2026</td><td>73.25</td><td>250000</td></tr>
    </table>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert "light-sweet-crude" in str(request.url)
        return httpx.Response(200, text=html)

    provider = CmeSettlementCurveProvider(
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = provider.fetch_curve(product_code="CL", trade_date=date(2026, 6, 12))

    assert len(rows) == 1
    assert rows[0].contract_month.isoformat() == "2026-07-01"
    assert list((tmp_path / "cme").glob("*/*.json"))


def test_cme_provider_rejects_unsupported_product_code() -> None:
    provider = CmeSettlementCurveProvider()

    with pytest.raises(ValueError, match="Unsupported CME product code"):
        provider.fetch_curve(product_code="XYZ", trade_date=date(2026, 6, 12))

