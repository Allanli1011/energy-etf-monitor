from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _feature_row(report_date: date, knowledge_date: datetime, **overrides) -> DailyFeatureRow:
    base = dict(
        source="feature_pipeline",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=knowledge_date,
        cl_front_month_settlement=70.0,
        cl_m1_m2_spread=-0.5,
        cl_carry_m1_m2=0.01,
    )
    base.update(overrides)
    return DailyFeatureRow(**base)


def _prediction(report_date: date, knowledge_date: datetime, **overrides) -> DailyPrediction:
    base = dict(
        source="prediction_pipeline",
        commodity="WTI",
        report_date=report_date,
        knowledge_date=knowledge_date,
        horizon_days=5,
        feature_report_date=report_date,
        price_up_probability=0.6,
        spread_up_probability=0.4,
        price_model_version="logistic_regression:price_direction:h5:through2026-06-01:n100",
        spread_model_version="logistic_regression:spread_direction:h5:through2026-06-01:n100",
        price_top_drivers="[]",
        spread_top_drivers="[]",
    )
    base.update(overrides)
    return DailyPrediction(**base)


def test_latest_daily_feature_row_respects_knowledge_date(session: Session) -> None:
    repository = IngestionRepository(session)
    repository.upsert_daily_feature_rows(
        [
            _feature_row(date(2026, 6, 10), datetime(2026, 6, 10, 16, tzinfo=UTC)),
            _feature_row(date(2026, 6, 12), datetime(2026, 6, 12, 16, tzinfo=UTC)),
        ]
    )

    # Before the 6/12 settlement publishes (16:00), only the 6/10 row is known.
    early = repository.latest_daily_feature_row(
        commodity="WTI",
        as_of=datetime(2026, 6, 12, 9, tzinfo=UTC),
    )
    assert early is not None
    assert early.report_date == date(2026, 6, 10)

    late = repository.latest_daily_feature_row(
        commodity="WTI",
        as_of=datetime(2026, 6, 12, 18, tzinfo=UTC),
    )
    assert late is not None
    assert late.report_date == date(2026, 6, 12)


def test_latest_daily_feature_row_returns_none_when_empty(session: Session) -> None:
    repository = IngestionRepository(session)
    assert (
        repository.latest_daily_feature_row(
            commodity="WTI",
            as_of=datetime(2026, 6, 12, 18, tzinfo=UTC),
        )
        is None
    )


def test_upsert_daily_predictions_is_idempotent_on_natural_key(session: Session) -> None:
    repository = IngestionRepository(session)
    first = repository.upsert_daily_predictions(
        [_prediction(date(2026, 6, 12), datetime(2026, 6, 12, 18, tzinfo=UTC))]
    )
    assert (first.inserted, first.updated) == (1, 0)

    second = repository.upsert_daily_predictions(
        [
            _prediction(
                date(2026, 6, 12),
                datetime(2026, 6, 12, 19, tzinfo=UTC),
                price_up_probability=0.71,
            )
        ]
    )
    assert (second.inserted, second.updated) == (0, 1)

    stored = repository.list_daily_predictions(commodity="WTI")
    assert len(stored) == 1
    assert stored[0].price_up_probability == 0.71


def test_upsert_daily_predictions_quarantines_out_of_range_probability(session: Session) -> None:
    repository = IngestionRepository(session)
    result = repository.upsert_daily_predictions(
        [
            _prediction(
                date(2026, 6, 12),
                datetime(2026, 6, 12, 18, tzinfo=UTC),
                price_up_probability=1.4,
            )
        ]
    )
    assert result.quarantined == 1
    stored = repository.list_daily_predictions(commodity="WTI")
    assert stored[0].quarantine is True
