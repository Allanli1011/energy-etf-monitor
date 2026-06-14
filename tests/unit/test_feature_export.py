from datetime import date, datetime

import duckdb

from energy_etf_monitor.features.export import export_daily_features_to_parquet
from energy_etf_monitor.records import DailyFeatureRow


def test_export_daily_features_to_parquet_writes_modeling_cache(tmp_path) -> None:
    row = DailyFeatureRow(
        source="feature_pipeline",
        commodity="WTI",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 12, 18),
        cl_front_month_settlement=70,
        cl_carry_m1_m2=-0.028571,
        cl_m1_m2_spread=-2,
        cl_m2_m3_spread=-3,
        cl_m3_m6_spread=-5,
        cl_curve_curvature_m1_m2_m3=1,
        cl_front_month_return_1d=0.014493,
        cl_carry_m1_m2_change_1d=0.000414,
        cot_swap_dealer_net=300,
        inventory_value=420_000,
    )

    output_path = export_daily_features_to_parquet([row], tmp_path)
    result = duckdb.connect().execute(
        """
        SELECT
          commodity,
          report_date,
          cl_front_month_settlement,
          cl_m2_m3_spread,
          cl_front_month_return_1d
        FROM read_parquet(?)
        """,
        [str(output_path)],
    ).fetchone()

    assert output_path == tmp_path / "wti_daily_features.parquet"
    assert result == ("WTI", date(2026, 6, 12), 70.0, -3.0, 0.014493)
