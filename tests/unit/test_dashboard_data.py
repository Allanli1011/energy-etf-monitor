from datetime import UTC, date, datetime

from energy_etf_monitor.dashboard.data import (
    PRICE_AND_CURVE_COLUMNS,
    etf_exposure_rows,
    etf_flow_chart,
    etf_flow_rows,
    etf_strategy_summary_rows,
    feature_time_series,
    latest_call,
    news_panel_rows,
)
from energy_etf_monitor.etfs import etf_funds_for_commodity
from energy_etf_monitor.records import (
    DailyFeatureRow,
    DailyPrediction,
    FundDailyMetric,
    FundHolding,
    NewsArticle,
)


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


def _news(*, importance: float, hour: int, title: str) -> NewsArticle:
    published = datetime(2026, 6, 12, hour, tzinfo=UTC)
    return NewsArticle(
        source="gdelt",
        report_date=published.date(),
        knowledge_date=published,
        published_at=published,
        url="https://a.com/x",
        url_hash=f"hash-{title}",
        title=title,
        commodity="WTI",
        catalyst_type="opec",
        impact_direction="Bullish",
        importance_score=importance,
        confidence=0.6,
        rationale="opec catalyst",
    )


def test_news_panel_rows_sorts_by_importance_then_recency_and_projects_fields() -> None:
    rows = news_panel_rows(
        [
            _news(importance=50, hour=9, title="a"),
            _news(importance=90, hour=8, title="b"),
            _news(importance=90, hour=10, title="c"),
        ],
        limit=2,
    )

    # importance desc, then recency desc -> 90@10:00 (c), 90@08:00 (b); the 50 is dropped by limit
    assert [row["headline"] for row in rows] == ["c", "b"]
    assert rows[0]["importance"] == 90
    assert rows[0]["direction"] == "Bullish"
    assert rows[0]["commodity"] == "WTI"


def _metric(
    ticker: str,
    report_date: date,
    *,
    aum: float,
    flow: float | None,
    source: str = "yahoo_etf",
) -> FundDailyMetric:
    return FundDailyMetric(
        source=source,
        fund_ticker=ticker,
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
        nav_per_share=50.0,
        shares_outstanding=aum / 50.0,
        total_net_assets=aum,
        implied_flow_usd=flow,
    )


def _holding(
    ticker: str,
    contract_month: date,
    *,
    quantity: float,
    market_value: float | None = None,
    percent_nav: float | None = None,
) -> FundHolding:
    return FundHolding(
        source="uscf",
        fund_ticker=ticker,
        holding_key=f"{ticker}-{contract_month.isoformat()}",
        holding_name=f"{ticker} CL {contract_month:%b%y}",
        instrument_type="Future",
        ticker="CL",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, 18, tzinfo=UTC),
        contract_month=contract_month,
        quantity=quantity,
        market_value=market_value,
        percent_nav=percent_nav,
    )


def test_etf_flow_rows_project_latest_flow_and_rolling_pressure() -> None:
    funds = etf_funds_for_commodity("WTI")
    metrics = [
        _metric("USO", date(2026, 6, 8), aum=1_000_000_000, flow=10_000_000),
        _metric("USO", date(2026, 6, 9), aum=1_050_000_000, flow=20_000_000),
        _metric("USO", date(2026, 6, 10), aum=1_100_000_000, flow=-5_000_000),
        _metric("USL", date(2026, 6, 10), aum=200_000_000, flow=2_000_000),
        _metric("UCO", date(2026, 6, 10), aum=300_000_000, flow=15_000_000),
    ]

    rows = etf_flow_rows(metrics, funds=funds)

    uso = next(row for row in rows if row["ticker"] == "USO")
    assert uso["strategy"] == "front-month roll"
    assert uso["latest_aum_usd"] == 1_100_000_000
    assert uso["daily_flow_usd"] == -5_000_000
    assert uso["flow_pct_aum"] == -0.0045
    assert uso["flow_5d_usd"] == 25_000_000
    assert uso["leverage"] == 1.0

    # Leveraged funds are shown as sentiment/flow context, not model inputs.
    uco = next(row for row in rows if row["ticker"] == "UCO")
    assert uco["strategy"] == "2x leveraged"
    assert uco["model_input"] is False


