from datetime import UTC, date, datetime

from energy_etf_monitor.config import Settings
from energy_etf_monitor.ingestion.runner import (
    PHASE0_EIA_SERIES,
    PHASE0_FRED_SERIES,
    PhaseZeroIngestionRunner,
)
from energy_etf_monitor.records import CotPosition, FuturesSettlement, TimeSeriesObservation
from energy_etf_monitor.storage.repository import LoadResult


def _observation(series_id: str) -> TimeSeriesObservation:
    return TimeSeriesObservation(
        source="test",
        series_id=series_id,
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        value=1.0,
    )


def _cot_position() -> CotPosition:
    return CotPosition(
        source="cftc",
        commodity="WTI",
        market_name="CRUDE OIL, LIGHT SWEET",
        contract_market_code="067651",
        report_date=date(2026, 6, 9),
        knowledge_date=datetime(2026, 6, 12, 19, 30, tzinfo=UTC),
        open_interest=100,
    )


def _settlement() -> FuturesSettlement:
    return FuturesSettlement(
        source="cme",
        product_code="CL",
        report_date=date(2026, 6, 12),
        knowledge_date=datetime(2026, 6, 13, tzinfo=UTC),
        contract_month=date(2026, 7, 1),
        settlement_price=73.25,
    )


def test_phase_zero_runner_fetches_configured_sources_without_loading(tmp_path) -> None:
    calls: dict[str, list] = {"eia": [], "fred": [], "cot": [], "cme": []}

    class FakeEia:
        def fetch_series(self, series_id: str):
            calls["eia"].append(series_id)
            return [_observation(series_id)]

    class FakeFred:
        def fetch_observations(self, series_id: str):
            calls["fred"].append(series_id)
            return [_observation(series_id)]

    class FakeCftc:
        def fetch_wti_positions(self, limit: int):
            calls["cot"].append(limit)
            return [_cot_position()]

    class FakeCme:
        def fetch_curve(self, *, product_code: str, trade_date: date):
            calls["cme"].append((product_code, trade_date))
            return [_settlement()]

    runner = PhaseZeroIngestionRunner(
        settings=Settings(data_dir=tmp_path),
        eia_connector=FakeEia(),
        fred_connector=FakeFred(),
        cftc_connector=FakeCftc(),
        cme_provider=FakeCme(),
    )

    result = runner.run(load=False, trade_date=date(2026, 6, 12), cot_limit=25)

    assert calls["eia"] == list(PHASE0_EIA_SERIES)
    assert calls["fred"] == list(PHASE0_FRED_SERIES)
    assert calls["cot"] == [25]
    assert calls["cme"] == [("CL", date(2026, 6, 12))]
    assert result.fetched_total == len(PHASE0_EIA_SERIES) + len(PHASE0_FRED_SERIES) + 2
    assert result.loaded_total == 0


def test_phase_zero_runner_loads_records_with_matching_repository_methods(tmp_path) -> None:
    loaded: dict[str, int] = {}

    class FakeEia:
        def fetch_series(self, series_id: str):
            return [_observation(series_id)]

    class FakeFred:
        def fetch_observations(self, series_id: str):
            return [_observation(series_id)]

    class FakeCftc:
        def fetch_wti_positions(self, limit: int):
            return [_cot_position()]

    class FakeCme:
        def fetch_curve(self, *, product_code: str, trade_date: date):
            return [_settlement()]

    class FakeRepository:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def upsert_time_series(self, records):
            loaded["time_series"] = loaded.get("time_series", 0) + len(records)
            return LoadResult(inserted=len(records))

        def upsert_cot_positions(self, records):
            loaded["cot"] = len(records)
            return LoadResult(inserted=len(records))

        def upsert_futures_settlements(self, records):
            loaded["settlements"] = len(records)
            return LoadResult(inserted=len(records))

    runner = PhaseZeroIngestionRunner(
        settings=Settings(data_dir=tmp_path),
        eia_connector=FakeEia(),
        fred_connector=FakeFred(),
        cftc_connector=FakeCftc(),
        cme_provider=FakeCme(),
        repository_factory=lambda settings: FakeRepository(),
    )

    result = runner.run(load=True, trade_date=date(2026, 6, 12), cot_limit=25)

    assert loaded == {
        "time_series": len(PHASE0_EIA_SERIES) + len(PHASE0_FRED_SERIES),
        "cot": 1,
        "settlements": 1,
    }
    assert result.loaded_total == result.fetched_total

