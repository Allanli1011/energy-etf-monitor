from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PointInTimeRecord(BaseModel):
    """Base record carrying event time and first-known time."""

    model_config = ConfigDict(frozen=True)

    source: str
    report_date: date
    knowledge_date: datetime
    quarantine: bool = False


class TimeSeriesObservation(PointInTimeRecord):
    series_id: str
    value: float
    unit: str | None = None
    metadata: dict[str, str | int | float | None] = Field(default_factory=dict)


class CotPosition(PointInTimeRecord):
    commodity: str
    market_name: str
    contract_market_code: str
    open_interest: int
    swap_dealer_long: int | None = None
    swap_dealer_short: int | None = None
    swap_dealer_spread: int | None = None


class FuturesSettlement(PointInTimeRecord):
    product_code: str
    contract_month: date
    settlement_price: float
    open_interest: int | None = None


class FundDailyMetric(PointInTimeRecord):
    fund_ticker: str
    nav_per_share: float
    shares_outstanding: float
    total_net_assets: float
    implied_flow_usd: float | None = None


class FundHolding(PointInTimeRecord):
    fund_ticker: str
    holding_key: str
    holding_name: str
    instrument_type: str
    ticker: str | None = None
    contract_month: date | None = None
    quantity: float | None = None
    market_value: float | None = None
    percent_nav: float | None = None


class FundCrowdingMetric(PointInTimeRecord):
    fund_ticker: str
    commodity: str
    product_code: str
    fund_total_net_assets: float
    held_contract_count: float
    open_interest_contracts: float
    open_interest_notional: float
    aum_to_open_interest_notional: float
    held_contracts_to_open_interest: float
    matched_contract_months: int


class DailyPrediction(PointInTimeRecord):
    commodity: str
    horizon_days: int
    feature_report_date: date
    price_up_probability: float
    spread_up_probability: float
    price_model_version: str
    spread_model_version: str
    price_top_drivers: str
    spread_top_drivers: str
    price_naive_probability: float | None = None
    spread_naive_probability: float | None = None


class NewsArticle(PointInTimeRecord):
    """A market-moving news item plus its (optional) impact classification.

    ``report_date`` is the publication date and ``knowledge_date`` is when we fetched it, so the
    same point-in-time gate as every other source applies. Impact fields default to an unscored
    state until a classifier fills them in.
    """

    published_at: datetime
    url: str
    url_hash: str
    title: str
    canonical_url: str | None = None
    summary: str | None = None
    tone: float | None = None
    commodity: str | None = None
    contract_family: str | None = None
    catalyst_type: str | None = None
    importance_score: float = 0.0
    impact_direction: str = "Unknown"
    spread_impact_direction: str | None = None
    confidence: float = 0.0
    rationale: str | None = None


class DailyFeatureRow(PointInTimeRecord):
    commodity: str
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
