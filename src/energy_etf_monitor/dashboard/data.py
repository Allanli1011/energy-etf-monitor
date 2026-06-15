"""Pure, UI-agnostic data shaping for the dashboard.

Keeping this layer free of Streamlit/Plotly lets it be unit-tested and reused; ``app.py`` is a
thin rendering shell on top of these functions.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from energy_etf_monitor.etfs import EtfFundConfig
from energy_etf_monitor.modeling.predict import FeatureContribution, parse_top_drivers
from energy_etf_monitor.records import (
    DailyFeatureRow,
    DailyPrediction,
    FundDailyMetric,
    FundHolding,
    NewsArticle,
)

_METRIC_SOURCE_PRIORITY = {
    "uscf": 3,
    "uscf_api": 3,
    "invesco": 3,
    "proshares": 3,
    "yahoo_etf": 1,
}


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


def news_panel_rows(
    articles: Sequence[NewsArticle],
    *,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Project news articles into display rows, sorted by importance then recency."""

    ordered = sorted(
        articles,
        key=lambda article: (article.importance_score, article.published_at),
        reverse=True,
    )
    if limit is not None:
        ordered = ordered[:limit]
    return [
        {
            "published": article.published_at.isoformat(timespec="minutes"),
            "headline": article.title,
            "source": article.source,
            "commodity": article.commodity or "—",
            "catalyst": article.catalyst_type or "—",
            "importance": round(article.importance_score),
            "direction": article.impact_direction,
            "spread_direction": article.spread_impact_direction or "—",
            "confidence": round(article.confidence, 2),
            "rationale": article.rationale or "",
            "url": article.url,
        }
        for article in ordered
    ]


def etf_flow_rows(
    metrics: Sequence[FundDailyMetric],
    *,
    funds: Sequence[EtfFundConfig],
) -> list[dict[str, object]]:
    """Latest per-fund ETF flow rows for dashboard tables."""

    by_ticker = _metrics_by_ticker(metrics)
    rows: list[dict[str, object]] = []
    for fund in funds:
        fund_metrics = by_ticker.get(fund.ticker, [])
        if not fund_metrics:
            rows.append(_empty_etf_flow_row(fund))
            continue
        latest = fund_metrics[-1]
        daily_flow = latest.implied_flow_usd
        rows.append(
            {
                "ticker": fund.ticker,
                "issuer": fund.issuer,
                "strategy": fund.strategy_badge,
                "leverage": fund.leverage,
                "latest_date": latest.report_date.isoformat(),
                "latest_aum_usd": round(latest.total_net_assets),
                "daily_flow_usd": _round_optional(daily_flow),
                "flow_pct_aum": _flow_pct(daily_flow, latest.total_net_assets),
                "flow_5d_usd": _rolling_flow(fund_metrics, 5),
                "flow_20d_usd": _rolling_flow(fund_metrics, 20),
                "front_month_roll": fund.front_month_roll,
                "model_input": fund.include_in_model,
            }
        )
    return rows


def etf_strategy_summary_rows(
    metrics: Sequence[FundDailyMetric],
    *,
    funds: Sequence[EtfFundConfig],
) -> list[dict[str, object]]:
    """Aggregate latest ETF flow and AUM by strategy bucket."""

    flow_rows = [row for row in etf_flow_rows(metrics, funds=funds) if row["latest_date"]]
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in flow_rows:
        grouped.setdefault(str(row["strategy"]), []).append(row)
    out: list[dict[str, object]] = []
    for strategy, rows in grouped.items():
        out.append(
            {
                "strategy": strategy,
                "funds": ", ".join(str(row["ticker"]) for row in rows),
                "fund_count": len(rows),
                "aum_usd": sum(int(row["latest_aum_usd"]) for row in rows),
                "daily_flow_usd": sum(float(row["daily_flow_usd"] or 0.0) for row in rows),
                "flow_5d_usd": sum(float(row["flow_5d_usd"] or 0.0) for row in rows),
            }
        )
    out.sort(key=lambda row: abs(float(row["daily_flow_usd"])), reverse=True)
    return out


