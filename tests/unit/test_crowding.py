from datetime import UTC, date, datetime

import pytest

from energy_etf_monitor.features.crowding import derive_fund_crowding_metric
from energy_etf_monitor.records import FundDailyMetric, FundHolding, FuturesSettlement


def _metric() -> FundDailyMetric:
    return FundDailyMetric(
        source="uscf",
        fund_ticker="USO",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        nav_per_share=81.25,
        shares_outstanding=10_000_000,
        total_net_assets=812_500_000,
    )


def test_derive_fund_crowding_metric_uses_matching_held_contract_months() -> None:
    holdings = [
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
        ),
        FundHolding(
            source="uscf",
            fund_ticker="USO",
            holding_key="cl|2026-09-01|sep",
            holding_name="Crude Oil Future Sep 2026",
            instrument_type="Futures",
            ticker="CL",
            report_date=date(2026, 6, 12),
            knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
            contract_month=date(2026, 9, 1),
            quantity=7_700,
            market_value=302_000_000,
        ),
        FundHolding(
            source="uscf",
            fund_ticker="USO",
            holding_key="usd|na|cash",
            holding_name="Cash",
            instrument_type="Cash",
            ticker="USD",
            report_date=date(2026, 6, 12),
            knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
            market_value=165_500_000,
        ),
    ]
    settlements = [
        FuturesSettlement(
            source="cme",
            product_code="CL",
            report_date=date(2026, 6, 12),
            knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
            contract_month=date(2026, 8, 1),
            settlement_price=70,
            open_interest=10_000,
        ),
        FuturesSettlement(
            source="cme",
            product_code="CL",
            report_date=date(2026, 6, 12),
            knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
            contract_month=date(2026, 9, 1),
            settlement_price=72,
            open_interest=5_000,
        ),
    ]

    metric = derive_fund_crowding_metric(
        fund_metric=_metric(),
        holdings=holdings,
        settlements=settlements,
        commodity="WTI",
        product_code="CL",
    )

    assert metric.report_date == date(2026, 6, 12)
    assert metric.held_contract_count == 16_200
    assert metric.open_interest_contracts == 15_000
    assert metric.open_interest_notional == 1_060_000_000
    assert metric.aum_to_open_interest_notional == pytest.approx(0.7665094)
    assert metric.held_contracts_to_open_interest == pytest.approx(1.08)
    assert metric.matched_contract_months == 2


def test_derive_fund_crowding_metric_raises_when_no_matching_open_interest() -> None:
    with pytest.raises(ValueError, match="No matching open interest"):
        derive_fund_crowding_metric(
            fund_metric=_metric(),
            holdings=[],
            settlements=[],
            commodity="WTI",
            product_code="CL",
        )

