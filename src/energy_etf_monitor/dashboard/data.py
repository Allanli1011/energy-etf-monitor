"""Pure, UI-agnostic data shaping for the dashboard.

Keeping this layer free of Streamlit/Plotly lets it be unit-tested and reused; ``app.py`` is a
thin rendering shell on top of these functions.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from energy_etf_monitor.modeling.predict import FeatureContribution, parse_top_drivers
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction


@dataclass(frozen=True)
class TodaysCall:
    commodity: str
    report_date: date
    horizon_days: int
    price_up_probability: float
    spread_up_probability: float
    price_naive_probability: float | None
    spread_naive_probability: float | None
    price_top_drivers: list[FeatureContribution]
    spread_top_drivers: list[FeatureContribution]


@dataclass(frozen=True)
class FeatureTimeSeries:
    dates: list[date]
    series: dict[str, list[float | None]]


def latest_call(predictions: Sequence[DailyPrediction]) -> TodaysCall | None:
    """The most recent non-quarantined prediction, decoded for display."""

    usable = [prediction for prediction in predictions if not prediction.quarantine]
    if not usable:
        return None
    latest = max(usable, key=lambda prediction: (prediction.report_date, prediction.knowledge_date))
    return TodaysCall(
        commodity=latest.commodity,
        report_date=latest.report_date,
        horizon_days=latest.horizon_days,
        price_up_probability=latest.price_up_probability,
        spread_up_probability=latest.spread_up_probability,
        price_naive_probability=latest.price_naive_probability,
        spread_naive_probability=latest.spread_naive_probability,
        price_top_drivers=parse_top_drivers(latest.price_top_drivers),
        spread_top_drivers=parse_top_drivers(latest.spread_top_drivers),
    )


def feature_time_series(
    feature_rows: Sequence[DailyFeatureRow],
    columns: Sequence[str],
) -> FeatureTimeSeries:
    """Project feature rows (report-date ascending) into aligned per-column series for charts."""

    ordered = sorted(feature_rows, key=lambda row: row.report_date)
    return FeatureTimeSeries(
        dates=[row.report_date for row in ordered],
        series={
            column: [_optional_float(getattr(row, column, None)) for row in ordered]
            for column in columns
        },
    )


PRICE_AND_CURVE_COLUMNS = (
    "cl_front_month_settlement",
    "cl_m1_m2_spread",
    "cl_m2_m3_spread",
    "cl_m3_m6_spread",
)
POSITIONING_COLUMNS = (
    "cot_swap_dealer_net",
    "cot_swap_dealer_net_zscore",
    "cot_swap_dealer_net_index",
)
INVENTORY_COLUMNS = (
    "inventory_value",
    "inventory_seasonal_surprise",
)


def _optional_float(value: float | None) -> float | None:
    return None if value is None else float(value)
