from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, create_engine

from energy_etf_monitor.config import Settings
from energy_etf_monitor.storage import models as _models  # noqa: F401

# The models import populates SQLModel.metadata before create_all().


def create_engine_from_settings(settings: Settings):
    _ensure_sqlite_parent(settings.database_url)
    return create_engine(settings.database_url)


# Additive, idempotent schema migrations: SQLModel.create_all() never adds columns to an existing
# table, so new nullable columns are backfilled here for the persisted SQLite state DB.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "cot_positions": [
        ("producer_merchant_long", "INTEGER"),
        ("producer_merchant_short", "INTEGER"),
        ("managed_money_long", "INTEGER"),
        ("managed_money_short", "INTEGER"),
        ("other_reportable_long", "INTEGER"),
        ("other_reportable_short", "INTEGER"),
    ],
}


def create_db_and_tables(settings: Settings) -> None:
    engine = create_engine_from_settings(settings)
    try:
        SQLModel.metadata.create_all(engine)
        if engine.dialect.name == "sqlite":
            with engine.begin() as connection:
                for table, columns in _ADDITIVE_COLUMNS.items():
                    present = {
                        row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
                    }
                    for name, ddl in columns:
                        if name not in present:
                            connection.exec_driver_sql(
                                f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                            )
    finally:
        engine.dispose()


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return

    database = url.database
    if not database or database == ":memory:":
        return

    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
