from energy_etf_monitor.etfs import (
    ETF_FUNDS,
    default_metric_tickers,
    default_official_holding_tickers,
    default_proshares_holding_tickers,
    default_uscf_holding_tickers,
    default_yahoo_metric_tickers,
    etf_funds_for_commodity,
)


def test_etf_registry_covers_core_strategy_types() -> None:
    wti = etf_funds_for_commodity("WTI")
    natgas = etf_funds_for_commodity("natgas")

    assert [fund.ticker for fund in wti] == ["USO", "USL", "UCO", "SCO"]
    assert {fund.strategy_type for fund in wti} >= {
        "front_month",
        "laddered",
        "leveraged",
        "inverse",
    }
    assert {fund.ticker for fund in natgas} >= {"UNG", "UNL", "BOIL", "KOLD"}


def test_default_metric_tickers_expand_beyond_primary_crowding_funds() -> None:
    tickers = default_metric_tickers()

    assert tickers[:2] == ("USO", "USL")
    assert {"USO", "UNG", "UGA"}.issubset(tickers)
    assert {"UCO", "SCO", "BOIL", "KOLD"}.issubset(tickers)


def test_default_source_tickers_route_supported_issuers_to_official_connectors() -> None:
    uscf = default_uscf_holding_tickers()
    proshares = default_proshares_holding_tickers()
    official = default_official_holding_tickers()
    yahoo = default_yahoo_metric_tickers()

    assert {"USO", "USL", "UNG", "UNL", "UGA"}.issubset(uscf)
    assert {"UCO", "SCO", "BOIL", "KOLD"}.issubset(proshares)
    assert {"USO", "USL", "UCO", "SCO", "UNG", "UNL", "BOIL", "KOLD", "UGA"}.issubset(
        official
    )
    assert "DBO" not in official
    assert yahoo == ()


def test_registry_keeps_model_and_dashboard_roles_separate() -> None:
    uso = ETF_FUNDS["USO"]
    uco = ETF_FUNDS["UCO"]

    assert uso.include_in_model is True
    assert uso.include_in_dashboard is True
    assert uco.include_in_model is False
    assert uco.leverage == 2.0
    assert uco.strategy_badge == "2x leveraged"
