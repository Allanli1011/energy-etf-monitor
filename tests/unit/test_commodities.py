import pytest

from energy_etf_monitor.commodities import COMMODITIES, WTI, commodity_config


def test_registry_contains_core_energy_commodities() -> None:
    assert set(COMMODITIES) == {"WTI", "NATGAS", "RBOB"}
    assert all(config.curve_source == "cme" for config in COMMODITIES.values())


def test_commodity_config_lookup_is_case_insensitive() -> None:
    assert commodity_config("wti") is WTI
    assert commodity_config("NatGas").product_code == "NG"
    assert commodity_config("rbob").crowding_fund_ticker == "UGA"


def test_commodity_config_unknown_raises() -> None:
    # Brent is intentionally absent until an ICE curve provider exists.
    with pytest.raises(ValueError, match="Unknown commodity"):
        commodity_config("BRENT")
