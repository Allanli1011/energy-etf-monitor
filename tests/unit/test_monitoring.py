from datetime import UTC, date, datetime

from energy_etf_monitor.modeling.monitoring import (
    build_model_health_report,
    export_model_health_report,
)
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction


def _feature_row(report_date: date, *, settle: float, spread: float) -> DailyFeatureRow:
    return DailyFeatureRow(
        source="feature_pipeline",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time()).replace(
            hour=16, tzinfo=UTC
        ),
        cl_front_month_settlement=settle,
        cl_m1_m2_spread=spread,
    )


def _prediction(
    report_date: date,
    *,
    price_prob: float,
    spread_prob: float,
    price_naive: float | None = None,
    spread_naive: float | None = None,
    horizon_days: int = 2,
    quarantine: bool = False,
) -> DailyPrediction:
    return DailyPrediction(
        source="prediction_pipeline",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time()).replace(
            hour=18, tzinfo=UTC
        ),
        horizon_days=horizon_days,
        feature_report_date=report_date,
        price_up_probability=price_prob,
        spread_up_probability=spread_prob,
        price_naive_probability=price_naive,
        spread_naive_probability=spread_naive,
        price_model_version="logistic_regression:price_direction:h2:through2026-06-01:n10",
        spread_model_version="logistic_regression:spread_direction:h2:through2026-06-01:n10",
        price_top_drivers="[]",
        spread_top_drivers="[]",
        quarantine=quarantine,
    )


FEATURE_ROWS = [
    _feature_row(date(2026, 6, 1), settle=70, spread=-2),
    _feature_row(date(2026, 6, 2), settle=71, spread=-1),
    _feature_row(date(2026, 6, 3), settle=69, spread=-3),
    _feature_row(date(2026, 6, 4), settle=73, spread=1),
]


def test_model_health_scores_realized_outcomes_against_naive() -> None:
    predictions = [
        # 6/1 -> 6/3: settle 70->69 (down), spread -2->-3 (down). Model predicts down -> correct.
        _prediction(date(2026, 6, 1), price_prob=0.3, spread_prob=0.2, price_naive=1.0),
        # 6/2 -> 6/4: settle 71->73 (up), spread -1->1 (up). Model predicts up -> correct.
        _prediction(date(2026, 6, 2), price_prob=0.8, spread_prob=0.9, price_naive=1.0),
    ]

    report = build_model_health_report(
        predictions,
        FEATURE_ROWS,
        as_of=datetime(2026, 6, 4, 18, tzinfo=UTC),
    )

    assert len(report.outcomes) == 2
    assert report.metrics["price_model_accuracy"] == 1.0
    assert report.metrics["spread_model_accuracy"] == 1.0
    # naive said "up" both times; realized down then up -> naive accuracy 0.5
    assert report.metrics["price_naive_accuracy"] == 0.5
    assert report.metrics["price_model_minus_naive_accuracy"] == 0.5
    assert [outcome.price_realized_up for outcome in report.outcomes] == [False, True]


def test_model_health_excludes_outcomes_not_yet_known_as_of() -> None:
    predictions = [
        _prediction(date(2026, 6, 1), price_prob=0.3, spread_prob=0.2),
        _prediction(date(2026, 6, 2), price_prob=0.8, spread_prob=0.9),
    ]

    # As of 6/3 18:00 the 6/2 prediction's outcome row (6/4, known 6/4 16:00) is not yet known.
    report = build_model_health_report(
        predictions,
        FEATURE_ROWS,
        as_of=datetime(2026, 6, 3, 18, tzinfo=UTC),
    )

    assert [outcome.report_date for outcome in report.outcomes] == [date(2026, 6, 1)]


def test_model_health_skips_quarantined_predictions() -> None:
    predictions = [
        _prediction(date(2026, 6, 1), price_prob=0.3, spread_prob=0.2, quarantine=True),
        _prediction(date(2026, 6, 2), price_prob=0.8, spread_prob=0.9),
    ]

    report = build_model_health_report(
        predictions,
        FEATURE_ROWS,
        as_of=datetime(2026, 6, 4, 18, tzinfo=UTC),
    )

    assert [outcome.report_date for outcome in report.outcomes] == [date(2026, 6, 2)]


def test_export_model_health_report_writes_outcomes_and_metrics(tmp_path) -> None:
    predictions = [_prediction(date(2026, 6, 1), price_prob=0.3, spread_prob=0.2)]
    report = build_model_health_report(
        predictions,
        FEATURE_ROWS,
        as_of=datetime(2026, 6, 4, 18, tzinfo=UTC),
    )

    exported = export_model_health_report(report, tmp_path)

    assert exported.outcomes_path.exists()
    assert exported.metrics_path.exists()
    assert "price_realized_up" in exported.outcomes_path.read_text()
    assert "price_model_accuracy" in exported.metrics_path.read_text()
