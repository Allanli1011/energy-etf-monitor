import json
from datetime import UTC, date, datetime

from energy_etf_monitor.dashboard.static_report import render_dashboard_html
from energy_etf_monitor.modeling.monitoring import ModelHealthReport
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction, NewsArticle


def _feature_row(report_date: date, price: float) -> DailyFeatureRow:
    return DailyFeatureRow(
        source="test",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
        cl_front_month_settlement=price,
        cl_m1_m2_spread=0.3,
        cot_swap_dealer_net=-100_000.0,
        inventory_value=420_000.0,
    )


def _prediction(report_date: date) -> DailyPrediction:
    return DailyPrediction(
        source="test",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
        horizon_days=5,
        feature_report_date=report_date,
        price_up_probability=0.62,
        spread_up_probability=0.44,
        price_model_version="v1",
        spread_model_version="v1",
        price_top_drivers=json.dumps([{"feature": "cl_carry_m1_m2", "contribution": 0.8}]),
        spread_top_drivers=json.dumps(
            [{"feature": "cot_swap_dealer_net_index", "contribution": -0.3}]
        ),
        price_naive_probability=1.0,
        spread_naive_probability=0.0,
    )


def _news(moment: datetime) -> NewsArticle:
    return NewsArticle(
        source="test",
        report_date=moment.date(),
        knowledge_date=moment,
        published_at=moment,
        url="https://example.com/1",
        url_hash="h1",
        title="OPEC cuts output",
        commodity="WTI",
        catalyst_type="supply",
        importance_score=88.0,
        impact_direction="Bullish",
        confidence=0.8,
    )


def test_render_dashboard_html_is_self_contained_and_populated() -> None:
    as_of = datetime(2026, 6, 15, 12, tzinfo=UTC)
    days = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    feature_rows = [_feature_row(day, 78.0 + index) for index, day in enumerate(days)]
    health = ModelHealthReport(
        commodity="WTI",
        outcomes=[],
        metrics={"price_model_accuracy": 0.57},
        regime_metrics={},
        rolling_metrics={},
    )

    html_doc = render_dashboard_html(
        commodity="WTI",
        predictions=[_prediction(days[-1])],
        feature_rows=feature_rows,
        news=[_news(as_of)],
        health=health,
        as_of=as_of,
        commodities=("WTI", "NATGAS"),
    )

    assert html_doc.startswith("<!doctype html>")
    assert "Energy ETF monitor" in html_doc
    assert "OPEC cuts output" in html_doc  # news rendered
    assert "P(price up)" in html_doc and "0.62" in html_doc  # today's call
    assert "<svg" in html_doc  # inline SVG charts
    assert "price_model_accuracy" in html_doc  # model health
    assert 'href="natgas.html"' in html_doc  # nav link to sibling commodity
    assert "<script" not in html_doc  # truly static — no JavaScript


def test_render_dashboard_html_handles_empty_state() -> None:
    as_of = datetime(2026, 6, 15, 12, tzinfo=UTC)
    health = ModelHealthReport(
        commodity="WTI", outcomes=[], metrics={}, regime_metrics={}, rolling_metrics={}
    )

    html_doc = render_dashboard_html(
        commodity="WTI",
        predictions=[],
        feature_rows=[],
        news=[],
        health=health,
        as_of=as_of,
    )

    assert "No predictions yet." in html_doc
    assert "No classified news yet." in html_doc
    assert "no data yet" in html_doc  # empty charts render a placeholder, not a crash
    assert "<script" not in html_doc
