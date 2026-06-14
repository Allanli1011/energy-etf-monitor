import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from energy_etf_monitor.modeling.dataset import DEFAULT_FEATURE_COLUMNS, TARGET_SOURCE_COLUMNS
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction


class PredictionModel(Protocol):
    """Common interface implemented by both the logistic and LightGBM artifacts."""

    model_type: str
    target_name: str
    horizon_days: int
    trained_through: date
    training_count: int

    def predict(self, features: dict[str, float]) -> float: ...

    def raw_contributions(self, features: dict[str, float]) -> dict[str, float]: ...


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    contribution: float


def artifact_version(artifact: PredictionModel) -> str:
    """Stable, human-readable version stamp for a saved model artifact."""

    return (
        f"{artifact.model_type}:{artifact.target_name}"
        f":h{artifact.horizon_days}:through{artifact.trained_through.isoformat()}"
        f":n{artifact.training_count}"
    )


def feature_dict_from_row(row: DailyFeatureRow) -> dict[str, float]:
    """Extract the model feature vector from a feature row (missing values -> 0.0).

    Mirrors ``dataset._numeric_features`` so training and inference see identical encodings.
    """

    features: dict[str, float] = {}
    for column in DEFAULT_FEATURE_COLUMNS:
        if column in TARGET_SOURCE_COLUMNS:
            continue
        value = getattr(row, column, None)
        features[column] = 0.0 if value is None else float(value)
    return features


def top_feature_contributions(
    artifact: PredictionModel,
    features: dict[str, float],
    *,
    top_n: int = 3,
) -> list[FeatureContribution]:
    """Rank a model's local drivers by absolute log-odds contribution.

    Both backends expose exact additive contributions to the log-odds: the logistic artifact via
    ``weight * value / scale`` and the LightGBM artifact via its per-feature ``pred_contrib`` SHAP
    values. So this is an honest local explanation for either model, no extra dependency.
    """

    contributions = [
        FeatureContribution(feature=name, contribution=value)
        for name, value in artifact.raw_contributions(features).items()
    ]
    contributions.sort(key=lambda item: abs(item.contribution), reverse=True)
    return contributions[:top_n]


def predict_two_head(
    *,
    feature_row: DailyFeatureRow,
    price_artifact: PredictionModel,
    spread_artifact: PredictionModel,
    predicted_at: datetime,
    top_n: int = 3,
) -> DailyPrediction:
    """Score one feature row with the price and spread heads into a DailyPrediction."""

    if price_artifact.target_name != "price_direction":
        raise ValueError("price_artifact must target price_direction")
    if spread_artifact.target_name != "spread_direction":
        raise ValueError("spread_artifact must target spread_direction")
    if price_artifact.horizon_days != spread_artifact.horizon_days:
        raise ValueError("price and spread artifacts must share the same horizon_days")
    if _as_utc_naive(predicted_at) < _as_utc_naive(feature_row.knowledge_date):
        raise ValueError("predicted_at must be at or after the feature row knowledge_date")

    features = feature_dict_from_row(feature_row)
    return DailyPrediction(
        source="prediction_pipeline",
        commodity=feature_row.commodity,
        report_date=feature_row.report_date,
        knowledge_date=predicted_at,
        horizon_days=price_artifact.horizon_days,
        feature_report_date=feature_row.report_date,
        price_up_probability=price_artifact.predict(features),
        spread_up_probability=spread_artifact.predict(features),
        price_naive_probability=_persistence_probability(feature_row.cl_front_month_return_1d),
        spread_naive_probability=_persistence_probability(feature_row.cl_carry_m1_m2_change_1d),
        price_model_version=artifact_version(price_artifact),
        spread_model_version=artifact_version(spread_artifact),
        price_top_drivers=_drivers_json(
            top_feature_contributions(price_artifact, features, top_n=top_n)
        ),
        spread_top_drivers=_drivers_json(
            top_feature_contributions(spread_artifact, features, top_n=top_n)
        ),
    )


def parse_top_drivers(drivers_json: str) -> list[FeatureContribution]:
    """Inverse of the persisted drivers JSON, for dashboards/tests."""

    return [
        FeatureContribution(feature=str(item["feature"]), contribution=float(item["contribution"]))
        for item in json.loads(drivers_json)
    ]


def _persistence_probability(recent_change: float | None) -> float | None:
    """Naive reference: persist the sign of the most recent 1-day move (point-in-time safe)."""

    if recent_change is None:
        return None
    return 1.0 if recent_change > 0 else 0.0


def _drivers_json(contributions: list[FeatureContribution]) -> str:
    return json.dumps(
        [
            {"feature": item.feature, "contribution": round(item.contribution, 6)}
            for item in contributions
        ]
    )


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
