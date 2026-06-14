from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

TARGET_SOURCE_COLUMNS = {
    "cl_front_month_settlement",
    "cl_m1_m2_spread",
}

DEFAULT_FEATURE_COLUMNS = (
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
    "news_count",
    "news_tone_mean",
    "news_impact_score",
)


@dataclass(frozen=True)
class FeatureCacheRow:
    report_date: date
    knowledge_date: datetime
    values: dict[str, Any]


@dataclass(frozen=True)
class SupervisedExample:
    report_date: date
    features: dict[str, float]
    price_direction_target: int
    spread_direction_target: int
    target_report_date: date


def load_feature_cache(path: Path) -> list[FeatureCacheRow]:
    """Load exported feature rows from Parquet in report-date order."""

    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM read_parquet(?) ORDER BY report_date",
            [str(path)],
        ).fetchall()
        columns = [description[0] for description in connection.description]

    report_date_index = columns.index("report_date")
    knowledge_date_index = columns.index("knowledge_date")
    return [
        FeatureCacheRow(
            report_date=row[report_date_index],
            knowledge_date=row[knowledge_date_index],
            values=dict(zip(columns, row, strict=True)),
        )
        for row in rows
    ]


def build_supervised_examples(
    rows: list[FeatureCacheRow],
    *,
    horizon_days: int,
    feature_columns: tuple[str, ...] = DEFAULT_FEATURE_COLUMNS,
) -> list[SupervisedExample]:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")

    examples: list[SupervisedExample] = []
    ordered_rows = sorted(rows, key=lambda row: row.report_date)
    for index, current in enumerate(ordered_rows):
        future_index = index + horizon_days
        if future_index >= len(ordered_rows):
            break
        future = ordered_rows[future_index]
        current_price = current.values.get("cl_front_month_settlement")
        future_price = future.values.get("cl_front_month_settlement")
        current_spread = current.values.get("cl_m1_m2_spread")
        future_spread = future.values.get("cl_m1_m2_spread")
        if None in (current_price, future_price, current_spread, future_spread):
            continue
        examples.append(
            SupervisedExample(
                report_date=current.report_date,
                features=_numeric_features(current, feature_columns),
                price_direction_target=int(float(future_price) > float(current_price)),
                spread_direction_target=int(float(future_spread) > float(current_spread)),
                target_report_date=future.report_date,
            )
        )
    return examples


def build_pooled_examples(
    caches: dict[str, Path],
    *,
    horizon_days: int,
    feature_columns: tuple[str, ...] = DEFAULT_FEATURE_COLUMNS,
) -> list[SupervisedExample]:
    """Combine per-commodity feature caches into one training set with commodity one-hot dummies.

    Cross-commodity pooling fights the thin per-commodity sample size; the ``commodity__<NAME>``
    dummies let the model learn commodity-specific offsets. Inference adds the active dummy for the
    row's commodity, so single-commodity artifacts (which have no dummies) are unaffected.
    """

    commodities = sorted(caches)
    pooled: list[SupervisedExample] = []
    for commodity in commodities:
        rows = load_feature_cache(caches[commodity])
        for example in build_supervised_examples(
            rows, horizon_days=horizon_days, feature_columns=feature_columns
        ):
            features = dict(example.features)
            for other in commodities:
                features[f"commodity__{other}"] = 1.0 if other == commodity else 0.0
            pooled.append(replace(example, features=features))
    pooled.sort(key=lambda example: example.report_date)
    return pooled


def _numeric_features(
    row: FeatureCacheRow,
    feature_columns: tuple[str, ...],
) -> dict[str, float]:
    features: dict[str, float] = {}
    for column in feature_columns:
        if column in TARGET_SOURCE_COLUMNS:
            continue
        value = row.values.get(column)
        features[column] = 0.0 if value is None else float(value)
    return features
