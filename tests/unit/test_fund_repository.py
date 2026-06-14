from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from energy_etf_monitor.records import FundDailyMetric, FundHolding
from energy_etf_monitor.storage.models import FundDailyMetricRow, FundHoldingRow
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _metric(report_date: date, shares: float, nav: float = 80.0) -> FundDailyMetric:
    return FundDailyMetric(
        source="uscf",
        fund_ticker="USO",
        report_date=report_date,
        knowledge_date=datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
        nav_per_share=nav,
        shares_outstanding=shares,
        total_net_assets=shares * nav,
    )


def test_fund_metric_upsert_derives_implied_flow_from_previous_row(session: Session) -> None:
    repository = IngestionRepository(session)

    repository.upsert_fund_daily_metrics([_metric(date(2026, 6, 11), shares=9_500_000, nav=80)])
    result = repository.upsert_fund_daily_metrics(
        [_metric(date(2026, 6, 12), shares=10_000_000, nav=81.25)]
    )
    rows = session.exec(select(FundDailyMetricRow).order_by(FundDailyMetricRow.report_date)).all()

    assert result.inserted == 1
    assert len(rows) == 2
    assert rows[1].implied_flow_usd == 40_625_000


def test_fund_holding_upsert_is_idempotent_by_holding_key(session: Session) -> None:
    repository = IngestionRepository(session)
    holding = FundHolding(
        source="uscf",
        fund_ticker="USO",
        holding_key="cl|2026-08-01|crude_oil_future_aug_2026",
        holding_name="Crude Oil Future Aug 2026",
        instrument_type="Futures",
        ticker="CL",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        contract_month=date(2026, 8, 1),
        quantity=8_500,
        market_value=345_000_000,
        percent_nav=42.46,
    )

    repository.upsert_fund_holdings([holding])
    result = repository.upsert_fund_holdings(
        [holding.model_copy(update={"quantity": 8_750, "market_value": 350_000_000})]
    )
    rows = session.exec(select(FundHoldingRow)).all()

    assert result.updated == 1
    assert len(rows) == 1
    assert rows[0].quantity == 8_750
    assert rows[0].market_value == 350_000_000

