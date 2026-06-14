from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from energy_etf_monitor.records import (
    CotPosition,
    DailyFeatureRow,
    FundCrowdingMetric,
    FuturesSettlement,
    TimeSeriesObservation,
)
from energy_etf_monitor.storage.models import DailyFeatureRowModel
from energy_etf_monitor.storage.repository import IngestionRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_repository_derives_wti_features_with_point_in_time_cutoff(session: Session) -> None:
    repository = IngestionRepository(session)
    as_of = datetime(2026, 6, 12, 18, tzinfo=UTC)
    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
                contract_month=date(2026, 7, 1),
                settlement_price=70,
                open_interest=100_000,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 16, 1, tzinfo=UTC),
                contract_month=date(2026, 8, 1),
                settlement_price=72,
                open_interest=90_000,
            ),
        ]
    )
    repository.upsert_cot_positions(
        [
            CotPosition(
                source="cftc",
                commodity="WTI",
                market_name="CRUDE OIL, LIGHT SWEET",
                contract_market_code="067651",
                report_date=date(2026, 6, 2),
                knowledge_date=datetime(2026, 6, 5, 19, 30, tzinfo=UTC),
                open_interest=1_000,
                swap_dealer_long=500,
                swap_dealer_short=200,
            ),
            CotPosition(
                source="cftc",
                commodity="WTI",
                market_name="CRUDE OIL, LIGHT SWEET",
                contract_market_code="067651",
                report_date=date(2026, 6, 9),
                knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
                open_interest=2_000,
                swap_dealer_long=900,
                swap_dealer_short=100,
            ),
        ]
    )
    repository.upsert_time_series(
        [
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=date(2026, 6, 6),
                knowledge_date=datetime(2026, 6, 12, 15, tzinfo=UTC),
                value=420_000,
                unit="thousand barrels",
            ),
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=date(2026, 6, 13),
                knowledge_date=datetime(2026, 6, 13, 15, tzinfo=UTC),
                value=999_000,
                unit="thousand barrels",
            ),
            TimeSeriesObservation(
                source="fred",
                series_id="DTWEXBGS",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 10, tzinfo=UTC),
                value=104.5,
            ),
            TimeSeriesObservation(
                source="fred",
                series_id="DFII10",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 10, 1, tzinfo=UTC),
                value=1.85,
            ),
        ]
    )
    repository.upsert_fund_crowding_metrics(
        [
            FundCrowdingMetric(
                source="derived",
                fund_ticker="USO",
                commodity="WTI",
                product_code="CL",
                report_date=date(2026, 6, 12),
                knowledge_date=datetime(2026, 6, 12, 17, 30, tzinfo=UTC),
                fund_total_net_assets=800_000_000,
                held_contract_count=12_000,
                open_interest_contracts=190_000,
                open_interest_notional=13_400_000_000,
                aum_to_open_interest_notional=0.0597,
                held_contracts_to_open_interest=0.0632,
                matched_contract_months=2,
            )
        ]
    )

    feature_row = repository.derive_wti_feature_row(as_of=as_of)

    assert feature_row.source == "feature_pipeline"
    assert feature_row.commodity == "WTI"
    assert feature_row.report_date == as_of.date()
    assert feature_row.knowledge_date == datetime(2026, 6, 12, 17, 30)
    assert feature_row.cl_carry_m1_m2 == pytest.approx((70 - 72) / 70)
    assert feature_row.cot_swap_dealer_net == 300
    assert feature_row.cot_open_interest == 1_000
    assert feature_row.inventory_value == 420_000
    assert feature_row.usd_index_value == 104.5
    assert feature_row.real_yield_10y == 1.85
    assert feature_row.crowding_aum_to_oi == 0.0597
    assert feature_row.crowding_contracts_to_oi == 0.0632


