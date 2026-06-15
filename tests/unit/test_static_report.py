from datetime import UTC, date, datetime

from energy_etf_monitor.dashboard.static_report import render_dashboard_html
from energy_etf_monitor.records import CotPosition, DailyFeatureRow, NewsArticle


def _feature_row(report_date: date, price: float, cot: float, inventory: float) -> DailyFeatureRow:
    return DailyFeatureRow(
        source="test",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
        cl_front_month_settlement=price,
        cot_swap_dealer_net=cot,
        inventory_value=inventory,
        inventory_seasonal_surprise=0.5,
    )


def _cot(report_date: date) -> CotPosition:
    return CotPosition(
        source="cftc",
        commodity="WTI",
        market_name="CRUDE OIL, LIGHT SWEET",
        contract_market_code="067651",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
        open_interest=1_000_000,
        swap_dealer_long=90_000,
        swap_dealer_short=600_000,
        producer_merchant_long=690_000,
        producer_merchant_short=320_000,
        managed_money_long=210_000,
        managed_money_short=110_000,
        other_reportable_long=140_000,
        other_reportable_short=110_000,
    )


def _news(moment: datetime) -> NewsArticle:
    return NewsArticle(
        source="test",
        report_date=moment.date(),
        knowledge_date=moment,
        published_at=moment,
        url="https://example.com/article-1",
        url_hash="h1",
        title="OPEC cuts output",
        commodity="WTI",
        catalyst_type="supply",
        importance_score=88.0,
        impact_direction="Bullish",
        confidence=0.8,
    )


def test_render_dashboard_is_interactive_factor_view() -> None:
    as_of = datetime(2026, 6, 15, 12, tzinfo=UTC)
    days = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    rows = [_feature_row(day, 78.0 + i, -100000.0 - i, 420000.0 + i) for i, day in enumerate(days)]

    page = render_dashboard_html(
        commodity="WTI",
        feature_rows=rows,
        news=[_news(as_of)],
        as_of=as_of,
        cot_positions=[_cot(day) for day in days],
        commodities=("WTI", "NATGAS"),
    )

    assert page.startswith("<!doctype html>")
    assert "Energy price factors" in page
    assert "Not a price forecast" in page
    assert "ETF roll watch" in page and "USO" in page  # roll strategy + alert
    assert "Time range" in page  # global range selector
    assert '"price"' in page and "78.0" in page  # embedded price series for the JS charts
    assert "https://example.com/article-1" in page  # news url embedded for the JS to link
    assert 'target="_blank"' in page  # JS renders news titles as links opening in a new tab
    assert "OPEC cuts output" in page
    assert "<script>" in page  # interactive (vanilla JS, self-contained)
    assert "creation / redemption" in page.lower()  # ETF flow section present (even if empty early)
    # COT is now broken out by disaggregated trader type, not a single swap-dealer net.
    assert "Positioning by trader type" in page
    assert "Producer / merchant" in page and "Managed money" in page
    assert "370000" in page  # producer/merchant net (690000 - 320000) embedded
    assert "mousemove" in page  # hover tooltips wired
    # The prediction view is gone.
    assert "P(price up)" not in page and "Today's call" not in page


def test_render_dashboard_handles_empty_state() -> None:
    as_of = datetime(2026, 6, 15, 12, tzinfo=UTC)

    page = render_dashboard_html(commodity="WTI", feature_rows=[], news=[], as_of=as_of)

    assert "Energy price factors" in page
    assert '"news": []' in page  # empty series embed without crashing
    assert "ETF roll watch" in page
