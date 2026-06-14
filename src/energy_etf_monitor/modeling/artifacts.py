import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from energy_etf_monitor.modeling.dataset import SupervisedExample
from energy_etf_monitor.modeling.logistic import LogisticModel, fit_logistic_model
from energy_etf_monitor.modeling.targets import target_value, validate_target_name


@dataclass(frozen=True)
class ModelArtifact:
    model_type: str
    target_name: str
    horizon_days: int
    trained_through: date
    training_count: int
    feature_names: tuple[str, ...]
    weights: tuple[float, ...]
    intercept: float
    scales: dict[str, float]

    def predict(self, features: dict[str, float]) -> float:
        return LogisticModel(
            feature_names=self.feature_names,
            weights=self.weights,
            intercept=self.intercept,
            scales=self.scales,
        ).predict(features)


def train_logistic_artifact(
    examples: list[SupervisedExample],
    *,
    target_name: str,
    horizon_days: int,
    learning_rate: float = 0.1,
    epochs: int = 100,
) -> ModelArtifact:
    validate_target_name(target_name)
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if not examples:
        raise ValueError("at least one training example is required")

    ordered = sorted(examples, key=lambda example: example.report_date)
    targets = [target_value(example, target_name) for example in ordered]
    model = fit_logistic_model(
        ordered,
        targets,
        learning_rate=learning_rate,
        epochs=epochs,
    )
    return ModelArtifact(
        model_type="logistic_regression",
        target_name=target_name,
        horizon_days=horizon_days,
        trained_through=ordered[-1].report_date,
        training_count=len(ordered),
        feature_names=model.feature_names,
        weights=model.weights,
        intercept=model.intercept,
        scales=model.scales,
    )


def save_model_artifact(artifact: ModelArtifact, path: Path) -> Path:
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
                "weights": list(artifact.weights),
                "intercept": artifact.intercept,
                "scales": artifact.scales,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return path


def load_model_artifact(path: Path) -> ModelArtifact:
    payload = json.loads(path.read_text())
    return ModelArtifact(
        model_type=str(payload["model_type"]),
        target_name=str(payload["target_name"]),
        horizon_days=int(payload["horizon_days"]),
        trained_through=date.fromisoformat(str(payload["trained_through"])),
        training_count=int(payload["training_count"]),
        feature_names=tuple(str(name) for name in payload["feature_names"]),
        weights=tuple(float(weight) for weight in payload["weights"]),
        intercept=float(payload["intercept"]),
        scales={str(name): float(value) for name, value in payload["scales"].items()},
    )
