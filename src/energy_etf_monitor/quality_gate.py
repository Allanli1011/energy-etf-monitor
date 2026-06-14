import math
from dataclasses import dataclass

from energy_etf_monitor.records import (
    CotPosition,
    DailyFeatureRow,
    DailyPrediction,
    FundCrowdingMetric,
    FundDailyMetric,
    FundHolding,
    FuturesSettlement,
    PointInTimeRecord,
    TimeSeriesObservation,
)


@dataclass(frozen=True)
class QualityGateResult:
    quarantine: bool
    reasons: list[str]


def inspect_record_quality(record: PointInTimeRecord) -> QualityGateResult:
    reasons: list[str] = []

    if record.knowledge_date.date() < record.report_date:
        reasons.append("knowledge_date_before_report_date")

    if isinstance(record, TimeSeriesObservation):
        if not math.isfinite(record.value):
            reasons.append("nonfinite_value")
    elif isinstance(record, CotPosition):
        _add_negative_reason(reasons, "open_interest", record.open_interest)
        _add_negative_reason(reasons, "swap_dealer_long", record.swap_dealer_long)
        _add_negative_reason(reasons, "swap_dealer_short", record.swap_dealer_short)
        _add_negative_reason(reasons, "swap_dealer_spread", record.swap_dealer_spread)
    elif isinstance(record, FuturesSettlement):
        if record.settlement_price <= 0:
            reasons.append("nonpositive_settlement_price")
        _add_negative_reason(reasons, "open_interest", record.open_interest)
        if record.contract_month.day != 1:
            reasons.append("contract_month_not_month_start")
    elif isinstance(record, FundDailyMetric):
        if record.nav_per_share <= 0:
            reasons.append("nonpositive_nav_per_share")
        if record.shares_outstanding < 0:
            reasons.append("negative_shares_outstanding")
        if record.total_net_assets < 0:
            reasons.append("negative_total_net_assets")
    elif isinstance(record, FundHolding):
        if record.market_value is not None and not math.isfinite(record.market_value):
            reasons.append("nonfinite_market_value")
        if record.percent_nav is not None and not math.isfinite(record.percent_nav):
            reasons.append("nonfinite_percent_nav")
    elif isinstance(record, FundCrowdingMetric):
        if record.fund_total_net_assets < 0:
            reasons.append("negative_fund_total_net_assets")
        if record.open_interest_contracts <= 0:
            reasons.append("nonpositive_open_interest_contracts")
        if record.open_interest_notional <= 0:
            reasons.append("nonpositive_open_interest_notional")
        if record.matched_contract_months <= 0:
            reasons.append("no_matched_contract_months")
    elif isinstance(record, DailyPrediction):
        _add_probability_reason(reasons, "price_up_probability", record.price_up_probability)
        _add_probability_reason(reasons, "spread_up_probability", record.spread_up_probability)
        if record.horizon_days <= 0:
            reasons.append("nonpositive_horizon_days")
        if record.feature_report_date > record.report_date:
            reasons.append("feature_report_date_after_report_date")
    elif isinstance(record, DailyFeatureRow):
        for field_name in (
            "cl_front_month_settlement",
            "cl_m1_m2_spread",
            "cl_m2_m3_spread",
            "cl_m3_m6_spread",
            "cl_curve_curvature_m1_m2_m3",
            "cl_front_month_return_1d",
            "cl_carry_m1_m2",
            "cl_carry_m1_m2_change_1d",
            "cot_swap_dealer_net",
            "cot_swap_dealer_net_zscore",
            "cot_swap_dealer_net_index",
            "cot_open_interest",
            "inventory_value",
            "inventory_seasonal_surprise",
            "usd_index_value",
            "real_yield_10y",
            "crowding_aum_to_oi",
            "crowding_contracts_to_oi",
            "roll_window_flag",
            "roll_window_crowding_interaction",
        ):
            value = getattr(record, field_name)
            if value is not None and not math.isfinite(value):
                reasons.append(f"nonfinite_{field_name}")

    return QualityGateResult(quarantine=record.quarantine or bool(reasons), reasons=reasons)


def apply_quality_gate[T: PointInTimeRecord](record: T) -> T:
    result = inspect_record_quality(record)
    if result.quarantine == record.quarantine:
        return record
    return record.model_copy(update={"quarantine": result.quarantine})


def _add_negative_reason(reasons: list[str], field_name: str, value: int | None) -> None:
    if value is not None and value < 0:
        reasons.append(f"negative_{field_name}")


def _add_probability_reason(reasons: list[str], field_name: str, value: float) -> None:
    if not math.isfinite(value):
        reasons.append(f"nonfinite_{field_name}")
    elif not 0.0 <= value <= 1.0:
        reasons.append(f"out_of_range_{field_name}")
