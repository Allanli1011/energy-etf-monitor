from datetime import UTC, date, datetime

from energy_etf_monitor.dashboard.data import (
    PRICE_AND_CURVE_COLUMNS,
    feature_time_series,
    latest_call,
)
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction


def _prediction(report_date: date, *, knowledge_hour: int, quarantine: bool = False, **overrides):
    base = dict(
        source="prediction_pipeline",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime(
            report_date.year, report_date.month, report_date.day, knowledge_hour, tzinfo=UTC
        ),
        horizon_days=5,
        feature_report_date=report_date,
        price_up_probability=0.6,
        spread_up_probability=0.4,
        price_model_version="v1",
        spread_model_version="v1",
        price_top_drivers='[{"feature": "cl_carry_m1_m2", "contribution": 1.0}]',
        spread_top_drivers="[]",
        quarantine=quarantine,
    )
    base.update(overrides)
    return DailyPrediction(**base)


def _feature_row(report_date: date, *, settle: float, spread: float) -> DailyFeatureRow:
    return DailyFeatureRow(
        source="feature_pipeline",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime(
            report_date.year, report_date.month, report_date.day, 16, tzinfo=UTC
        ),
        cl_front_month_settlement=settle,
        cl_m1_m2_spread=spread,
    )


def test_latest_call_picks_most_recent_non_quarantined_and_decodes_drivers() -> None:
    predictions = [
        _prediction(date(2026, 6, 10), knowledge_hour=18, price_up_probability=0.55),
        _prediction(date(2026, 6, 12), knowledge_hour=18, price_up_probability=0.66),
        # newer report_date but quarantined -> must be ignored
        _prediction(date(2026, 6, 13), knowledge_hour=18, quarantine=True),
    ]

    call = latest_call(predictions)

    assert call is not None
    assert call.report_date == date(2026, 6, 12)
    assert call.price_up_probability == 0.66
    assert call.price_top_drivers[0].feature == "cl_carry_m1_m2"
    assert call.spread_top_drivers == []


def test_latest_call_returns_none_when_all_quarantined_or_empty() -> None:
    assert latest_call([]) is None
    assert latest_call([_prediction(date(2026, 6, 12), knowledge_hour=18, quarantine=True)]) is None


def test_feature_time_series_sorts_and_aligns_columns() -> None:
    rows = [
        _feature_row(date(2026, 6, 12), settle=73, spread=1),
        _feature_row(date(2026, 6, 10), settle=70, spread=-2),
        _feature_row(date(2026, 6, 11), settle=71, spread=-1),
    ]

    series = feature_time_series(rows, PRICE_AND_CURVE_COLUMNS)

    assert series.dates == [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    assert series.series["cl_front_month_settlement"] == [70.0, 71.0, 73.0]
    assert series.series["cl_m1_m2_spread"] == [-2.0, -1.0, 1.0]
    # a column absent from the rows is filled with None, aligned to dates
    assert series.series["cl_m2_m3_spread"] == [None, None, None]
