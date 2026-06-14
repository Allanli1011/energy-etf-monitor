"""Streamlit dashboard for the energy ETF monitor.

Run with the optional dashboard dependencies:

    uv run --extra dashboard streamlit run src/energy_etf_monitor/dashboard/app.py

This module is a thin rendering shell; all data shaping lives in ``dashboard/data.py`` and the
point-in-time queries live in the repository, both of which are unit-tested.
"""

from datetime import UTC, datetime

import streamlit as st

from energy_etf_monitor.commodities import COMMODITIES
from energy_etf_monitor.config import Settings
from energy_etf_monitor.dashboard.data import (
    INVENTORY_COLUMNS,
    POSITIONING_COLUMNS,
    PRICE_AND_CURVE_COLUMNS,
    FeatureTimeSeries,
    feature_time_series,
    latest_call,
)
from energy_etf_monitor.modeling.monitoring import build_model_health_report
from energy_etf_monitor.storage.repository import IngestionRepository


def _load(commodity: str, as_of: datetime):
    with IngestionRepository.from_settings(Settings()) as repository:
        predictions = repository.list_daily_predictions(commodity=commodity)
        feature_rows = repository.list_daily_feature_rows(commodity=commodity)
    health = build_model_health_report(
        predictions, feature_rows, as_of=as_of, commodity=commodity
    )
    return predictions, feature_rows, health


def _chart(series: FeatureTimeSeries) -> None:
    data = {"date": series.dates}
    data.update(series.series)
    st.line_chart(data, x="date")


def main() -> None:
    st.set_page_config(page_title="Energy ETF Monitor", layout="wide")
    st.title("Energy ETF monitor")
    st.caption(
        "Probabilistic directional tilts, not a price oracle. "
        "Always read calls against the naive baseline and the model-health page."
    )

    commodity = st.sidebar.selectbox("Commodity", list(COMMODITIES), index=0)
    as_of = datetime.now(UTC)
    predictions, feature_rows, health = _load(commodity, as_of)

    st.header("Today's call")
    call = latest_call(predictions)
    if call is None:
        st.info("No predictions yet. Run `predict-daily --load` to populate calls.")
    else:
        st.caption(
            f"{call.commodity} — decision date {call.report_date}, horizon {call.horizon_days}d"
        )
        price_col, spread_col = st.columns(2)
        price_col.metric(
            "P(price up)",
            f"{call.price_up_probability:.2f}",
            delta=_naive_delta(call.price_up_probability, call.price_naive_probability),
        )
        spread_col.metric(
            "P(spread widens)",
            f"{call.spread_up_probability:.2f}",
            delta=_naive_delta(call.spread_up_probability, call.spread_naive_probability),
        )
        driver_price, driver_spread = st.columns(2)
        driver_price.subheader("Price drivers")
        driver_price.table(_drivers_table(call.price_top_drivers))
        driver_spread.subheader("Spread drivers")
        driver_spread.table(_drivers_table(call.spread_top_drivers))

    st.header("Price & curve")
    _chart(feature_time_series(feature_rows, PRICE_AND_CURVE_COLUMNS))

    st.header("Positioning (COT swap dealers)")
    _chart(feature_time_series(feature_rows, POSITIONING_COLUMNS))

    st.header("Inventory")
    _chart(feature_time_series(feature_rows, INVENTORY_COLUMNS))

    st.header("Model health (decay monitor)")
    if not health.metrics:
        st.info("No realized outcomes yet — model health appears after horizon days elapse.")
    else:
        st.caption(f"Scored {len(health.outcomes)} predictions with realized outcomes.")
        st.json(health.metrics)
        if health.rolling_metrics:
            st.subheader("Rolling window")
            st.json(health.rolling_metrics)
        if health.regime_metrics:
            st.subheader("By regime")
            st.json(health.regime_metrics)


def _naive_delta(model_probability: float, naive_probability: float | None) -> str | None:
    if naive_probability is None:
        return None
    return f"{model_probability - naive_probability:+.2f} vs naive"


def _drivers_table(drivers) -> list[dict[str, object]]:
    return [
        {"feature": driver.feature, "contribution": round(driver.contribution, 4)}
        for driver in drivers
    ]


if __name__ == "__main__":
    main()
