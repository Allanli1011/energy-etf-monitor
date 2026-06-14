from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class TimeSeriesObservationRow(SQLModel, table=True):
    __tablename__ = "time_series_observations"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "series_id",
            "report_date",
            name="uq_time_series_observations_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    series_id: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    value: float
    unit: str | None = None
    quarantine: bool = Field(default=False, index=True)


class CotPositionRow(SQLModel, table=True):
    __tablename__ = "cot_positions"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "commodity",
            "contract_market_code",
            "report_date",
            name="uq_cot_positions_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    commodity: str = Field(index=True)
    market_name: str
    contract_market_code: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    open_interest: int
    swap_dealer_long: int | None = None
    swap_dealer_short: int | None = None
    swap_dealer_spread: int | None = None
    quarantine: bool = Field(default=False, index=True)


class FuturesSettlementRow(SQLModel, table=True):
    __tablename__ = "futures_settlements"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "product_code",
            "report_date",
            "contract_month",
            name="uq_futures_settlements_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    product_code: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    contract_month: date = Field(index=True)
    settlement_price: float
    open_interest: int | None = None
    quarantine: bool = Field(default=False, index=True)


class FundDailyMetricRow(SQLModel, table=True):
    __tablename__ = "fund_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "fund_ticker",
            "report_date",
            name="uq_fund_daily_metrics_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    fund_ticker: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    nav_per_share: float
    shares_outstanding: float
    total_net_assets: float
    implied_flow_usd: float | None = None
    quarantine: bool = Field(default=False, index=True)


class FundHoldingRow(SQLModel, table=True):
    __tablename__ = "fund_holdings"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "fund_ticker",
            "report_date",
            "holding_key",
            name="uq_fund_holdings_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    fund_ticker: str = Field(index=True)
    holding_key: str = Field(index=True)
    holding_name: str
    instrument_type: str = Field(index=True)
    ticker: str | None = Field(default=None, index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    contract_month: date | None = Field(default=None, index=True)
    quantity: float | None = None
    market_value: float | None = None
    percent_nav: float | None = None
    quarantine: bool = Field(default=False, index=True)


class FundCrowdingMetricRow(SQLModel, table=True):
    __tablename__ = "fund_crowding_metrics"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "fund_ticker",
            "commodity",
            "product_code",
            "report_date",
            name="uq_fund_crowding_metrics_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    fund_ticker: str = Field(index=True)
    commodity: str = Field(index=True)
    product_code: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    fund_total_net_assets: float
    held_contract_count: float
    open_interest_contracts: float
    open_interest_notional: float
    aum_to_open_interest_notional: float
    held_contracts_to_open_interest: float
    matched_contract_months: int
    quarantine: bool = Field(default=False, index=True)


class NewsArticleRow(SQLModel, table=True):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "url_hash",
            name="uq_news_articles_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    published_at: datetime = Field(index=True)
    url: str
    url_hash: str = Field(index=True)
    title: str
    canonical_url: str | None = Field(default=None, index=True)
    summary: str | None = None
    tone: float | None = None
    commodity: str | None = Field(default=None, index=True)
    contract_family: str | None = None
    catalyst_type: str | None = Field(default=None, index=True)
    importance_score: float = Field(default=0.0, index=True)
    impact_direction: str = Field(default="Unknown", index=True)
    spread_impact_direction: str | None = None
    confidence: float = 0.0
    rationale: str | None = None
    quarantine: bool = Field(default=False, index=True)


class DailyPredictionRow(SQLModel, table=True):
    __tablename__ = "daily_predictions"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "commodity",
            "report_date",
            "horizon_days",
            name="uq_daily_predictions_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    commodity: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    horizon_days: int = Field(index=True)
    feature_report_date: date = Field(index=True)
    price_up_probability: float
    spread_up_probability: float
    price_naive_probability: float | None = None
    spread_naive_probability: float | None = None
    price_model_version: str
    spread_model_version: str
    price_top_drivers: str
    spread_top_drivers: str
    quarantine: bool = Field(default=False, index=True)


class DailyFeatureRowModel(SQLModel, table=True):
    __tablename__ = "daily_feature_rows"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "commodity",
            "report_date",
            name="uq_daily_feature_rows_natural_key",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    commodity: str = Field(index=True)
    report_date: date = Field(index=True)
    knowledge_date: datetime = Field(index=True)
    cl_front_month_settlement: float | None = None
    cl_m1_m2_spread: float | None = None
    cl_m2_m3_spread: float | None = None
    cl_m3_m6_spread: float | None = None
    cl_curve_curvature_m1_m2_m3: float | None = None
    cl_front_month_return_1d: float | None = None
    cl_carry_m1_m2: float | None = None
    cl_carry_m1_m2_change_1d: float | None = None
    cot_swap_dealer_net: float | None = None
    cot_swap_dealer_net_zscore: float | None = None
    cot_swap_dealer_net_index: float | None = None
    cot_open_interest: float | None = None
    inventory_value: float | None = None
    inventory_seasonal_surprise: float | None = None
    usd_index_value: float | None = None
    real_yield_10y: float | None = None
    crowding_aum_to_oi: float | None = None
    crowding_contracts_to_oi: float | None = None
    roll_window_flag: float | None = None
    roll_window_crowding_interaction: float | None = None
    news_count: float | None = None
    news_tone_mean: float | None = None
    news_impact_score: float | None = None
    quarantine: bool = Field(default=False, index=True)
