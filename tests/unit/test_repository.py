from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from energy_etf_monitor.records import CotPosition, FuturesSettlement, TimeSeriesObservation
from energy_etf_monitor.storage.models import (
    CotPositionRow,
    FuturesSettlementRow,
    TimeSeriesObservationRow,
)
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_time_series_upsert_is_idempotent_and_updates_existing_row(session: Session) -> None:
    repository = IngestionRepository(session)
    first = TimeSeriesObservation(
        source="fred",
        series_id="DTWEXBGS",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        value=98.75,
    )
    second = first.model_copy(
        update={
            "knowledge_date": datetime(2026, 6, 13, 1, tzinfo=UTC),
            "value": 99.01,
        }
    )

    first_result = repository.upsert_time_series([first])
    second_result = repository.upsert_time_series([second])
    rows = session.exec(select(TimeSeriesObservationRow)).all()

    assert first_result.inserted == 1
    assert second_result.updated == 1
    assert len(rows) == 1
    assert rows[0].value == 99.01
    assert rows[0].knowledge_date == datetime(2026, 6, 13, 1)


def test_cot_upsert_applies_quality_gate_before_persisting(session: Session) -> None:
    repository = IngestionRepository(session)
    record = CotPosition(
        source="cftc",
        commodity="WTI",
        market_name="CRUDE OIL, LIGHT SWEET",
        contract_market_code="067651",
        report_date=date(2026, 6, 9),
        knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
        open_interest=-10,
    )

    result = repository.upsert_cot_positions([record])
    row = session.exec(select(CotPositionRow)).one()

    assert result.inserted == 1
    assert result.quarantined == 1
    assert row.quarantine is True


def test_futures_settlement_upsert_uses_contract_month_in_natural_key(session: Session) -> None:
    repository = IngestionRepository(session)
    report_date = date(2026, 6, 12)
    knowledge_date = datetime(2026, 6, 13, tzinfo=UTC)

    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date,
                contract_month=date(2026, 7, 1),
                settlement_price=73.25,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date + timedelta(minutes=1),
                contract_month=date(2026, 8, 1),
                settlement_price=72.95,
            ),
        ]
    )
    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date + timedelta(minutes=2),
                contract_month=date(2026, 7, 1),
                settlement_price=73.50,
            )
        ]
    )
    rows = session.exec(
        select(FuturesSettlementRow).order_by(FuturesSettlementRow.contract_month)
    ).all()

    assert len(rows) == 2
    assert [row.settlement_price for row in rows] == [73.50, 72.95]