def test_etf_flow_rows_prefer_official_issuer_metrics_over_yahoo_estimates() -> None:
    funds = etf_funds_for_commodity("WTI")
    metrics = [
        _metric("USO", date(2026, 6, 12), aum=900_000_000, flow=9_000_000),
        _metric(
            "USO",
            date(2026, 6, 12),
            aum=1_000_000_000,
            flow=10_000_000,
            source="uscf",
        ),
        _metric("DBO", date(2026, 6, 12), aum=200_000_000, flow=2_000_000),
        _metric(
            "DBO",
            date(2026, 6, 12),
            aum=265_000_000,
            flow=4_000_000,
            source="invesco",
        ),
        _metric("UCO", date(2026, 6, 12), aum=300_000_000, flow=3_000_000),
        _metric(
            "UCO",
            date(2026, 6, 12),
            aum=399_000_000,
            flow=5_000_000,
            source="proshares",
        ),
    ]

    rows = etf_flow_rows(metrics, funds=funds)

    uso = next(row for row in rows if row["ticker"] == "USO")
    assert uso["latest_aum_usd"] == 1_000_000_000
    assert uso["daily_flow_usd"] == 10_000_000
    dbo = next(row for row in rows if row["ticker"] == "DBO")
    assert dbo["latest_aum_usd"] == 265_000_000
    assert dbo["daily_flow_usd"] == 4_000_000
    uco = next(row for row in rows if row["ticker"] == "UCO")
    assert uco["latest_aum_usd"] == 399_000_000
    assert uco["daily_flow_usd"] == 5_000_000


def test_etf_strategy_summary_rows_aggregate_by_strategy_type() -> None:
    funds = etf_funds_for_commodity("WTI")
    metrics = [
        _metric("USO", date(2026, 6, 10), aum=1_100_000_000, flow=-5_000_000),
        _metric("USL", date(2026, 6, 10), aum=200_000_000, flow=2_000_000),
        _metric("UCO", date(2026, 6, 10), aum=300_000_000, flow=15_000_000),
        _metric("SCO", date(2026, 6, 10), aum=100_000_000, flow=-3_000_000),
    ]

    rows = etf_strategy_summary_rows(metrics, funds=funds)

    leveraged = next(row for row in rows if row["strategy"] == "2x leveraged")
    assert leveraged["fund_count"] == 1
    assert leveraged["aum_usd"] == 300_000_000
    assert leveraged["daily_flow_usd"] == 15_000_000

    front = next(row for row in rows if row["strategy"] == "front-month roll")
    assert front["funds"] == "USO"


def test_etf_exposure_rows_show_latest_contract_month_distribution() -> None:
    funds = etf_funds_for_commodity("WTI")
    metrics = [_metric("USO", date(2026, 6, 12), aum=1_000_000_000, flow=1_000_000)]
    holdings = [
        _holding("USO", date(2026, 7, 1), quantity=10_000, market_value=700_000_000),
        _holding("USO", date(2026, 8, 1), quantity=2_000, percent_nav=12.5),
    ]

    rows = etf_exposure_rows(holdings, metrics=metrics, funds=funds)

    assert [row["contract_month"] for row in rows] == ["2026-07", "2026-08"]
    assert rows[0]["quantity"] == 10_000
    assert rows[0]["percent_nav"] == 70.0
    assert rows[1]["percent_nav"] == 12.5


def test_etf_flow_chart_aligns_multiple_funds_by_date() -> None:
    funds = etf_funds_for_commodity("WTI")
    metrics = [
        _metric("USO", date(2026, 6, 10), aum=1_000_000_000, flow=5_000_000),
        _metric("USO", date(2026, 6, 11), aum=1_000_000_000, flow=6_000_000),
        _metric("USL", date(2026, 6, 11), aum=200_000_000, flow=-1_000_000),
    ]

    chart = etf_flow_chart(metrics, funds=funds)

    assert chart["dates"] == ["2026-06-10", "2026-06-11"]
    assert chart["series"][0] == {"name": "USO", "values": [5.0, 6.0]}
    assert chart["series"][1] == {"name": "USL", "values": [None, -1.0]}
