from sqlmodel import SQLModel, create_engine

from energy_etf_monitor.config import Settings


def create_engine_from_settings(settings: Settings):
    return create_engine(settings.database_url)


def create_db_and_tables(settings: Settings) -> None:
    engine = create_engine_from_settings(settings)
    try:
        SQLModel.metadata.create_all(engine)
    finally:
        engine.dispose()
