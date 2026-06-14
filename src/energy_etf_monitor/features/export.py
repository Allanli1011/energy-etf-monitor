from collections.abc import Sequence
from pathlib import Path

import duckdb

from energy_etf_monitor.records import DailyFeatureRow

FEATURE_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "VARCHAR"),
    ("commodity", "VARCHAR"),
    ("report_date", "DATE"),
    ("knowledge_date", "TIMESTAMP"),
    ("cl_front_month_settlement", "DOUBLE"),
    ("cl_m1_m2_spread", "DOUBLE"),
    ("cl_m2_m3_spread", "DOUBLE"),
    ("cl_m3_m6_spread", "DOUBLE"),
    ("cl_curve_curvature_m1_m2_m3", "DOUBLE"),
    ("cl_front_month_return_1d", "DOUBLE"),
    ("cl_carry_m1_m2", "DOUBLE"),
    ("cl_carry_m1_m2_change_1d", "DOUBLE"),
    ("cot_swap_dealer_net", "DOUBLE"),
    ("cot_swap_dealer_net_zscore", "DOUBLE"),
    ("cot_swap_dealer_net_index", "DOUBLE"),
    ("cot_open_interest", "DOUBLE"),
    ("inventory_value", "DOUBLE"),
    ("inventory_seasonal_surprise", "DOUBLE"),
    ("usd_index_value", "DOUBLE"),
    ("real_yield_10y", "DOUBLE"),
    ("crowding_aum_to_oi", "DOUBLE"),
    ("crowding_contracts_to_oi", "DOUBLE"),
    ("roll_window_flag", "DOUBLE"),
    ("roll_window_crowding_interaction", "DOUBLE"),
    ("news_count", "DOUBLE"),
    ("news_tone_mean", "DOUBLE"),
    ("news_impact_score", "DOUBLE"),
    ("quarantine", "BOOLEAN"),
)


def export_daily_features_to_parquet(
    rows: Sequence[DailyFeatureRow],
    destination: Path,
) -> Path:
    """Write feature rows to a modeling-ready Parquet cache."""

    output_path = _resolve_output_path(destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect() as connection:
        connection.execute(f"CREATE TABLE feature_rows ({_column_schema()})")
        if rows:
            connection.executemany(
                f"INSERT INTO feature_rows VALUES ({_placeholders()})",
                [_row_values(row) for row in rows],
            )
        connection.execute(
            f"COPY feature_rows TO '{_escape_duckdb_path(output_path)}' (FORMAT PARQUET)"
        )
    return output_path


def _resolve_output_path(destination: Path) -> Path:
    if destination.suffix.lower() == ".parquet":
        return destination
    return destination / "wti_daily_features.parquet"


def _column_schema() -> str:
    return ", ".join(f"{name} {column_type}" for name, column_type in FEATURE_EXPORT_COLUMNS)


def _placeholders() -> str:
    return ", ".join("?" for _ in FEATURE_EXPORT_COLUMNS)


def _row_values(row: DailyFeatureRow) -> tuple:
    return tuple(getattr(row, name) for name, _ in FEATURE_EXPORT_COLUMNS)


def _escape_duckdb_path(path: Path) -> str:
    return str(path).replace("'", "''")
