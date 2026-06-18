import pytest

from energy_etf_monitor.commodities import BRENT, COMMODITIES, WTI, commodity_config


def test_registry_contains_core_energy_commodities() -> None:
    assert set(COMMODITIES) == {"WTI", "NATGAS", "RBOB", "BRENT"}
    assert all(config.curve_source == "yahoo" for config in COMMODITIES.values())
    assert BRENT.product_code == "BZ"
    assert BRENT.cot_contract_market_code == "B"
    assert BRENT.cot_source == "ice_cot"
    assert BRENT.inventory_series_id is None


def test_commodity_config_lookup_is_case_insensitive() -> None:
    assert commodity_config("wti") is WTI
    assert commodity_config("NatGas").product_code == "NG"
    assert commodity_config("rbob").crowding_fund_ticker == "UGA"
    assert commodity_config("brent") is BRENT


def test_commodity_config_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown commodity"):
        commodity_config("POWER")
