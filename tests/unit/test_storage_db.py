from pathlib import Path

from sqlalchemy import inspect

from energy_etf_monitor.config import Settings
from energy_etf_monitor.storage.db import create_db_and_tables, create_engine_from_settings


def test_create_db_and_tables_creates_phase_zero_tables(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'monitor.db'}",
    )

    create_db_and_tables(settings)

    engine = create_engine_from_settings(settings)
    tables = set(inspect(engine).get_table_names())

    assert "time_series_observations" in tables
    assert "cot_positions" in tables
    assert "futures_settlements" in tables
    assert "fund_daily_metrics" in tables
    assert "fund_holdings" in tables
    assert "fund_crowding_metrics" in tables
    assert "daily_feature_rows" in tables
    engine.dispose()