def test_repository_derives_curve_shape_and_front_month_return_features(
    session: Session,
) -> None:
    repository = IngestionRepository(session)
    previous_date = date(2026, 6, 11)
    report_date = date(2026, 6, 12)
    knowledge_date = datetime(2026, 6, 12, 16, tzinfo=UTC)
    repository.upsert_futures_settlements(
        [
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=previous_date,
                knowledge_date=datetime(2026, 6, 11, 16, tzinfo=UTC),
                contract_month=date(2026, 7, 1),
                settlement_price=69,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=previous_date,
                knowledge_date=datetime(2026, 6, 11, 16, 1, tzinfo=UTC),
                contract_month=date(2026, 8, 1),
                settlement_price=71,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date,
                contract_month=date(2026, 7, 1),
                settlement_price=70,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date,
                contract_month=date(2026, 8, 1),
                settlement_price=72,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date,
                contract_month=date(2026, 9, 1),
                settlement_price=75,
            ),
            FuturesSettlement(
                source="cme",
                product_code="CL",
                report_date=report_date,
                knowledge_date=knowledge_date,
                contract_month=date(2026, 12, 1),
                settlement_price=80,
            ),
        ]
    )

    feature_row = repository.derive_wti_feature_row(
        as_of=datetime(2026, 6, 12, 18, tzinfo=UTC),
    )

    previous_carry = (69 - 71) / 69
    assert feature_row.cl_front_month_settlement == 70
    assert feature_row.cl_m1_m2_spread == -2
    assert feature_row.cl_m2_m3_spread == -3
    assert feature_row.cl_m3_m6_spread == -5
    assert feature_row.cl_curve_curvature_m1_m2_m3 == 1
    assert feature_row.cl_front_month_return_1d == pytest.approx((70 / 69) - 1)
    assert feature_row.cl_carry_m1_m2_change_1d == pytest.approx(
        feature_row.cl_carry_m1_m2 - previous_carry
    )


def test_daily_feature_row_upsert_is_idempotent(session: Session) -> None:
    repository = IngestionRepository(session)
    record = DailyFeatureRow(
        source="feature_pipeline",
        commodity="WTI",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, 17, tzinfo=UTC),
        cl_carry_m1_m2=-0.01,
        cot_swap_dealer_net=300,
        cot_open_interest=1_000,
        inventory_value=420_000,
        usd_index_value=104.5,
        real_yield_10y=1.85,
        crowding_aum_to_oi=0.05,
        crowding_contracts_to_oi=0.06,
    )

    repository.upsert_daily_feature_rows([record])
    result = repository.upsert_daily_feature_rows(
        [record.model_copy(update={"cl_carry_m1_m2": -0.02})]
    )
    rows = session.exec(select(DailyFeatureRowModel)).all()

    assert result.updated == 1
    assert len(rows) == 1
    assert rows[0].cl_carry_m1_m2 == -0.02


def test_repository_derives_phase_two_history_features_without_future_leakage(
    session: Session,
) -> None:
    repository = IngestionRepository(session)
    as_of = datetime(2026, 6, 8, 18, tzinfo=UTC)
    latest_inventory_date = date(2026, 6, 6)
    latest_inventory_week = latest_inventory_date.isocalendar().week
    prior_inventory_2024 = date.fromisocalendar(2024, latest_inventory_week, 6)
    prior_inventory_2025 = date.fromisocalendar(2025, latest_inventory_week, 6)
    repository.upsert_time_series(
        [
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=prior_inventory_2024,
                knowledge_date=datetime.combine(
                    prior_inventory_2024 + timedelta(days=1),
                    time(15, tzinfo=UTC),
                ),
                value=400_000,
            ),
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=prior_inventory_2025,
                knowledge_date=datetime.combine(
                    prior_inventory_2025 + timedelta(days=1),
                    time(15, tzinfo=UTC),
                ),
                value=410_000,
            ),
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=latest_inventory_date,
                knowledge_date=datetime(2026, 6, 6, 15, tzinfo=UTC),
                value=420_000,
            ),
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=date(2026, 6, 13),
                knowledge_date=datetime(2026, 6, 13, 15, tzinfo=UTC),
                value=999_000,
            ),
        ]
    )
    for offset, net_position in enumerate((100, 200, 300)):
        report_date = date(2026, 5, 19) + timedelta(days=7 * offset)
        repository.upsert_cot_positions(
            [
                CotPosition(
                    source="cftc",
                    commodity="WTI",
                    market_name="CRUDE OIL, LIGHT SWEET",
                    contract_market_code="067651",
                    report_date=report_date,
                    knowledge_date=datetime.combine(
                        report_date + timedelta(days=3),
                        time(19, 30, tzinfo=UTC),
                    ),
                    open_interest=1_000,
                    swap_dealer_long=500 + net_position,
                    swap_dealer_short=500,
                )
            ]
        )
    repository.upsert_cot_positions(
        [
            CotPosition(
                source="cftc",
                commodity="WTI",
                market_name="CRUDE OIL, LIGHT SWEET",
                contract_market_code="067651",
                report_date=date(2026, 6, 9),
                knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
                open_interest=1_000,
                swap_dealer_long=9_999,
                swap_dealer_short=0,
            )
        ]
    )
    repository.upsert_fund_crowding_metrics(
        [
            FundCrowdingMetric(
                source="derived",
                fund_ticker="USO",
                commodity="WTI",
                product_code="CL",
                report_date=date(2026, 6, 8),
                knowledge_date=datetime(2026, 6, 8, 17, tzinfo=UTC),
                fund_total_net_assets=800_000_000,
                held_contract_count=12_000,
                open_interest_contracts=190_000,
                open_interest_notional=13_400_000_000,
                aum_to_open_interest_notional=0.05,
                held_contracts_to_open_interest=0.06,
                matched_contract_months=2,
            )
        ]
    )

    feature_row = repository.derive_wti_feature_row(as_of=as_of)

    assert feature_row.inventory_seasonal_surprise == pytest.approx(15_000)
    assert feature_row.cot_swap_dealer_net == 300
    assert feature_row.cot_swap_dealer_net_zscore == pytest.approx(1.224744871)
    assert feature_row.cot_swap_dealer_net_index == 100
    assert feature_row.roll_window_flag == 1
    assert feature_row.roll_window_crowding_interaction == pytest.approx(0.05)


