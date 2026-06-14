from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from energy_etf_monitor.records import (
    FundCrowdingMetric,
    FundDailyMetric,
    FundHolding,
    FuturesSettlement,
)
from energy_etf_monitor.storage.models import FundCrowdingMetricRow
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_fund_crowding_metric_upsert_is_idempotent(session: Session) -> None:
    repository = IngestionRepository(session)
    metric = FundCrowdingMetric(
        source="derived",
        fund_ticker="USO",
        commodity="WTI",
        product_code="CL",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        fund_total_net_assets=812_500_000,
        held_contract_count=16_200,
        open_interest_contracts=15_000,
        open_interest_notional=1_060_000_000,
        aum_to_open_interest_notional=0.7665,
        held_contracts_to_open_interest=1.08,
        matched_contract_months=2,
    )

    repository.upsert_fund_crowding_metrics([metric])
    result = repository.upsert_fund_crowding_metrics(
        [metric.model_copy(update={"aum_to_open_interest_notional": 0.8})]
    )
    rows = session.exec(select(FundCrowdingMetricRow)).all()

    assert result.updated == 1
    assert len(rows) == 1
    assert rows[0].aum_to_open_interest_notional == 0.8


def test_repository_derives_crowding_metric_from_loaded_rows(session: Session) -> None:
    repository = IngestionRepository(session)
    repository.upsert_fund_daily_metrics(
        [
            FundDailyMetric(
                source="uscf",
                fund_ticker="USO",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
                nav_per_share=81.25,
                shares_outstanding=10_000_000,
                total_net_assets=812_500_000,
            )
        ]
    )
    repository.upsert_fund_holdings(
        [
            FundHolding(
                source="uscf",
                fund_ticker="USO",
                holding_key="cl|2026-08-01|aug",
                holding_name="Crude Oil Future Aug 2026",
                instrument_type="Futures",
                ticker="CL",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
                contract_month=date(2026, 8, 1),
                quantity=8_500,
                market_value=345_000_000,
            )
        ]
    )
    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
                contract_month=date(2026, 8, 1),
                settlement_price=70,
                open_interest=10_000,
            )
        ]
    )

    metric = repository.derive_fund_crowding_metric(
        fund_ticker="USO",
        commodity="WTI",
        product_code="CL",
        report_date=date(2026, 6, 12),
    )

    assert metric.open_interest_notional == 700_000_000
    assert metric.held_contracts_to_open_interest == 0.85
