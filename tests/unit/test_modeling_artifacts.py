from datetime import date, timedelta
from math import isclose

import pytest

from energy_etf_monitor.modeling.artifacts import (
    load_model_artifact,
    save_model_artifact,
    train_logistic_artifact,
)
from energy_etf_monitor.modeling.dataset import SupervisedExample


def test_logistic_artifact_trains_predicts_and_round_trips(tmp_path) -> None:
    artifact = train_logistic_artifact(
        [
            _example(date(2026, 1, 1), carry=-0.2, inventory=100, target=0),
            _example(date(2026, 1, 2), carry=-0.1, inventory=101, target=0),
            _example(date(2026, 1, 3), carry=0.2, inventory=104, target=1),
            _example(date(2026, 1, 4), carry=0.3, inventory=106, target=1),
        ],
        target_name="price_direction",
        horizon_days=5,
        learning_rate=0.3,
        epochs=40,
    )

    assert artifact.model_type == "logistic_regression"
    assert artifact.target_name == "price_direction"
    assert artifact.horizon_days == 5
    assert artifact.feature_names == ("carry", "inventory")
    assert artifact.training_count == 4
    assert artifact.trained_through == date(2026, 1, 4)
    probability = artifact.predict({"carry": 0.25, "inventory": 105})
    assert 0 <= probability <= 1

    artifact_path = save_model_artifact(artifact, tmp_path / "price_model.json")
    loaded = load_model_artifact(artifact_path)

    assert loaded == artifact
    assert isclose(
        loaded.predict({"carry": 0.25, "inventory": 105}),
        probability,
        rel_tol=1e-12,
    )


def test_logistic_artifact_requires_training_examples() -> None:
    with pytest.raises(ValueError, match="at least one training example"):
        train_logistic_artifact(
            [],
            target_name="price_direction",
            horizon_days=5,
        )


def _example(
    report_date: date,
    *,
    carry: float,
    inventory: float,
    target: int,
) -> SupervisedExample:
    return SupervisedExample(
        report_date=report_date,
        features={"carry": carry, "inventory": inventory},
        price_direction_target=target,
        spread_direction_target=1 - target,
        target_report_date=report_date + timedelta(days=1),
    )
