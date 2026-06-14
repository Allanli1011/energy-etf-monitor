from datetime import UTC, date, datetime, timedelta

import pytest

pytest.importorskip("lightgbm")

from energy_etf_monitor.modeling.dataset import SupervisedExample  # noqa: E402
from energy_etf_monitor.modeling.gbm import (  # noqa: E402
    load_gbm_artifact,
    save_gbm_artifact,
    train_gbm_artifact,
)
from energy_etf_monitor.modeling.predict import predict_two_head  # noqa: E402
from energy_etf_monitor.records import DailyFeatureRow  # noqa: E402


def _examples(count: int = 24) -> list[SupervisedExample]:
    base = date(2026, 1, 1)
    examples = []
    for index in range(count):
        carry = 0.5 if index % 2 == 0 else -0.5
        target = 1 if carry > 0 else 0
        examples.append(
            SupervisedExample(
                report_date=base + timedelta(days=index),
                features={
                    "cl_carry_m1_m2": carry,
                    "inventory_seasonal_surprise": float(index),
                },
                price_direction_target=target,
                spread_direction_target=target,
                target_report_date=base + timedelta(days=index + 5),
            )
        )
    return examples


def test_gbm_artifact_trains_learns_signal_and_round_trips(tmp_path) -> None:
    artifact = train_gbm_artifact(_examples(), target_name="price_direction", horizon_days=5)

    assert artifact.model_type == "lightgbm"
    assert artifact.target_name == "price_direction"
    assert artifact.training_count == 24
    assert artifact.trained_through == date(2026, 1, 24)

    up = artifact.predict({"cl_carry_m1_m2": 0.5, "inventory_seasonal_surprise": 3.0})
    down = artifact.predict({"cl_carry_m1_m2": -0.5, "inventory_seasonal_surprise": 3.0})
    assert 0 <= up <= 1
    assert 0 <= down <= 1
    assert up > down  # learned the carry -> direction signal

    contributions = artifact.raw_contributions(
        {"cl_carry_m1_m2": 0.5, "inventory_seasonal_surprise": 3.0}
    )
    assert set(contributions) == {"cl_carry_m1_m2", "inventory_seasonal_surprise"}

    path = save_gbm_artifact(artifact, tmp_path / "wti_price_gbm.json")
    loaded = load_gbm_artifact(path)
    assert loaded.predict(
        {"cl_carry_m1_m2": 0.5, "inventory_seasonal_surprise": 3.0}
    ) == pytest.approx(up)


def test_predict_two_head_works_with_gbm_artifacts() -> None:
    price = train_gbm_artifact(_examples(), target_name="price_direction", horizon_days=5)
    spread = train_gbm_artifact(_examples(), target_name="spread_direction", horizon_days=5)
    feature_row = DailyFeatureRow(
        source="feature_pipeline",
        commodity="WTI",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
        cl_carry_m1_m2=0.5,
        inventory_seasonal_surprise=3.0,
        cl_front_month_return_1d=0.01,
        cl_carry_m1_m2_change_1d=-0.002,
    )

    prediction = predict_two_head(
        feature_row=feature_row,
        price_artifact=price,
        spread_artifact=spread,
        predicted_at=datetime(2026, 6, 12, 18, tzinfo=UTC),
    )

    assert 0 <= prediction.price_up_probability <= 1
    assert 0 <= prediction.spread_up_probability <= 1
    assert prediction.price_model_version.startswith("lightgbm:price_direction")
    assert prediction.price_top_drivers != "[]"
