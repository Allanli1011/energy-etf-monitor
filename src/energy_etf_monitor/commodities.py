"""Per-commodity configuration for energy futures monitored by the pipeline.

Each config pins the exchange product code, the CFTC COT contract-market code, the optional EIA
inventory series, and the futures-based ETF used for the crowding feature. The current free curve
provider is Yahoo Finance; exchange-official ICE settlement packages remain a paid upgrade path.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommodityConfig:
    name: str
    product_code: str
    cot_contract_market_code: str
    inventory_series_id: str | None
    crowding_fund_ticker: str | None = None
    crowding_product_code: str | None = None
    curve_source: str = "yahoo"


# COT contract-market codes are verified against the CFTC disaggregated futures-only API.
WTI = CommodityConfig(
    name="WTI",
    product_code="CL",
    cot_contract_market_code="067651",
    inventory_series_id="WCESTUS1",
    crowding_fund_ticker="USO",
    crowding_product_code="CL",
)
NATGAS = CommodityConfig(
    name="NATGAS",
    product_code="NG",
    cot_contract_market_code="023651",
    inventory_series_id="NG.NW2_EPG0_SWO_R48_BCF.W",
    crowding_fund_ticker="UNG",
    crowding_product_code="NG",
)
RBOB = CommodityConfig(
    name="RBOB",
    product_code="RB",
    cot_contract_market_code="111659",
    inventory_series_id="WGTSTUS1",
    crowding_fund_ticker="UGA",
    crowding_product_code="RB",
)
BRENT = CommodityConfig(
    name="BRENT",
    product_code="BZ",
    cot_contract_market_code="06765T",
    inventory_series_id=None,
    crowding_fund_ticker="BNO",
    crowding_product_code="BZ",
)

COMMODITIES: dict[str, CommodityConfig] = {
    config.name: config for config in (WTI, NATGAS, RBOB, BRENT)
}


def commodity_config(name: str) -> CommodityConfig:
    try:
        return COMMODITIES[name.upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown commodity: {name}") from exc
