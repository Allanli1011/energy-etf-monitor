"""Per-commodity configuration so the WTI pipeline generalizes to other energy futures.

Each config pins the exchange product code, the CFTC COT contract-market code, the EIA inventory
series, and the futures-based ETF used for the crowding feature. Adding a commodity is a config
entry plus ingestion wiring — no new feature/model code.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommodityConfig:
    name: str
    product_code: str
    cot_contract_market_code: str
    inventory_series_id: str
    crowding_fund_ticker: str | None = None
    crowding_product_code: str | None = None
    curve_source: str = "cme"  # "cme" (free settlements) or "ice" (paywalled — provider pending)


# COT contract-market codes: WTI 067651 is verified live against the CFTC API; the NatGas/RBOB
# codes below are the commonly-cited disaggregated codes and should be re-verified against
# publicreporting.cftc.gov before relying on live positioning data.
WTI = CommodityConfig(
    name="WTI",
    product_code="CL",
    cot_contract_market_code="067651",
    inventory_series_id="WCESTUS1",
    crowding_fund_ticker="USO",
    crowding_product_code="CL",
    curve_source="cme",
)
NATGAS = CommodityConfig(
    name="NATGAS",
    product_code="NG",
    cot_contract_market_code="023651",
    inventory_series_id="NG.NW2_EPG0_SWO_R48_BCF.W",
    crowding_fund_ticker="UNG",
    crowding_product_code="NG",
    curve_source="cme",
)
RBOB = CommodityConfig(
    name="RBOB",
    product_code="RB",
    cot_contract_market_code="111659",
    inventory_series_id="WGTSTUS1",
    crowding_fund_ticker="UGA",
    crowding_product_code="RB",
    curve_source="cme",
)

# Brent is ICE-listed; its forward curve is paywalled and the ICE provider is not built yet, so it
# is intentionally excluded from the default registry until a curve source exists.

COMMODITIES: dict[str, CommodityConfig] = {config.name: config for config in (WTI, NATGAS, RBOB)}


def commodity_config(name: str) -> CommodityConfig:
    try:
        return COMMODITIES[name.upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown commodity: {name}") from exc
