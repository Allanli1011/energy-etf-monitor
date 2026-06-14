from datetime import UTC, date, datetime

import pytest

from energy_etf_monitor.modeling.artifacts import ModelArtifact
from energy_etf_monitor.modeling.predict import (
    feature_dict_from_row,
    parse_top_drivers,
    predict_two_head,
)
from energy_etf_monitor.records import DailyFeatureRow

FEATURES = ("cl_carry_m1_m2", "inventory_seasonal_surprise", "cot_swap_dealer_net_zscore")


def _artifact(target_name, *, weights, feature_names=FEATURES, horizon_days=5):
    return ModelArtifact(
        model_type="logistic_regression",
        target_name=target_name,
        horizon_days=horizon_days,
        trained_through=date(2026, 6, 1),
        training_count=100,
        feature_names=feature_names,
        weights=weights,
        intercept=0.0,
        scales={name: 1.0 for name in feature_names},
    )


def _feature_row(**overrides) -> DailyFeatureRow:
    base = dict(
        source="feature_pipeline",
        commodity="WTI",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, 16, tzinfo=UTC),
        cl_carry_m1_m2=0.5,
        inventory_seasonal_surprise=2.0,
        cot_swap_dealer_net_zscore=-1.0,
        cl_front_month_return_1d=0.01,
        cl_carry_m1_m2_change_1d=-0.002,
    )
    base.update(overrides)
    return DailyFeatureRow(**base)


def test_predict_two_head_produces_probabilities_drivers_and_naive() -> None:
    price = _artifact("price_direction", weights=(2.0, 0.1, 0.0))
    spread = _artifact("spread_direction", weights=(0.0, 0.0, 1.5))

    prediction = predict_two_head(
        feature_row=_feature_row(),
        price_artifact=price,
        spread_artifact=spread,
        predicted_at=datetime(2026, 6, 12, 18, tzinfo=UTC),
    )

    assert 0 <= prediction.price_up_probability <= 1
    assert 0 <= prediction.spread_up_probability <= 1
    # price head dominated by cl_carry_m1_m2 (2.0 * 0.5 = 1.0 contribution)
    price_drivers = parse_top_drivers(prediction.price_top_drivers)
    assert price_drivers[0].feature == "cl_carry_m1_m2"
    spread_drivers = parse_top_drivers(prediction.spread_top_drivers)
    assert spread_drivers[0].feature == "cot_swap_dealer_net_zscore"
    # naive persistence reads the sign of the latest 1-day move
    assert prediction.price_naive_probability == 1.0
    assert prediction.spread_naive_probability == 0.0
    assert prediction.horizon_days == 5
    assert prediction.report_date == date(2026, 6, 12)
    assert "through2026-06-01" in prediction.price_model_version


def test_predict_two_head_rejects_swapped_target_roles() -> None:
    price = _artifact("price_direction", weights=(1.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="spread_direction"):
        predict_two_head(
            feature_row=_feature_row(),
            price_artifact=price,
            spread_artifact=price,
            predicted_at=datetime(2026, 6, 12, 18, tzinfo=UTC),
        )


def test_predict_two_head_rejects_horizon_mismatch() -> None:
    price = _artifact("price_direction", weights=(1.0, 0.0, 0.0), horizon_days=5)
    spread = _artifact("spread_direction", weights=(1.0, 0.0, 0.0), horizon_days=3)
    with pytest.raises(ValueError, match="horizon"):
        predict_two_head(
            feature_row=_feature_row(),
            price_artifact=price,
            spread_artifact=spread,
            predicted_at=datetime(2026, 6, 12, 18, tzinfo=UTC),
        )


def test_predict_two_head_rejects_predicting_before_feature_is_known() -> None:
    price = _artifact("price_direction", weights=(1.0, 0.0, 0.0))
    spread = _artifact("spread_direction", weights=(1.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="predicted_at"):
        predict_two_head(
            feature_row=_feature_row(knowledge_date=datetime(2026, 6, 12, 20, tzinfo=UTC)),
            price_artifact=price,
            spread_artifact=spread,
            predicted_at=datetime(2026, 6, 12, 18, tzinfo=UTC),
        )


def test_feature_dict_excludes_target_source_columns_and_fills_missing() -> None:
    features = feature_dict_from_row(_feature_row(cl_carry_m1_m2=0.5))
    assert "cl_front_month_settlement" not in features
    assert "cl_m1_m2_spread" not in features
    assert features["cl_carry_m1_m2"] == 0.5
    # a column with no value on the row falls back to 0.0
    assert features["real_yield_10y"] == 0.0
