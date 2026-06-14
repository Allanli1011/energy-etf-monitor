from datetime import UTC, date, datetime, timedelta

from energy_etf_monitor.quality_gate import apply_quality_gate, inspect_record_quality
from energy_etf_monitor.records import CotPosition, FuturesSettlement, TimeSeriesObservation


def test_quality_gate_quarantines_records_known_before_report_date() -> None:
    record = TimeSeriesObservation(
        source="eia",
        series_id="WCESTUS1",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 11, tzinfo=UTC),
        value=412_345,
    )

    result = inspect_record_quality(record)
    gated = apply_quality_gate(record)

    assert result.quarantine is True
    assert "knowledge_date_before_report_date" in result.reasons
    assert gated.quarantine is True


def test_quality_gate_quarantines_negative_cot_open_interest() -> None:
    record = CotPosition(
        source="cftc",
        commodity="WTI",
        market_name="CRUDE OIL, LIGHT SWEET",
        contract_market_code="067651",
        report_date=date(2026, 6, 9),
        knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
        open_interest=-1,
        swap_dealer_long=100,
    )

    result = inspect_record_quality(record)

    assert result.quarantine is True
    assert "negative_open_interest" in result.reasons


def test_quality_gate_quarantines_nonpositive_futures_settlement() -> None:
    record = FuturesSettlement(
        source="cme",
        product_code="CL",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        contract_month=date(2026, 7, 1),
        settlement_price=0,
    )

    result = inspect_record_quality(record)

    assert result.quarantine is True
    assert "nonpositive_settlement_price" in result.reasons


def test_quality_gate_keeps_valid_macro_observation_even_when_value_is_negative() -> None:
    record = TimeSeriesObservation(
        source="fred",
        series_id="DFII10",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, tzinfo=UTC) + timedelta(hours=1),
        value=-0.25,
    )

    result = inspect_record_quality(record)

    assert result.quarantine is False
    assert result.reasons == []

