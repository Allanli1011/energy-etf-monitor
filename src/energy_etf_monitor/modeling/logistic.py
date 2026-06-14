from dataclasses import dataclass
from math import exp, log

from energy_etf_monitor.modeling.dataset import SupervisedExample


@dataclass(frozen=True)
class LogisticModel:
    feature_names: tuple[str, ...]
    weights: tuple[float, ...]
    intercept: float
    scales: dict[str, float]

    def predict(self, features: dict[str, float]) -> float:
        vector = _feature_vector(features, self.feature_names, self.scales)
        score = self.intercept + sum(
            weight * value for weight, value in zip(self.weights, vector, strict=True)
        )
        return _sigmoid(score)


def fit_logistic_model(
    examples: list[SupervisedExample],
    targets: list[int],
    *,
    feature_names: tuple[str, ...] | None = None,
    learning_rate: float = 0.1,
    epochs: int = 100,
) -> LogisticModel:
    if not examples:
        raise ValueError("at least one training example is required")
    if len(examples) != len(targets):
        raise ValueError("examples and targets must have the same length")

    names = feature_names or tuple(
        sorted({name for example in examples for name in example.features})
    )
    weights = [0.0 for _ in names]
    intercept = _logit_prior(targets)
    scales = _feature_scales(examples, names)
    for _ in range(epochs):
        for example, target in zip(examples, targets, strict=True):
            vector = _feature_vector(example.features, names, scales)
            probability = _sigmoid(
                intercept + sum(w * x for w, x in zip(weights, vector, strict=True))
            )
            error = probability - target
            intercept -= learning_rate * error
            weights = [
                weight - (learning_rate * error * value)
                for weight, value in zip(weights, vector, strict=True)
            ]
    return LogisticModel(
        feature_names=names,
        weights=tuple(weights),
        intercept=intercept,
        scales=scales,
    )


def _feature_vector(
    features: dict[str, float],
    feature_names: tuple[str, ...],
    scales: dict[str, float],
) -> list[float]:
    return [features.get(name, 0.0) / scales[name] for name in feature_names]


def _feature_scales(
    examples: list[SupervisedExample],
    feature_names: tuple[str, ...],
) -> dict[str, float]:
    scales: dict[str, float] = {}
    for name in feature_names:
        max_abs = max(abs(example.features.get(name, 0.0)) for example in examples)
        scales[name] = max(max_abs, 1.0)
    return scales


def _logit_prior(targets: list[int]) -> float:
    positive_rate = (sum(targets) + 0.5) / (len(targets) + 1)
    return _safe_log(positive_rate / (1 - positive_rate))


def _safe_log(value: float) -> float:
    return log(value)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + exp(-value))
    exp_value = exp(value)
    return exp_value / (1 + exp_value)
