from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from energy_etf_monitor.commodities import WTI, CommodityConfig
from energy_etf_monitor.config import Settings
from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.cftc import CftcCotConnector
from energy_etf_monitor.ingestion.eia import EiaSeriesConnector
from energy_etf_monitor.ingestion.fred import FredSeriesConnector
from energy_etf_monitor.ingestion.yahoo import YahooFuturesConnector
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


class EiaConnectorLike(Protocol):
    def fetch_series(self, series_id: str) -> list[TimeSeriesObservation]: ...


class FredConnectorLike(Protocol):
    def fetch_observations(self, series_id: str) -> list[TimeSeriesObservation]: ...


class CftcConnectorLike(Protocol):
    def fetch_positions(
        self,
        *,
        commodity: str,
        contract_market_code: str,
        limit: int,
    ) -> list[CotPosition]: ...


class CurveProviderLike(Protocol):
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
    error: str | None = None


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

    @property
    def failures(self) -> list[SourceRunResult]:
        return [run for run in self.runs if run.error is not None]


class PhaseZeroIngestionRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        eia_connector: EiaConnectorLike | None = None,
        fred_connector: FredConnectorLike | None = None,
        cftc_connector: CftcConnectorLike | None = None,
        curve_provider: CurveProviderLike | None = None,
        repository_factory: Callable[
            [Settings],
            IngestionRepository,
        ] = IngestionRepository.from_settings,
        commodities: Sequence[CommodityConfig] = (WTI,),
        eia_series: Sequence[str] = PHASE0_EIA_SERIES,
        fred_series: Sequence[str] = PHASE0_FRED_SERIES,
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
        self.curve_provider = curve_provider or YahooFuturesConnector(raw_store=raw_store)
        self.repository_factory = repository_factory
        self.commodities = tuple(commodities)
        # Fold each commodity's inventory series into the EIA list (order-stable, de-duplicated),
        # and derive the futures curve products straight from the commodity set.
        self.eia_series = tuple(
            dict.fromkeys(
                [*eia_series, *(config.inventory_series_id for config in self.commodities)]
            )
        )
        self.fred_series = tuple(fred_series)
        self.curve_products = tuple(
            dict.fromkeys(config.product_code for config in self.commodities)
        )

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
            self._fetch_all(runs, repository=None, trade_date=trade_date, cot_limit=cot_limit)
        else:
            with repository_context as repository:
                self._fetch_all(
                    runs,
                    repository=repository,
                    trade_date=trade_date,
                    cot_limit=cot_limit,
                )

        return BatchIngestionResult(runs=runs)

    def _fetch_all(
        self,
        runs: list[SourceRunResult],
        *,
        repository: IngestionRepository | None,
        trade_date: date,
        cot_limit: int,
    ) -> None:
        for series_id in self.eia_series:
            self._ingest_source(
                runs,
                source="eia",
                name=series_id,
                fetch=lambda series_id=series_id: self.eia_connector.fetch_series(series_id),
                load=repository.upsert_time_series if repository is not None else None,
            )
        for series_id in self.fred_series:
            self._ingest_source(
                runs,
                source="fred",
                name=series_id,
                fetch=lambda series_id=series_id: self.fred_connector.fetch_observations(series_id),
                load=repository.upsert_time_series if repository is not None else None,
            )
        for config in self.commodities:
            self._ingest_source(
                runs,
                source="cftc",
                name=f"{config.name} COT",
                fetch=lambda config=config: self.cftc_connector.fetch_positions(
                    commodity=config.name,
                    contract_market_code=config.cot_contract_market_code,
                    limit=cot_limit,
                ),
                load=repository.upsert_cot_positions if repository is not None else None,
            )
        for product_code in self.curve_products:
            self._ingest_source(
                runs,
                source="yahoo",
                name=f"{product_code} curve",
                fetch=lambda product_code=product_code: self.curve_provider.fetch_curve(
                    product_code=product_code, trade_date=trade_date
                ),
                load=repository.upsert_futures_settlements if repository is not None else None,
            )

    def _ingest_source(
        self,
        runs: list[SourceRunResult],
        *,
        source: str,
        name: str,
        fetch: Callable[[], list],
        load: Callable[[list], LoadResult] | None,
    ) -> None:
        """Fetch (and optionally load) one source, isolating failures so a single flaky
        upstream source (timeout, parse error, outage) is recorded and skipped rather than
        aborting the whole batch."""

        try:
            rows = fetch()
        except Exception as exc:
            runs.append(SourceRunResult(source=source, name=name, fetched=0, error=repr(exc)))
            return
        load_result = load(rows) if load is not None else None
        runs.append(
            SourceRunResult(
                source=source, name=name, fetched=len(rows), load_result=load_result
            )
        )
