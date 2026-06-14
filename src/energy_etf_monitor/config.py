from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_prefix="ENERGY_ETF_MONITOR_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("data")
    database_url: str = "postgresql+psycopg://energy:energy@localhost:5432/energy_etf_monitor"

    eia_api_key: str | None = None
    fred_api_key: str | None = None
    cftc_app_token: str | None = None
    marketaux_api_key: str | None = None

    @computed_field
    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"

    @computed_field
    @property
    def processed_data_dir(self) -> Path:
        return self.data_dir / "processed"

