"""ETF universe metadata used for flow, roll-pressure, and dashboard views."""

from dataclasses import dataclass


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
        ticker="DBO",
        commodity="WTI",
        issuer="Invesco",
        strategy_type="optimum_yield",
        strategy_badge="optimum yield",
        strategy_description=(
            "WTI strategy fund that can select a futures month to reduce negative roll yield."
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
            "Front-month Brent exposure; excluded from the main commodity registry until an ICE "
            "curve source exists."
        ),
        product_code="B",
        front_month_roll=True,
        include_in_dashboard=False,
        include_in_metric_ingest=False,
    ),
)

ETF_FUNDS: dict[str, EtfFundConfig] = {fund.ticker: fund for fund in ETF_FUND_LIST}


def etf_funds_for_commodity(commodity: str) -> tuple[EtfFundConfig, ...]:
    name = commodity.upper()
    return tuple(
        fund for fund in ETF_FUND_LIST if fund.commodity == name and fund.include_in_dashboard
    )


def default_metric_tickers(
    commodities: tuple[str, ...] = ("WTI", "NATGAS", "RBOB"),
) -> tuple[str, ...]:
    allowed = {commodity.upper() for commodity in commodities}
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed and fund.include_in_metric_ingest
    )


def default_uscf_holding_tickers(
    commodities: tuple[str, ...] = ("WTI", "NATGAS", "RBOB"),
) -> tuple[str, ...]:
    allowed = {commodity.upper() for commodity in commodities}
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.issuer.upper() == "USCF"
        and fund.include_in_dashboard
        and fund.include_in_metric_ingest
    )


def default_proshares_holding_tickers(
    commodities: tuple[str, ...] = ("WTI", "NATGAS", "RBOB"),
) -> tuple[str, ...]:
    allowed = {commodity.upper() for commodity in commodities}
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.issuer.upper() == "PROSHARES"
        and fund.include_in_dashboard
        and fund.include_in_metric_ingest
    )


def default_invesco_holding_tickers(
    commodities: tuple[str, ...] = ("WTI", "NATGAS", "RBOB"),
) -> tuple[str, ...]:
    allowed = {commodity.upper() for commodity in commodities}
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.issuer.upper() == "INVESCO"
        and fund.include_in_dashboard
        and fund.include_in_metric_ingest
    )


def default_official_holding_tickers(
    commodities: tuple[str, ...] = ("WTI", "NATGAS", "RBOB"),
) -> tuple[str, ...]:
    return (
        default_uscf_holding_tickers(commodities)
        + default_invesco_holding_tickers(commodities)
        + default_proshares_holding_tickers(commodities)
    )


def default_yahoo_metric_tickers(
    commodities: tuple[str, ...] = ("WTI", "NATGAS", "RBOB"),
) -> tuple[str, ...]:
    official_tickers = set(default_official_holding_tickers(commodities))
    allowed = {commodity.upper() for commodity in commodities}
    return tuple(
        fund.ticker
        for fund in ETF_FUND_LIST
        if fund.commodity in allowed
        and fund.ticker not in official_tickers
        and fund.include_in_metric_ingest
    )
