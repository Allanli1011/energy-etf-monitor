"""LightGBM model heads (optional `gbm` extra).

This module imports lightgbm/numpy at module load, so it must only be imported on demand (the
loader and the CLI gbm command import it lazily) — the core install does not require the native
LightGBM dependency.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np

from energy_etf_monitor.modeling.dataset import SupervisedExample
from energy_etf_monitor.modeling.targets import target_value, validate_target_name

DEFAULT_GBM_PARAMS = {
    "objective": "binary",
    "num_leaves": 7,
    "learning_rate": 0.05,
    "min_data_in_leaf": 1,
    "min_data_in_bin": 1,
    "feature_pre_filter": False,
    "verbosity": -1,
}


@dataclass(frozen=True)
class GbmArtifact:
    model_type: str
    target_name: str
    horizon_days: int
    trained_through: date
    training_count: int
    feature_names: tuple[str, ...]
    booster_text: str

    def predict(self, features: dict[str, float]) -> float:
        booster = lgb.Booster(model_str=self.booster_text)
        value = booster.predict(np.array([self._vector(features)], dtype=float))[0]
        return float(value)

    def raw_contributions(self, features: dict[str, float]) -> dict[str, float]:
        """Per-feature additive log-odds contributions via LightGBM `pred_contrib` (SHAP).

        ``pred_contrib`` returns one column per feature plus a trailing expected-value (base) term,
        which is dropped here so only feature attributions remain.
        """

        booster = lgb.Booster(model_str=self.booster_text)
        contributions = booster.predict(
            np.array([self._vector(features)], dtype=float),
            pred_contrib=True,
        )[0]
        return {name: float(contributions[index]) for index, name in enumerate(self.feature_names)}

    def _vector(self, features: dict[str, float]) -> list[float]:
        return [float(features.get(name, 0.0)) for name in self.feature_names]


def train_gbm_artifact(
    examples: list[SupervisedExample],
    *,
    target_name: str,
    horizon_days: int,
    num_boost_round: int = 100,
    params: dict | None = None,
) -> GbmArtifact:
    validate_target_name(target_name)
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if not examples:
        raise ValueError("at least one training example is required")

    ordered = sorted(examples, key=lambda example: example.report_date)
    feature_names = tuple(sorted({name for example in ordered for name in example.features}))
    matrix = np.array(
        [[float(example.features.get(name, 0.0)) for name in feature_names] for example in ordered],
        dtype=float,
    )
    labels = np.array([target_value(example, target_name) for example in ordered], dtype=float)

    resolved_params = {**DEFAULT_GBM_PARAMS, **(params or {})}
    dataset = lgb.Dataset(matrix, label=labels, feature_name=list(feature_names))
    booster = lgb.train(resolved_params, dataset, num_boost_round=num_boost_round)
    return GbmArtifact(
        model_type="lightgbm",
        target_name=target_name,
        horizon_days=horizon_days,
        trained_through=ordered[-1].report_date,
        training_count=len(ordered),
        feature_names=feature_names,
        booster_text=booster.model_to_string(),
    )


def save_gbm_artifact(artifact: GbmArtifact, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model_type": artifact.model_type,
                "target_name": artifact.target_name,
                "horizon_days": artifact.horizon_days,
                "trained_through": artifact.trained_through.isoformat(),
                "training_count": artifact.training_count,
                "feature_names": list(artifact.feature_names),
                "booster_text": artifact.booster_text,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return path


def load_gbm_artifact(path: Path) -> GbmArtifact:
    payload = json.loads(path.read_text())
    return GbmArtifact(
        model_type=str(payload["model_type"]),
        target_name=str(payload["target_name"]),
        horizon_days=int(payload["horizon_days"]),
        trained_through=date.fromisoformat(str(payload["trained_through"])),
        training_count=int(payload["training_count"]),
        feature_names=tuple(str(name) for name in payload["feature_names"]),
        booster_text=str(payload["booster_text"]),
    )
