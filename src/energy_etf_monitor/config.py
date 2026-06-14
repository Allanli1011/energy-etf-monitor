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
    database_url: str = "sqlite:///data/state/energy_etf_monitor.sqlite"

    eia_api_key: str | None = None
    fred_api_key: str | None = None
    cftc_app_token: str | None = None
    marketaux_api_key: str | None = None
    anthropic_api_key: str | None = None

    news_classifier: str = "rule"  # "rule" or "llm"
    llm_model: str = "claude-haiku-4-5-20251001"
    alert_webhook_url: str | None = None
    alert_webhook_kind: str = "slack"  # "slack" or "ntfy"

    @computed_field
    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"

    @computed_field
    @property
    def processed_data_dir(self) -> Path:
        return self.data_dir / "processed"
