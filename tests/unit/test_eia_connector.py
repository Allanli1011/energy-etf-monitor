from datetime import UTC, datetime

from energy_etf_monitor.ingestion.eia import EiaSeriesConnector


def test_eia_connector_normalizes_series_rows_with_dual_timestamps() -> None:
    payload = {
        "response": {
            "data": [
                {
                    "period": "2026-06-05",
                    "series": "WCESTUS1",
                    "value": "412345",
                    "units": "Thousand Barrels",
                }
            ]
        }
    }
    fetched_at = datetime(2026, 6, 10, 14, 35, tzinfo=UTC)

    rows = EiaSeriesConnector.normalize_series(
        payload=payload,
        series_id="WCESTUS1",
        fetched_at=fetched_at,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.source == "eia"
    assert row.series_id == "WCESTUS1"
    assert row.report_date.isoformat() == "2026-06-05"
    assert row.knowledge_date == fetched_at
    assert row.value == 412345.0
    assert row.unit == "Thousand Barrels"


def test_eia_connector_parses_monthly_and_annual_periods_and_skips_bad_rows() -> None:
    payload = {
        "response": {
            "data": [
                {"period": "2026-05", "series": "X", "value": "10", "units": "u"},
                {"period": "not-a-date", "series": "X", "value": "20", "units": "u"},
                {"period": "2026", "series": "X", "value": "30", "units": "u"},
            ]
        }
    }

    rows = EiaSeriesConnector.normalize_series(
        payload=payload,
        series_id="X",
        fetched_at=datetime(2026, 6, 10, tzinfo=UTC),
    )

    # The monthly and annual rows parse (anchored to the first of the period); the
    # unparseable row is skipped rather than crashing the whole series.
    assert [row.report_date.isoformat() for row in rows] == ["2026-05-01", "2026-01-01"]
    assert [row.value for row in rows] == [10.0, 30.0]