def etf_exposure_rows(
    holdings: Sequence[FundHolding],
    *,
    metrics: Sequence[FundDailyMetric],
    funds: Sequence[EtfFundConfig],
) -> list[dict[str, object]]:
    """Latest futures-holding exposure rows by fund and contract month."""

    fund_tickers = {fund.ticker for fund in funds}
    latest_metrics = {
        ticker: rows[-1] for ticker, rows in _metrics_by_ticker(metrics).items() if rows
    }
    latest_holding_dates = _latest_holding_dates(holdings, fund_tickers)
    rows: list[dict[str, object]] = []
    for holding in sorted(
        holdings,
        key=lambda item: (
            item.fund_ticker,
            item.contract_month or date.max,
            item.holding_key,
        ),
    ):
        if holding.fund_ticker not in fund_tickers:
            continue
        if latest_holding_dates.get(holding.fund_ticker) != holding.report_date:
            continue
        if holding.contract_month is None:
            continue
        metric = latest_metrics.get(holding.fund_ticker)
        percent_nav = holding.percent_nav
        if (
            percent_nav is None
            and holding.market_value is not None
            and metric is not None
            and metric.total_net_assets
        ):
            percent_nav = holding.market_value / metric.total_net_assets * 100.0
        rows.append(
            {
                "ticker": holding.fund_ticker,
                "contract_month": holding.contract_month.strftime("%Y-%m"),
                "holding_name": holding.holding_name,
                "quantity": _round_optional(holding.quantity),
                "market_value_usd": _round_optional(holding.market_value),
                "percent_nav": _round_optional(percent_nav, digits=2),
            }
        )
    return rows


def etf_flow_chart(
    metrics: Sequence[FundDailyMetric],
    *,
    funds: Sequence[EtfFundConfig],
) -> dict[str, object]:
    """Multi-fund daily flow chart data in millions of dollars."""

    by_ticker = _metrics_by_ticker(metrics)
    dates = sorted({metric.report_date for metric in metrics})
    series = []
    for fund in funds:
        fund_metrics = {metric.report_date: metric for metric in by_ticker.get(fund.ticker, [])}
        values = [
            (
                None
                if date_value not in fund_metrics
                or fund_metrics[date_value].implied_flow_usd is None
                else round(float(fund_metrics[date_value].implied_flow_usd) / 1_000_000, 3)
            )
            for date_value in dates
        ]
        if any(value is not None for value in values):
            series.append({"name": fund.ticker, "values": values})
    return {
        "dates": [date_value.isoformat() for date_value in dates],
        "series": series,
        "title": "ETF creation / redemption by fund",
        "yLabel": "Daily flow ($M)",
        "explain": (
            "Official issuer creation/redemption flow is used when available; otherwise the "
            "fallback estimate is changes in shares outstanding times NAV. Front-month funds map "
            "most directly to roll pressure; leveraged/inverse funds are context."
        ),
    }


def _optional_float(value: float | None) -> float | None:
    return None if value is None else float(value)


def _metrics_by_ticker(
    metrics: Sequence[FundDailyMetric],
) -> dict[str, list[FundDailyMetric]]:
    by_ticker_date: dict[tuple[str, date], FundDailyMetric] = {}
    for metric in metrics:
        key = (metric.fund_ticker.upper(), metric.report_date)
        existing = by_ticker_date.get(key)
        if existing is None or _metric_rank(metric) > _metric_rank(existing):
            by_ticker_date[key] = metric

    by_ticker: dict[str, list[FundDailyMetric]] = {}
    for metric in sorted(
        by_ticker_date.values(),
        key=lambda item: (item.fund_ticker.upper(), item.report_date),
    ):
        by_ticker.setdefault(metric.fund_ticker.upper(), []).append(metric)
    return by_ticker


def _metric_rank(metric: FundDailyMetric) -> tuple[int, datetime]:
    return (
        _METRIC_SOURCE_PRIORITY.get(metric.source, 0),
        metric.knowledge_date,
    )


def _latest_holding_dates(
    holdings: Sequence[FundHolding],
    fund_tickers: set[str],
) -> dict[str, date]:
    latest: dict[str, date] = {}
    for holding in holdings:
        if holding.fund_ticker not in fund_tickers:
            continue
        previous = latest.get(holding.fund_ticker)
        if previous is None or holding.report_date > previous:
            latest[holding.fund_ticker] = holding.report_date
    return latest


def _empty_etf_flow_row(fund: EtfFundConfig) -> dict[str, object]:
    return {
        "ticker": fund.ticker,
        "issuer": fund.issuer,
        "strategy": fund.strategy_badge,
        "leverage": fund.leverage,
        "latest_date": "",
        "latest_aum_usd": None,
        "daily_flow_usd": None,
        "flow_pct_aum": None,
        "flow_5d_usd": None,
        "flow_20d_usd": None,
        "front_month_roll": fund.front_month_roll,
        "model_input": fund.include_in_model,
    }


def _rolling_flow(metrics: Sequence[FundDailyMetric], window: int) -> float | None:
    flows = [
        metric.implied_flow_usd
        for metric in metrics[-window:]
        if metric.implied_flow_usd is not None
    ]
    if not flows:
        return None
    return round(sum(flows))


def _flow_pct(flow: float | None, aum: float) -> float | None:
    if flow is None or not aum:
        return None
    return round(flow / aum, 4)


def _round_optional(value: float | None, *, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    rounded = round(float(value), digits)
    return int(rounded) if digits == 0 else rounded
