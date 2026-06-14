from datetime import UTC, date, datetime, timedelta

from energy_etf_monitor.features.export import export_daily_features_to_parquet
from energy_etf_monitor.modeling.artifacts import train_logistic_artifact
from energy_etf_monitor.modeling.dataset import build_pooled_examples
from energy_etf_monitor.records import DailyFeatureRow


def _cache(tmp_path, *, commodity: str, prices: list[float]):
    rows = []
    for offset, price in enumerate(prices):
        rows.append(
            DailyFeatureRow(
                source="feature_pipeline",
                commodity=commodity,
                report_date=date(2026, 6, 1) + timedelta(days=offset),
                knowledge_date=datetime(2026, 6, 1, 18, tzinfo=UTC) + timedelta(days=offset),
                cl_front_month_settlement=price,
                cl_m1_m2_spread=-0.5 + 0.01 * offset,
                cl_carry_m1_m2=-0.01 + 0.001 * offset,
            )
        )
    return export_daily_features_to_parquet(rows, tmp_path / f"{commodity.lower()}.parquet")


def test_build_pooled_examples_adds_commodity_one_hot(tmp_path) -> None:
    caches = {
        "WTI": _cache(tmp_path, commodity="WTI", prices=[70, 71, 72, 73]),
        "NATGAS": _cache(tmp_path, commodity="NATGAS", prices=[3.5, 3.4, 3.6, 3.7]),
    }

    examples = build_pooled_examples(caches, horizon_days=1)

    # both commodities contribute, each example carries both dummies
    assert len(examples) == 6  # 3 per commodity (4 rows, horizon 1)
    for example in examples:
        assert "commodity__WTI" in example.features
        assert "commodity__NATGAS" in example.features
        active = [k for k in ("commodity__WTI", "commodity__NATGAS") if example.features[k] == 1.0]
        assert len(active) == 1  # exactly one active dummy


def test_pooled_examples_train_a_model_that_uses_dummies(tmp_path) -> None:
    caches = {
        "WTI": _cache(tmp_path, commodity="WTI", prices=[70, 71, 72, 73, 74, 75]),
        "NATGAS": _cache(tmp_path, commodity="NATGAS", prices=[3.5, 3.4, 3.6, 3.7, 3.8, 3.9]),
    }
    examples = build_pooled_examples(caches, horizon_days=1)

    artifact = train_logistic_artifact(examples, target_name="price_direction", horizon_days=1)

    assert "commodity__WTI" in artifact.feature_names
    assert "commodity__NATGAS" in artifact.feature_names
    assert artifact.training_count == len(examples)
