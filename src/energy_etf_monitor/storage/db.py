from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, create_engine

from energy_etf_monitor.config import Settings
from energy_etf_monitor.storage import models as _models  # noqa: F401

# The models import populates SQLModel.metadata before create_all().


def create_engine_from_settings(settings: Settings):
    _ensure_sqlite_parent(settings.database_url)
    return create_engine(settings.database_url)


def create_db_and_tables(settings: Settings) -> None:
    engine = create_engine_from_settings(settings)
    try:
        SQLModel.metadata.create_all(engine)
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
