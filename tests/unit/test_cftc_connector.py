from datetime import date
from zoneinfo import ZoneInfo

from energy_etf_monitor.ingestion.cftc import CftcCotConnector, cot_knowledge_datetime


def test_cot_knowledge_datetime_applies_tuesday_to_friday_release_lag() -> None:
    knowledge_date = cot_knowledge_datetime(date(2026, 6, 9))

    assert knowledge_date.isoformat() == "2026-06-12T15:30:00-04:00"
    assert knowledge_date.tzinfo == ZoneInfo("America/New_York")


def test_cftc_connector_normalizes_wti_swap_dealer_position() -> None:
    payload = [
        {
            "report_date_as_yyyy_mm_dd": "2026-06-09T00:00:00.000",
            "market_and_exchange_names": "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
            "cftc_contract_market_code": "067651",
            "open_interest_all": "1866415",
            "swap_positions_long_all": "507669",
            "swap_positions_short_all": "217401",
            "swap_positions_spread_all": "109584",
        }
    ]

    rows = CftcCotConnector.normalize_positions(payload=payload, commodity="WTI")

    assert len(rows) == 1
    row = rows[0]
    assert row.source == "cftc"
    assert row.commodity == "WTI"
    assert row.report_date.isoformat() == "2026-06-09"
    assert row.knowledge_date.isoformat() == "2026-06-12T15:30:00-04:00"
    assert row.open_interest == 1_866_415
    assert row.swap_dealer_long == 507_669
    assert row.swap_dealer_short == 217_401
    assert row.swap_dealer_spread == 109_584

