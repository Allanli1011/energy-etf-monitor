from datetime import date, datetime, timedelta

from energy_etf_monitor.features.export import export_daily_features_to_parquet
from energy_etf_monitor.modeling.baselines import evaluate_walk_forward_baselines
from energy_etf_monitor.modeling.dataset import (
    SupervisedExample,
    build_supervised_examples,
    load_feature_cache,
)
from energy_etf_monitor.records import DailyFeatureRow


def test_feature_cache_builds_forward_price_and_spread_targets(tmp_path) -> None:
    cache_path = _write_feature_cache(
        tmp_path,
        prices=[70, 71, 69, 73],
        spreads=[-2, -1, -3, 1],
    )

    rows = load_feature_cache(cache_path)
    examples = build_supervised_examples(rows, horizon_days=2)

    assert [example.report_date for example in examples] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
    ]
    assert [example.price_direction_target for example in examples] == [0, 1]
    assert [example.spread_direction_target for example in examples] == [0, 1]
    assert [example.target_report_date for example in examples] == [
        date(2026, 6, 3),
        date(2026, 6, 4),
    ]
    assert examples[0].features["cl_carry_m1_m2"] == -0.01
    assert "cl_front_month_settlement" not in examples[0].features


def test_walk_forward_baselines_use_expanding_past_window_only(tmp_path) -> None:
    cache_path = _write_feature_cache(
        tmp_path,
        prices=[70, 71, 72, 73, 72, 74, 75],
        spreads=[-3, -2, -1, 0, -1, 1, 2],
    )
    examples = build_supervised_examples(load_feature_cache(cache_path), horizon_days=1)

    report = evaluate_walk_forward_baselines(
        examples,
        target_name="price_direction",
        min_train_size=3,
        learning_rate=0.4,
        epochs=80,
    )

    assert report.target_name == "price_direction"
    # With horizon=1 the most recent training example's label realizes on the decision date
    # itself, so it is purged: the first eligible decision is 6/5 (3 fully-realized labels),
    # not 6/4. A leaky implementation would have produced rows at 6/4..6/6 with sizes 3,4,5.
    assert [row.report_date for row in report.rows] == [
        date(2026, 6, 5),
        date(2026, 6, 6),
    ]
    assert [row.train_size for row in report.rows] == [3, 4]
    assert all(0 <= row.naive_probability <= 1 for row in report.rows)
    assert all(0 <= row.logistic_probability <= 1 for row in report.rows)
    assert report.metrics["naive_accuracy"] >= 0
    assert report.metrics["logistic_brier"] >= 0


def test_walk_forward_purges_examples_whose_label_realizes_on_or_after_decision() -> None:
    # Labels become known on target_report_date (two calendar days after report_date here).
    # At each decision only strictly-realized labels may train; a naive ordered[:index] window
    # would over-count by the most recent (horizon) examples.
    examples = [
        _example(date(2026, 6, 1), target=1, target_report_date=date(2026, 6, 3)),
        _example(date(2026, 6, 2), target=0, target_report_date=date(2026, 6, 4)),
        _example(date(2026, 6, 3), target=1, target_report_date=date(2026, 6, 5)),
        _example(date(2026, 6, 4), target=0, target_report_date=date(2026, 6, 6)),
        _example(date(2026, 6, 5), target=1, target_report_date=date(2026, 6, 7)),
    ]

    report = evaluate_walk_forward_baselines(
        examples,
        target_name="price_direction",
        min_train_size=1,
        learning_rate=0.2,
        epochs=20,
    )

    rows_by_date = {row.report_date: row for row in report.rows}
    # Decision on 6/4: only 6/1's label (realized 6/3) is known -> train_size 1 (leaky would be 3).
    assert rows_by_date[date(2026, 6, 4)].train_size == 1
    # Decision on 6/5: 6/1 (6/3) and 6/2 (6/4) are known -> train_size 2 (leaky would be 4).
    assert rows_by_date[date(2026, 6, 5)].train_size == 2
    # 6/1..6/3 cannot be decided (fewer than min_train_size realized labels).
    assert date(2026, 6, 3) not in rows_by_date


def test_walk_forward_report_labels_regimes_and_slices_metrics() -> None:
    examples = [
        _example(date(2007, 12, 31), target=1),
        _example(date(2008, 1, 2), target=0),
        _example(date(2014, 6, 2), target=1),
        _example(date(2020, 3, 2), target=0),
        _example(date(2021, 2, 1), target=1),
        _example(date(2023, 1, 3), target=0),
    ]

    report = evaluate_walk_forward_baselines(
        examples,
        target_name="price_direction",
        min_train_size=1,
        learning_rate=0.2,
        epochs=20,
    )

    assert [row.regime for row in report.rows] == [
        "gfc_2008",
        "oil_crash_2014_2016",
        "covid_2020",
        "inflation_2021_2022",
        "other",
    ]
    assert set(report.regime_metrics) == {
        "gfc_2008",
        "oil_crash_2014_2016",
        "covid_2020",
        "inflation_2021_2022",
        "other",
    }
    assert report.regime_metrics["covid_2020"]["logistic_brier"] >= 0


def _example(
    report_date: date,
    *,
    target: int,
    target_report_date: date | None = None,
) -> SupervisedExample:
    return SupervisedExample(
        report_date=report_date,
        features={"cl_carry_m1_m2": float(report_date.month)},
        price_direction_target=target,
        spread_direction_target=1 - target,
        target_report_date=target_report_date or (report_date + timedelta(days=1)),
    )


def _write_feature_cache(
    tmp_path,
    *,
    prices: list[float],
    spreads: list[float],
):
    rows = []
    for offset, (price, spread) in enumerate(zip(prices, spreads, strict=True)):
        rows.append(
            DailyFeatureRow(
                source="feature_pipeline",
                commodity="WTI",
                report_date=date(2026, 6, 1) + timedelta(days=offset),
                knowledge_date=datetime(2026, 6, 1, 18) + timedelta(days=offset),
                cl_front_month_settlement=price,
                cl_m1_m2_spread=spread,
                cl_m2_m3_spread=spread - 1,
                cl_m3_m6_spread=spread - 2,
                cl_curve_curvature_m1_m2_m3=0.5,
                cl_front_month_return_1d=0.01 * offset,
                cl_carry_m1_m2=-0.01 + (0.002 * offset),
                cl_carry_m1_m2_change_1d=0.002,
                cot_swap_dealer_net=100 + (offset * 10),
                cot_swap_dealer_net_zscore=-1 + (0.2 * offset),
                cot_swap_dealer_net_index=offset * 10,
                cot_open_interest=1_000 + offset,
                inventory_value=420_000 + offset,
                inventory_seasonal_surprise=5_000 + offset,
                usd_index_value=104 + offset,
                real_yield_10y=1.5 + offset,
                crowding_aum_to_oi=0.05 + (0.001 * offset),
                crowding_contracts_to_oi=0.06 + (0.001 * offset),
                roll_window_flag=float(offset % 2),
                roll_window_crowding_interaction=0.05 * float(offset % 2),
            )
        )
    return export_daily_features_to_parquet(rows, tmp_path)
