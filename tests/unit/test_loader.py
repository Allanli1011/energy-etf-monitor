from datetime import date, timedelta

import pytest

from energy_etf_monitor.modeling.artifacts import save_model_artifact, train_logistic_artifact
from energy_etf_monitor.modeling.dataset import SupervisedExample
from energy_etf_monitor.modeling.loader import load_artifact


def _examples() -> list[SupervisedExample]:
    base = date(2026, 1, 1)
    examples = []
    for index in range(8):
        carry = 0.4 if index % 2 == 0 else -0.4
        target = 1 if carry > 0 else 0
        examples.append(
            SupervisedExample(
                report_date=base + timedelta(days=index),
                features={"cl_carry_m1_m2": carry},
                price_direction_target=target,
                spread_direction_target=target,
                target_report_date=base + timedelta(days=index + 5),
            )
        )
    return examples


def test_load_artifact_dispatches_logistic(tmp_path) -> None:
    artifact = train_logistic_artifact(_examples(), target_name="price_direction", horizon_days=5)
    path = save_model_artifact(artifact, tmp_path / "logistic.json")

    loaded = load_artifact(path)

    assert loaded.model_type == "logistic_regression"
    assert 0 <= loaded.predict({"cl_carry_m1_m2": 0.4}) <= 1


def test_load_artifact_dispatches_lightgbm(tmp_path) -> None:
    pytest.importorskip("lightgbm")
    from energy_etf_monitor.modeling.gbm import save_gbm_artifact, train_gbm_artifact

    artifact = train_gbm_artifact(_examples(), target_name="price_direction", horizon_days=5)
    path = save_gbm_artifact(artifact, tmp_path / "gbm.json")

    loaded = load_artifact(path)

    assert loaded.model_type == "lightgbm"
    assert 0 <= loaded.predict({"cl_carry_m1_m2": 0.4}) <= 1
