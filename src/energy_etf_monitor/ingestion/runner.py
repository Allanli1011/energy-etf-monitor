from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from energy_etf_monitor.config import Settings
from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.cftc import CftcCotConnector
from energy_etf_monitor.ingestion.cme import CmeSettlementCurveProvider
from energy_etf_monitor.ingestion.eia import EiaSeriesConnector
from energy_etf_monitor.ingestion.fred import FredSeriesConnector
from energy_etf_monitor.records import CotPosition, FuturesSettlement, TimeSeriesObservation
from energy_etf_monitor.storage.repository import IngestionRepository, LoadResult

PHASE0_EIA_SERIES = (
    "WCESTUS1",
    "WCRSTUS1",
    "WCSSTUS1",
    "W_EPC0_SAX_YCUOK_MBBL",
)
PHASE0_FRED_SERIES = (
    "DTWEXBGS",
    "DFII10",
    "DCOILWTICO",
    "GASREGW",
)
PHASE0_CME_PRODUCTS = ("CL",)


class EiaConnectorLike(Protocol):
    def fetch_series(self, series_id: str) -> list[TimeSeriesObservation]: ...


class FredConnectorLike(Protocol):
    def fetch_observations(self, series_id: str) -> list[TimeSeriesObservation]: ...


class CftcConnectorLike(Protocol):
    def fetch_wti_positions(self, limit: int) -> list[CotPosition]: ...


class CmeProviderLike(Protocol):
    def fetch_curve(
        self,
        *,
        product_code: str,
        trade_date: date,
    ) -> list[FuturesSettlement]: ...


@dataclass(frozen=True)
class SourceRunResult:
    source: str
    name: str
    fetched: int
    load_result: LoadResult | None = None


@dataclass(frozen=True)
class BatchIngestionResult:
    runs: list[SourceRunResult] = field(default_factory=list)

    @property
    def fetched_total(self) -> int:
        return sum(run.fetched for run in self.runs)

    @property
    def loaded_total(self) -> int:
        return sum(run.load_result.total for run in self.runs if run.load_result is not None)

    @property
    def quarantined_total(self) -> int:
        return sum(run.load_result.quarantined for run in self.runs if run.load_result is not None)


class PhaseZeroIngestionRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        eia_connector: EiaConnectorLike | None = None,
        fred_connector: FredConnectorLike | None = None,
        cftc_connector: CftcConnectorLike | None = None,
        cme_provider: CmeProviderLike | None = None,
        repository_factory: Callable[
            [Settings],
            IngestionRepository,
        ] = IngestionRepository.from_settings,
        eia_series: Sequence[str] = PHASE0_EIA_SERIES,
        fred_series: Sequence[str] = PHASE0_FRED_SERIES,
        cme_products: Sequence[str] = PHASE0_CME_PRODUCTS,
    ) -> None:
        raw_store = RawPayloadStore(settings.raw_data_dir)
        self.settings = settings
        self.eia_connector = eia_connector or EiaSeriesConnector(
            api_key=settings.eia_api_key,
            raw_store=raw_store,
        )
        self.fred_connector = fred_connector or FredSeriesConnector(
            api_key=settings.fred_api_key,
            raw_store=raw_store,
        )
        self.cftc_connector = cftc_connector or CftcCotConnector(
            app_token=settings.cftc_app_token,
            raw_store=raw_store,
        )
        self.cme_provider = cme_provider or CmeSettlementCurveProvider(raw_store=raw_store)
        self.repository_factory = repository_factory
        self.eia_series = tuple(eia_series)
        self.fred_series = tuple(fred_series)
        self.cme_products = tuple(cme_products)

    def run(
        self,
        *,
        load: bool,
        trade_date: date,
        cot_limit: int = 5000,
    ) -> BatchIngestionResult:
        runs: list[SourceRunResult] = []

        repository_context = self.repository_factory(self.settings) if load else None
        if repository_context is None:
            self._fetch_all_without_loading(runs, trade_date=trade_date, cot_limit=cot_limit)
        else:
            with repository_context as repository:
                self._fetch_all_with_loading(
                    runs,
                    repository=repository,
                    trade_date=trade_date,
                    cot_limit=cot_limit,
                )

        return BatchIngestionResult(runs=runs)

    def _fetch_all_without_loading(
        self,
        runs: list[SourceRunResult],
        *,
        trade_date: date,
        cot_limit: int,
    ) -> None:
        for series_id in self.eia_series:
            rows = self.eia_connector.fetch_series(series_id)
            runs.append(SourceRunResult(source="eia", name=series_id, fetched=len(rows)))
        for series_id in self.fred_series:
            rows = self.fred_connector.fetch_observations(series_id)
            runs.append(SourceRunResult(source="fred", name=series_id, fetched=len(rows)))
        cot_rows = self.cftc_connector.fetch_wti_positions(limit=cot_limit)
        runs.append(SourceRunResult(source="cftc", name="WTI COT", fetched=len(cot_rows)))
        for product_code in self.cme_products:
            rows = self.cme_provider.fetch_curve(product_code=product_code, trade_date=trade_date)
            runs.append(
                SourceRunResult(
                    source="cme",
                    name=f"{product_code} curve",
                    fetched=len(rows),
                )
            )

    def _fetch_all_with_loading(
        self,
        runs: list[SourceRunResult],
        *,
        repository: IngestionRepository,
        trade_date: date,
        cot_limit: int,
    ) -> None:
        for series_id in self.eia_series:
            rows = self.eia_connector.fetch_series(series_id)
            runs.append(
                SourceRunResult(
                    source="eia",
                    name=series_id,
                    fetched=len(rows),
                    load_result=repository.upsert_time_series(rows),
                )
            )
        for series_id in self.fred_series:
            rows = self.fred_connector.fetch_observations(series_id)
            runs.append(
                SourceRunResult(
                    source="fred",
                    name=series_id,
                    fetched=len(rows),
                    load_result=repository.upsert_time_series(rows),
                )
            )
        cot_rows = self.cftc_connector.fetch_wti_positions(limit=cot_limit)
        runs.append(
            SourceRunResult(
                source="cftc",
                name="WTI COT",
                fetched=len(cot_rows),
                load_result=repository.upsert_cot_positions(cot_rows),
            )
        )
        for product_code in self.cme_products:
            rows = self.cme_provider.fetch_curve(product_code=product_code, trade_date=trade_date)
            runs.append(
                SourceRunResult(
                    source="cme",
                    name=f"{product_code} curve",
                    fetched=len(rows),
                    load_result=repository.upsert_futures_settlements(rows),
                )
            )