def test_repository_respects_known_eia_and_cot_release_times(session: Session) -> None:
    repository = IngestionRepository(session)
    repository.upsert_time_series(
        [
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=date(2026, 5, 30),
                knowledge_date=datetime(2026, 6, 3, 14, 30, tzinfo=UTC),
                value=410_000,
            ),
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=date(2026, 6, 6),
                knowledge_date=datetime(2026, 6, 10, 14, 30, tzinfo=UTC),
                value=420_000,
            ),
        ]
    )
    repository.upsert_cot_positions(
        [
            CotPosition(
                source="cftc",
                commodity="WTI",
                market_name="CRUDE OIL, LIGHT SWEET",
                contract_market_code="067651",
                report_date=date(2026, 6, 2),
                knowledge_date=datetime(2026, 6, 5, 19, 30, tzinfo=UTC),
                open_interest=1_000,
                swap_dealer_long=800,
                swap_dealer_short=500,
            ),
            CotPosition(
                source="cftc",
                commodity="WTI",
                market_name="CRUDE OIL, LIGHT SWEET",
                contract_market_code="067651",
                report_date=date(2026, 6, 9),
                knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
                open_interest=2_000,
                swap_dealer_long=1_300,
                swap_dealer_short=500,
            ),
        ]
    )

    before_eia_release = repository.derive_wti_feature_row(
        as_of=datetime(2026, 6, 10, 14, tzinfo=UTC),
    )
    after_eia_release = repository.derive_wti_feature_row(
        as_of=datetime(2026, 6, 10, 15, tzinfo=UTC),
    )
    before_cot_release = repository.derive_wti_feature_row(
        as_of=datetime(2026, 6, 12, 18, tzinfo=UTC),
    )
    after_cot_release = repository.derive_wti_feature_row(
        as_of=datetime(2026, 6, 12, 20, tzinfo=UTC),
    )

    assert before_eia_release.inventory_value == 410_000
    assert after_eia_release.inventory_value == 420_000
    assert before_cot_release.cot_swap_dealer_net == 300
    assert after_cot_release.cot_swap_dealer_net == 800


def test_repository_derives_wti_feature_rows_for_date_range(session: Session) -> None:
    repository = IngestionRepository(session)
    repository.upsert_time_series(
        [
            TimeSeriesObservation(
                source="eia",
                series_id="WCESTUS1",
                report_date=date(2026, 6, 1),
                knowledge_date=datetime(2026, 6, 1, 15, tzinfo=UTC),
                value=420_000,
            )
        ]
    )

    rows = repository.derive_wti_feature_rows(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        as_of_time=time(18, tzinfo=UTC),
    )

    assert [row.report_date for row in rows] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 6, 3),
    ]
