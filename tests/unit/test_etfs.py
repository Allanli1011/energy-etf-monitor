from energy_etf_monitor.etfs import (
    ETF_FUNDS,
    dashboard_commodities,
    default_metric_tickers,
    default_official_holding_tickers,
    default_proshares_holding_tickers,
    default_uscf_holding_tickers,
    default_wisdomtree_metric_tickers,
    default_yahoo_metric_tickers,
    etf_funds_for_commodity,
    yahoo_metric_source_ticker,
)


def test_etf_registry_covers_core_strategy_types() -> None:
    wti = etf_funds_for_commodity("WTI")
    natgas = etf_funds_for_commodity("natgas")

    assert [fund.ticker for fund in wti] == [
        "USO",
        "USL",
        "UCO",
        "SCO",
        "SOIL",
        "LOIL",
        "3OIL",
        "3OIS",
    ]
    assert {fund.strategy_type for fund in wti} >= {
        "front_month",
        "laddered",
        "leveraged",
        "inverse",
    }
    assert {fund.ticker for fund in natgas} >= {
        "UNG",
        "UNL",
        "BOIL",
        "KOLD",
        "SNGA",
        "LNGA",
        "3NGL",
        "3NGS",
    }


def test_brent_etp_registry_includes_requested_products() -> None:
    brent = etf_funds_for_commodity("brent")

    assert [fund.ticker for fund in brent] == ["BNO", "BRNT", "SBRT", "LBRT", "3BRL", "3BRS"]
    assert {fund.issuer for fund in brent} == {"USCF", "WisdomTree"}
    assert {fund.ticker: fund.leverage for fund in brent} == {
        "BNO": 1.0,
        "BRNT": 1.0,
        "SBRT": -1.0,
        "LBRT": 2.0,
        "3BRL": 3.0,
        "3BRS": -3.0,
    }
    assert ETF_FUNDS["BNO"].front_month_roll is True
    assert ETF_FUNDS["BRNT"].include_in_metric_ingest is True
    assert yahoo_metric_source_ticker("BRNT") == "BRNT.MI"
    assert yahoo_metric_source_ticker("3BRS") == "3BRS.MI"


def test_dashboard_commodities_adds_etf_only_brent_page() -> None:
    assert dashboard_commodities(("WTI", "NATGAS", "RBOB")) == (
        "WTI",
        "NATGAS",
        "RBOB",
        "BRENT",
    )


def test_default_metric_tickers_expand_beyond_primary_crowding_funds() -> None:
    tickers = default_metric_tickers()

    assert tickers[:2] == ("USO", "USL")
    assert {"USO", "UNG", "UGA", "BNO"}.issubset(tickers)
    assert {"UCO", "SCO", "BOIL", "KOLD"}.issubset(tickers)


def test_default_source_tickers_route_supported_issuers_to_official_connectors() -> None:
    uscf = default_uscf_holding_tickers()
    proshares = default_proshares_holding_tickers()
    official = default_official_holding_tickers()
    wisdomtree = default_wisdomtree_metric_tickers()
    yahoo = default_yahoo_metric_tickers()

    assert {"USO", "USL", "UNG", "UNL", "UGA", "BNO"}.issubset(uscf)
    assert {"UCO", "SCO", "BOIL", "KOLD"}.issubset(proshares)
    assert {"USO", "USL", "UCO", "SCO", "UNG", "UNL", "BOIL", "KOLD", "UGA", "BNO"}.issubset(
        official
    )
    assert "DBO" not in official
    assert wisdomtree == (
        "SOIL",
        "LOIL",
        "3OIL",
        "3OIS",
        "SNGA",
        "LNGA",
        "3NGL",
        "3NGS",
        "BRNT",
        "SBRT",
        "LBRT",
        "3BRL",
        "3BRS",
    )
    assert yahoo == wisdomtree


def test_registry_keeps_model_and_dashboard_roles_separate() -> None:
    uso = ETF_FUNDS["USO"]
    uco = ETF_FUNDS["UCO"]

    assert uso.include_in_model is True
    assert uso.include_in_dashboard is True
    assert uco.include_in_model is False
    assert uco.leverage == 2.0
    assert uco.strategy_badge == "2x leveraged"
