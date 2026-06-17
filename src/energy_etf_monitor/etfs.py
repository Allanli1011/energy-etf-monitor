"""ETF universe metadata used for flow, roll-pressure, and dashboard views."""

from dataclasses import dataclass

DEFAULT_DASHBOARD_BASE_COMMODITIES = ("WTI", "NATGAS", "RBOB")


@dataclass(frozen=True)
class EtfFundConfig:
    ticker: str
    commodity: str
    issuer: str
    strategy_type: str
    strategy_badge: str
    strategy_description: str
    product_code: str | None = None
    leverage: float = 1.0
    front_month_roll: bool = False
    include_in_dashboard: bool = True
    include_in_model: bool = False
    include_in_metric_ingest: bool = True


ETF_FUND_LIST: tuple[EtfFundConfig, ...] = (
    EtfFundConfig(
        ticker="USO",
        commodity="WTI",
        issuer="USCF",
        strategy_type="front_month",
        strategy_badge="front-month roll",
        strategy_description=(
            "Front-month WTI exposure; the main fund-flow and roll-pressure proxy for CL."
        ),
        product_code="CL",
        front_month_roll=True,
        include_in_model=True,
    ),
    EtfFundConfig(
        ticker="USL",
        commodity="WTI",
        issuer="USCF",
        strategy_type="laddered",
        strategy_badge="12-month ladder",
        strategy_description=(
            "WTI exposure laddered across 12 consecutive monthly contracts; useful contrast "
            "against front-month roll concentration."
        ),
        product_code="CL",
    ),
    EtfFundConfig(
        ticker="UCO",
        commodity="WTI",
        issuer="ProShares",
        strategy_type="leveraged",
        strategy_badge="2x leveraged",
        strategy_description=(
            "Daily 2x WTI-linked product; useful as leveraged flow/sentiment context, not a "
            "clean structural roll input."
        ),
        product_code="CL",
        leverage=2.0,
    ),
    EtfFundConfig(
        ticker="SCO",
        commodity="WTI",
        issuer="ProShares",
        strategy_type="inverse",
        strategy_badge="-2x inverse",
        strategy_description=(
            "Daily -2x WTI-linked product; useful as inverse leveraged flow/sentiment context."
        ),
        product_code="CL",
        leverage=-2.0,
    ),
    EtfFundConfig(
        ticker="UNG",
        commodity="NATGAS",
        issuer="USCF",
        strategy_type="front_month",
        strategy_badge="front-month roll",
        strategy_description=(
            "Front-month Henry Hub natural gas exposure; the main UNG roll-pressure proxy."
        ),
        product_code="NG",
        front_month_roll=True,
        include_in_model=True,
    ),
    EtfFundConfig(
        ticker="UNL",
        commodity="NATGAS",
        issuer="USCF",
        strategy_type="laddered",
        strategy_badge="12-month ladder",
        strategy_description=(
            "Natural gas exposure laddered across 12 consecutive monthly contracts."
        ),
        product_code="NG",
    ),
    EtfFundConfig(
        ticker="BOIL",
        commodity="NATGAS",
        issuer="ProShares",
        strategy_type="leveraged",
        strategy_badge="2x leveraged",
        strategy_description=(
            "Daily 2x natural-gas-linked product; tracks speculative flow pressure more than "
            "issuer roll mechanics."
        ),
        product_code="NG",
        leverage=2.0,
    ),
    EtfFundConfig(
        ticker="KOLD",
        commodity="NATGAS",
        issuer="ProShares",
        strategy_type="inverse",
        strategy_badge="-2x inverse",
        strategy_description="Daily -2x natural-gas-linked product; inverse leveraged context.",
        product_code="NG",
        leverage=-2.0,
    ),
    EtfFundConfig(
        ticker="UGA",
        commodity="RBOB",
        issuer="USCF",
        strategy_type="front_month",
        strategy_badge="front-month roll",
        strategy_description=(
            "Front-month RBOB gasoline exposure. The single-product ETF universe is much thinner "
            "than WTI or natural gas."
        ),
        product_code="RB",
        front_month_roll=True,
        include_in_model=True,
    ),
    EtfFundConfig(
        ticker="BNO",
        commodity="BRENT",
        issuer="USCF",
        strategy_type="front_month",
        strategy_badge="front-month roll",
        strategy_description=(
            "United States Brent Oil Fund, LP. Front-month ICE Brent exposure; the ETF/ETP "
            "dashboard tracks the fund even though the core ICE curve source is still pending."
        ),
        product_code="B",
        front_month_roll=True,
    ),
    EtfFundConfig(
        ticker="BRNT",
        commodity="BRENT",
        issuer="WisdomTree",
        strategy_type="synthetic",
        strategy_badge="1x ETC",
        strategy_description=(
            "WisdomTree Brent Crude Oil. Swap-based ETC exposure to Brent crude futures total "
            "return; useful as a European ETP sentiment layer, not transparent futures holdings."
        ),
        product_code=None,
        include_in_metric_ingest=False,
    ),
    EtfFundConfig(
        ticker="SBRT",
        commodity="BRENT",
        issuer="WisdomTree",
        strategy_type="inverse",
        strategy_badge="-1x short",
        strategy_description=(
            "WisdomTree Brent Crude Oil 1x Daily Short. Daily inverse Brent exposure; ETF cash "
            "flow and Brent-equivalent exposure flow use opposite signs."
        ),
        product_code=None,
        leverage=-1.0,
        include_in_metric_ingest=False,
    ),
    EtfFundConfig(
        ticker="LBRT",
        commodity="BRENT",
        issuer="WisdomTree",
        strategy_type="leveraged",
        strategy_badge="2x leveraged",
        strategy_description=(
            "WisdomTree Brent Crude Oil 2x Daily Leveraged (also listed as 2BRT). Daily 2x "
            "Brent exposure; treated as directional notional pressure."
        ),
        product_code=None,
        leverage=2.0,
        include_in_metric_ingest=False,
    ),
    EtfFundConfig(
        ticker="3BRL",
        commodity="BRENT",
        issuer="WisdomTree",
        strategy_type="leveraged",
        strategy_badge="3x leveraged",
        strategy_description=(
            "WisdomTree Brent Crude Oil 3x Daily Leveraged. Daily 3x Brent exposure; treated as "
            "leveraged directional notional pressure."
        ),
        product_code=None,
        leverage=3.0,
        include_in_metric_ingest=False,
    ),
    EtfFundConfig(
        ticker="3BRS",
        commodity="BRENT",
        issuer="WisdomTree",
        strategy_type="inverse",
        strategy_badge="-3x short",
        strategy_description=(
            "WisdomTree Brent Crude Oil 3x Daily Short. Daily -3x Brent exposure; redemptions "
            "can translate into positive Brent-equivalent flow."
        ),
        product_code=None,
        leverage=-3.0,
        include_in_metric_ingest=False,
    ),
)

