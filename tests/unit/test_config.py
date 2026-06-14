from pathlib import Path

from energy_etf_monitor.config import Settings


def test_settings_derives_raw_and_processed_dirs(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.raw_data_dir == tmp_path / "raw"
    assert settings.processed_data_dir == tmp_path / "processed"


def test_settings_accepts_optional_api_keys(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        eia_api_key="eia-key",
        fred_api_key="fred-key",
        cftc_app_token="cftc-token",
    )

    assert settings.eia_api_key == "eia-key"
    assert settings.fred_api_key == "fred-key"
    assert settings.cftc_app_token == "cftc-token"

