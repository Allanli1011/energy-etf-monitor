from datetime import UTC, datetime

from energy_etf_monitor.ingestion.fred import FredSeriesConnector


def test_fred_connector_skips_missing_values_and_normalizes_observations() -> None:
    payload = {
        "observations": [
            {"date": "2026-06-11", "value": "."},
            {"date": "2026-06-12", "value": "98.75"},
        ]
    }
    fetched_at = datetime(2026, 6, 13, 0, 5, tzinfo=UTC)

    rows = FredSeriesConnector.normalize_observations(
        payload=payload,
        series_id="DTWEXBGS",
        fetched_at=fetched_at,
    )

    assert len(rows) == 1
    assert rows[0].source == "fred"
    assert rows[0].series_id == "DTWEXBGS"
    assert rows[0].report_date.isoformat() == "2026-06-12"
    assert rows[0].knowledge_date == fetched_at
    assert rows[0].value == 98.75

