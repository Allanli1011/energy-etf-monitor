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
    "proshares": 3,
    "wisdomtree_fundlist": 2,
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
        fund_metrics = _preferred_metric_series(by_ticker.get(fund.ticker, []))
        if not fund_metrics:
            rows.append(_empty_etf_flow_row(fund))
            continue
        latest = fund_metrics[-1]
        daily_flow = latest.implied_flow_usd
        exposure_flow = _exposure_adjusted_flow(daily_flow, fund)
        exposure_flow_5d = _exposure_adjusted_flow(_rolling_flow(fund_metrics, 5), fund)
        rows.append(
            {
                "ticker": fund.ticker,
                "issuer": fund.issuer,
                "strategy": fund.strategy_badge,
                "leverage": fund.leverage,
                "latest_date": latest.report_date.isoformat(),
                "latest_aum_usd": round(latest.total_net_assets),
                "daily_flow_usd": _round_optional(daily_flow),
                "exposure_flow_usd": _round_optional(exposure_flow),
                "flow_pct_aum": _flow_pct(daily_flow, latest.total_net_assets),
                "flow_5d_usd": _rolling_flow(fund_metrics, 5),
                "exposure_flow_5d_usd": _round_optional(exposure_flow_5d),
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
                "exposure_flow_usd": sum(
                    float(row["exposure_flow_usd"] or 0.0) for row in rows
                ),
                "flow_5d_usd": sum(float(row["flow_5d_usd"] or 0.0) for row in rows),
                "exposure_flow_5d_usd": sum(
                    float(row["exposure_flow_5d_usd"] or 0.0) for row in rows
                ),
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
        ticker: preferred[-1]
        for ticker, rows in _metrics_by_ticker(metrics).items()
        if (preferred := _preferred_metric_series(rows))
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


def etf_source_health_rows(
    metrics: Sequence[FundDailyMetric],
    *,
    holdings: Sequence[FundHolding],
    funds: Sequence[EtfFundConfig],
    as_of: date | None = None,
) -> list[dict[str, object]]:
    """Per-fund ETF data coverage and caveats for the dashboard."""

    fund_tickers = {fund.ticker for fund in funds}
    by_ticker = _metrics_by_ticker(metrics)
    latest_holding_dates = _latest_holding_dates(holdings, fund_tickers)
    latest_holdings = _latest_holdings_by_ticker(holdings, latest_holding_dates)
    rows: list[dict[str, object]] = []
    for fund in funds:
        ticker = fund.ticker
        fund_metrics = _preferred_metric_series(by_ticker.get(ticker, []))
        latest_metric = fund_metrics[-1] if fund_metrics else None
        holding_date = latest_holding_dates.get(ticker)
        holding_rows = latest_holdings.get(ticker, [])
        contract_rows = sum(1 for holding in holding_rows if holding.contract_month is not None)
        notes = _source_health_notes(
            metric=latest_metric,
            holding_date=holding_date,
            holding_count=len(holding_rows),
            contract_rows=contract_rows,
            as_of=as_of,
        )
        rows.append(
            {
                "ticker": ticker,
                "issuer": fund.issuer,
                "status": _source_health_status(
                    metric=latest_metric,
                    holding_date=holding_date,
                    contract_rows=contract_rows,
                    as_of=as_of,
                ),
                "metric_source": latest_metric.source if latest_metric is not None else "",
                "latest_metric_date": (
                    latest_metric.report_date.isoformat() if latest_metric is not None else ""
                ),
                "latest_holding_date": holding_date.isoformat() if holding_date else "",
                "holding_rows": len(holding_rows),
                "contract_rows": contract_rows,
                "note": "; ".join(notes) if notes else "Issuer metric and holdings loaded",
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
    preferred_by_ticker = {
        fund.ticker: _preferred_metric_series(by_ticker.get(fund.ticker, [])) for fund in funds
    }
    dates = sorted(
        {
            metric.report_date
            for fund_metrics in preferred_by_ticker.values()
            for metric in fund_metrics
        }
    )
    series = []
    for fund in funds:
        fund_metrics = {metric.report_date: metric for metric in preferred_by_ticker[fund.ticker]}
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
        "net": {
            "name": "Net ETF cash flow",
            "values": _net_flow_values(series),
        },
        "title": "ETF creation / redemption by fund",
        "yLabel": "Daily flow ($M)",
        "explain": (
            "Official issuer creation/redemption flow is used when available; otherwise the "
            "fallback estimate is changes in shares outstanding times NAV. Front-month funds map "
            "most directly to roll pressure; leveraged/inverse funds are context."
        ),
    }


def etf_exposure_flow_chart(
    metrics: Sequence[FundDailyMetric],
    *,
    funds: Sequence[EtfFundConfig],
) -> dict[str, object]:
    """Multi-fund commodity-equivalent flow chart data in millions of dollars."""

    commodity = funds[0].commodity if funds else "COMMODITY"
    by_ticker = _metrics_by_ticker(metrics)
    preferred_by_ticker = {
        fund.ticker: _preferred_metric_series(by_ticker.get(fund.ticker, [])) for fund in funds
    }
    dates = sorted(
        {
            metric.report_date
            for fund_metrics in preferred_by_ticker.values()
            for metric in fund_metrics
        }
    )
    series = []
    for fund in funds:
        fund_metrics = {metric.report_date: metric for metric in preferred_by_ticker[fund.ticker]}
        values = [
            (
                None
                if date_value not in fund_metrics
                or fund_metrics[date_value].implied_flow_usd is None
                else round(
                    float(fund_metrics[date_value].implied_flow_usd)
                    * fund.leverage
                    / 1_000_000,
                    3,
                )
            )
            for date_value in dates
        ]
        if any(value is not None for value in values):
            series.append({"name": fund.ticker, "values": values})
    return {
        "dates": [date_value.isoformat() for date_value in dates],
        "series": series,
        "net": {
            "name": f"Net {commodity}-equivalent flow",
            "values": _net_flow_values(series),
        },
        "title": f"{commodity}-equivalent futures exposure flow by fund",
        "yLabel": f"{commodity}-equivalent flow ($M)",
        "explain": (
            "ETF cash creation/redemption is converted to commodity-equivalent notional by "
            "multiplying by each fund's target leverage. Leveraged funds scale the notional; "
            "inverse funds flip sign, so redemptions from an inverse ETF can be positive "
            f"{commodity} exposure flow. Treat leveraged/inverse products as directional "
            "notional pressure because some exposure may be implemented with swaps."
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
        _metric_source_priority(metric),
        metric.knowledge_date,
    )


def _preferred_metric_series(metrics: Sequence[FundDailyMetric]) -> list[FundDailyMetric]:
    if not metrics:
        return []
    best_priority = max(_metric_source_priority(metric) for metric in metrics)
    return [metric for metric in metrics if _metric_source_priority(metric) == best_priority]


def _metric_source_priority(metric: FundDailyMetric) -> int:
    return _METRIC_SOURCE_PRIORITY.get(metric.source, 0)


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


def _latest_holdings_by_ticker(
    holdings: Sequence[FundHolding],
    latest_dates: dict[str, date],
) -> dict[str, list[FundHolding]]:
    by_ticker: dict[str, list[FundHolding]] = {}
    for holding in holdings:
        if latest_dates.get(holding.fund_ticker) == holding.report_date:
            by_ticker.setdefault(holding.fund_ticker, []).append(holding)
    return by_ticker


def _source_health_status(
    *,
    metric: FundDailyMetric | None,
    holding_date: date | None,
    contract_rows: int,
    as_of: date | None,
) -> str:
    if metric is None and holding_date is None:
        return "missing"
    if _is_stale(metric.report_date if metric is not None else holding_date, as_of):
        return "stale"
    if metric is None or holding_date is None or contract_rows == 0:
        return "partial"
    if metric.source == "yahoo_etf" or metric.implied_flow_usd is None:
        return "partial"
    return "ok"


def _source_health_notes(
    *,
    metric: FundDailyMetric | None,
    holding_date: date | None,
    holding_count: int,
    contract_rows: int,
    as_of: date | None,
) -> list[str]:
    notes: list[str] = []
    if metric is None:
        notes.append("No issuer metric snapshot loaded")
    elif metric.source == "wisdomtree_fundlist":
        notes.append("Using WisdomTree fund-list metric; holdings/PCF are not disclosed")
    elif metric.source == "yahoo_etf":
        notes.append("Using Yahoo fallback metric, not issuer data")
    if holding_date is None:
        notes.append("No issuer holdings/PCF rows loaded")
    elif contract_rows == 0:
        notes.append("Holdings loaded but no contract-month exposure parsed")
    elif holding_count != contract_rows:
        notes.append("Holdings include cash/swap/collateral rows outside contract-month table")
    if metric is not None and metric.implied_flow_usd is None:
        notes.append("Creation/redemption flow not directly available")
    latest_date = metric.report_date if metric is not None else holding_date
    if _is_stale(latest_date, as_of):
        lag = (as_of - latest_date).days if as_of and latest_date else 0
        notes.append(f"Latest issuer date is {lag} calendar days behind snapshot")
    return notes


def _is_stale(latest_date: date | None, as_of: date | None) -> bool:
    if latest_date is None or as_of is None:
        return False
    return (as_of - latest_date).days > 3


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


def _net_flow_values(series: Sequence[dict[str, object]]) -> list[float | None]:
    if not series:
        return []
    length = max(len(item["values"]) for item in series)
    values: list[float | None] = []
    for index in range(length):
        day_values = [
            float(item["values"][index])
            for item in series
            if item["values"][index] is not None
        ]
        values.append(round(sum(day_values), 3) if day_values else None)
    return values


def _exposure_adjusted_flow(
    flow: float | int | None,
    fund: EtfFundConfig,
) -> float | None:
    if flow is None:
        return None
    return float(flow) * fund.leverage


def _round_optional(value: float | None, *, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    rounded = round(float(value), digits)
    return int(rounded) if digits == 0 else rounded
