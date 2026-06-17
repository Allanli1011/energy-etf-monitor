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
    etf_exposure_rows,
    etf_flow_rows,
    etf_strategy_summary_rows,
    feature_time_series,
    news_panel_rows,
)
from energy_etf_monitor.etfs import dashboard_commodities, etf_funds_for_commodity
from energy_etf_monitor.storage.repository import IngestionRepository


def _load(commodity: str, as_of: datetime):
    funds = etf_funds_for_commodity(commodity)
    tickers = [fund.ticker for fund in funds]
    with IngestionRepository.from_settings(Settings()) as repository:
        feature_rows = repository.list_daily_feature_rows(commodity=commodity)
        news = repository.list_news_articles(as_of=as_of, limit=25)
        fund_metrics = [
            metric
            for ticker in tickers
            for metric in repository.list_fund_daily_metrics(fund_ticker=ticker)
        ]
        fund_holdings = [
            holding
            for ticker in tickers
            for holding in repository.list_fund_holdings(fund_ticker=ticker)
        ]
    return feature_rows, news, fund_metrics, fund_holdings, funds


def _chart(series: FeatureTimeSeries) -> None:
    data = {"date": series.dates}
    data.update(series.series)
    st.line_chart(data, x="date")


def main() -> None:
    st.set_page_config(page_title="Energy ETF Monitor", layout="wide")
    st.title("Energy ETF monitor")
    st.caption(
        "Data-first monitor for ETF flows, issuer holdings, roll pressure, curves, positioning, "
        "inventory, and market-moving news."
    )

    commodity = st.sidebar.selectbox(
        "Commodity", list(dashboard_commodities(tuple(COMMODITIES))), index=0
    )
    as_of = datetime.now(UTC)
    feature_rows, news, fund_metrics, fund_holdings, funds = _load(commodity, as_of)

    st.header("Latest market-moving news")
    rows = news_panel_rows(news, limit=25)
    if not rows:
        st.info("No classified news yet. Run `ingest-news --load` to populate the panel.")
    else:
        st.dataframe(rows, hide_index=True, use_container_width=True)

    st.header("ETF flow & roll pressure")
    flow_rows = etf_flow_rows(fund_metrics, funds=funds)
    summary_rows = etf_strategy_summary_rows(fund_metrics, funds=funds)
    exposure_rows = etf_exposure_rows(fund_holdings, metrics=fund_metrics, funds=funds)
    st.dataframe(flow_rows, hide_index=True, use_container_width=True)
    if summary_rows:
        st.subheader("Strategy buckets")
        st.dataframe(summary_rows, hide_index=True, use_container_width=True)
    if exposure_rows:
        st.subheader("Latest futures exposure")
        st.dataframe(exposure_rows, hide_index=True, use_container_width=True)

    st.header("Price & curve")
    _chart(feature_time_series(feature_rows, PRICE_AND_CURVE_COLUMNS))

    st.header("Positioning (COT swap dealers)")
    _chart(feature_time_series(feature_rows, POSITIONING_COLUMNS))

    st.header("Inventory")
    _chart(feature_time_series(feature_rows, INVENTORY_COLUMNS))


if __name__ == "__main__":
    main()
