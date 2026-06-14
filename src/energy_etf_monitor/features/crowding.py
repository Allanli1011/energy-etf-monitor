from datetime import datetime

from energy_etf_monitor.records import (
    FundCrowdingMetric,
    FundDailyMetric,
    FundHolding,
    FuturesSettlement,
)

CONTRACT_MULTIPLIERS = {
    "CL": 1_000.0,
}


def derive_fund_crowding_metric(
    *,
    fund_metric: FundDailyMetric,
    holdings: list[FundHolding],
    settlements: list[FuturesSettlement],
    commodity: str,
    product_code: str,
    contract_multiplier: float | None = None,
) -> FundCrowdingMetric:
    product = product_code.upper()
    multiplier = contract_multiplier or CONTRACT_MULTIPLIERS.get(product, 1.0)
    matching_holdings = [
        holding
        for holding in holdings
        if (holding.ticker or "").upper() == product and holding.contract_month is not None
    ]
    held_months = {holding.contract_month for holding in matching_holdings}
    matching_settlements = [
        settlement
        for settlement in settlements
        if settlement.product_code.upper() == product
        and settlement.contract_month in held_months
        and settlement.open_interest is not None
    ]

    open_interest_contracts = sum(
        float(settlement.open_interest or 0)
        for settlement in matching_settlements
    )
    if open_interest_contracts <= 0:
        raise ValueError(f"No matching open interest for {fund_metric.fund_ticker} {product}")

    open_interest_notional = sum(
        float(settlement.open_interest or 0) * settlement.settlement_price * multiplier
        for settlement in matching_settlements
    )
    held_contract_count = sum(abs(float(holding.quantity or 0)) for holding in matching_holdings)
    knowledge_date = max(
        [fund_metric.knowledge_date]
        + [holding.knowledge_date for holding in matching_holdings]
        + [settlement.knowledge_date for settlement in matching_settlements],
        key=_datetime_sort_key,
    )

    return FundCrowdingMetric(
        source="derived",
        fund_ticker=fund_metric.fund_ticker,
        commodity=commodity,
        product_code=product,
        report_date=fund_metric.report_date,
        knowledge_date=knowledge_date,
        fund_total_net_assets=fund_metric.total_net_assets,
        held_contract_count=held_contract_count,
        open_interest_contracts=open_interest_contracts,
        open_interest_notional=open_interest_notional,
        aum_to_open_interest_notional=fund_metric.total_net_assets / open_interest_notional,
        held_contracts_to_open_interest=held_contract_count / open_interest_contracts,
        matched_contract_months=len(
            {settlement.contract_month for settlement in matching_settlements}
        ),
    )


def _datetime_sort_key(value: datetime) -> float:
    return value.timestamp()