ETF_FUNDS: dict[str, EtfFundConfig] = {fund.ticker: fund for fund in ETF_FUND_LIST}


def dashboard_commodities(
    base_commodities: tuple[str, ...] = DEFAULT_DASHBOARD_BASE_COMMODITIES,
) -> tuple[str, ...]:
    """Commodity pages to render: core feature commodities plus ETF-only commodity pages."""

    ordered: list[str] = []
    seen: set[str] = set()
    candidates = tuple(base_commodities) + tuple(
        fund.commodity for fund in ETF_FUND_LIST if fund.include_in_dashboard
    )
    for commodity in candidates:
        normalized = commodity.upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def etf_funds_for_commodity(commodity: str) -> tuple[EtfFundConfig, ...]:
    name = commodity.upper()
    return tuple(
        fund for fund in ETF_FUND_LIST if fund.commodity == name and fund.include_in_dashboard
    )


def default_metric_tickers(
    commodities: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    allowed = _allowed_commodities(commodities)
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed and fund.include_in_metric_ingest
    )


def default_uscf_holding_tickers(
    commodities: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    allowed = _allowed_commodities(commodities)
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.issuer.upper() == "USCF"
        and fund.include_in_dashboard
        and fund.include_in_metric_ingest
    )


def default_proshares_holding_tickers(
    commodities: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    allowed = _allowed_commodities(commodities)
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.issuer.upper() == "PROSHARES"
        and fund.include_in_dashboard
        and fund.include_in_metric_ingest
    )


def default_official_holding_tickers(
    commodities: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    return (
        default_uscf_holding_tickers(commodities)
        + default_proshares_holding_tickers(commodities)
    )


def default_yahoo_metric_tickers(
    commodities: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    official_tickers = set(default_official_holding_tickers(commodities))
    allowed = _allowed_commodities(commodities)
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.ticker not in official_tickers
        and fund.include_in_metric_ingest
    )


def _allowed_commodities(commodities: tuple[str, ...] | None) -> set[str]:
    return {
        commodity.upper()
        for commodity in (dashboard_commodities() if commodities is None else commodities)
    }
