from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from energy_etf_monitor.commodities import NATGAS
from energy_etf_monitor.records import CotPosition, FuturesSettlement, TimeSeriesObservation
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_derive_feature_row_generalizes_to_natgas(session: Session) -> None:
    repository = IngestionRepository(session)
    as_of = datetime(2026, 6, 12, 20, tzinfo=UTC)

    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="NG",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
                contract_month=date(2026, 7, 1),
                settlement_price=3.50,
                open_interest=50_000,
            ),
            FuturesSettlement(
                source="cme",
                product_code="NG",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
                contract_month=date(2026, 8, 1),
                settlement_price=3.60,
                open_interest=40_000,
            ),
        ]
    )
    repository.upsert_cot_positions(
        [
            CotPosition(
                source="cftc",
                commodity="NATGAS",
                market_name="NATURAL GAS",
                contract_market_code="023651",
                report_date=date(2026, 6, 9),
                knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
                open_interest=100_000,
                swap_dealer_long=20_000,
                swap_dealer_short=15_000,
            )
        ]
    )
    repository.upsert_time_series(
        [
            TimeSeriesObservation(
                source="eia",
                series_id="NG.NW2_EPG0_SWO_R48_BCF.W",
                report_date=date(2026, 6, 6),
                knowledge_date=datetime(2026, 6, 11, 16, tzinfo=UTC),
                value=2_500.0,
            )
        ]
    )

    row = repository.derive_feature_row(config=NATGAS, as_of=as_of)

    assert row.commodity == "NATGAS"
    assert row.cl_front_month_settlement == 3.50
    assert row.cl_m1_m2_spread == pytest.approx(-0.10)
    assert row.cot_swap_dealer_net == 5_000.0
    assert row.inventory_value == 2_500.0
    # No UNG crowding data loaded -> crowding features stay None (optional).
    assert row.crowding_aum_to_oi is None


def test_derive_feature_row_excludes_natgas_cot_not_yet_published(session: Session) -> None:
    repository = IngestionRepository(session)
    # Decision at 18:00 UTC is before the COT 19:30 UTC release -> COT must be excluded.
    as_of = datetime(2026, 6, 12, 18, tzinfo=UTC)

    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="NG",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
                contract_month=date(2026, 7, 1),
                settlement_price=3.50,
                open_interest=50_000,
            )
        ]
    )
    repository.upsert_cot_positions(
        [
            CotPosition(
                source="cftc",
                commodity="NATGAS",
                market_name="NATURAL GAS",
                contract_market_code="023651",
                report_date=date(2026, 6, 9),
                knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
                open_interest=100_000,
                swap_dealer_long=20_000,
                swap_dealer_short=15_000,
            )
        ]
    )

    row = repository.derive_feature_row(config=NATGAS, as_of=as_of)

    assert row.commodity == "NATGAS"
    assert row.cot_swap_dealer_net is None
