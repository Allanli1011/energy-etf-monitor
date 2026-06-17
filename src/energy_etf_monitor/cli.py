from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Annotated

import typer

from energy_etf_monitor.commodities import COMMODITIES, CommodityConfig, commodity_config
from energy_etf_monitor.config import Settings
from energy_etf_monitor.dashboard.static_report import write_static_site
from energy_etf_monitor.etfs import (
    ETF_FUNDS,
    default_official_holding_tickers,
    default_yahoo_metric_tickers,
    yahoo_metric_source_ticker,
)
from energy_etf_monitor.features.export import export_daily_features_to_parquet
from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.cftc import CftcCotConnector
from energy_etf_monitor.ingestion.cme import CmeSettlementCurveProvider
from energy_etf_monitor.ingestion.eia import EiaSeriesConnector
from energy_etf_monitor.ingestion.fred import FredSeriesConnector
from energy_etf_monitor.ingestion.gdelt import GdeltDocConnector
from energy_etf_monitor.ingestion.marketaux import MarketauxConnector
from energy_etf_monitor.ingestion.proshares import ProSharesHoldingsConnector
from energy_etf_monitor.ingestion.rss import DEFAULT_FEEDS, RssNewsConnector
from energy_etf_monitor.ingestion.runner import (
    BatchIngestionResult,
    PhaseZeroIngestionRunner,
)
from energy_etf_monitor.ingestion.uscf import UscfHoldingsConnector, UscfPcfConnector
from energy_etf_monitor.ingestion.yahoo import YahooEtfMetricsConnector, YahooFuturesConnector
from energy_etf_monitor.modeling.artifacts import save_model_artifact, train_logistic_artifact
from energy_etf_monitor.modeling.baselines import evaluate_walk_forward_baselines
from energy_etf_monitor.modeling.dataset import (
    build_pooled_examples,
    build_supervised_examples,
    load_feature_cache,
)
from energy_etf_monitor.modeling.loader import load_artifact
from energy_etf_monitor.modeling.monitoring import (
    build_model_health_report,
    export_model_health_report,
)
from energy_etf_monitor.modeling.predict import predict_two_head
from energy_etf_monitor.modeling.reports import export_baseline_evaluation_report
from energy_etf_monitor.news.alerts import alert_worthy
from energy_etf_monitor.news.classify import RuleBasedClassifier, is_relevant
from energy_etf_monitor.news.dedup import deduplicate_articles
from energy_etf_monitor.news.notify import post_news_alerts
from energy_etf_monitor.storage.db import create_db_and_tables
from energy_etf_monitor.storage.repository import IngestionRepository, LoadResult

app = typer.Typer(help="Energy ETF Monitor development CLI.")


@app.command()
def init_db() -> None:
    """Create database tables in the configured database."""

    create_db_and_tables(Settings())
    typer.echo("Database tables are ready.")


@app.command()
def render_report(
    output_dir: str = typer.Option(
        "site", "--output-dir", help="Directory for the generated static HTML site."
    ),
) -> None:
    """Render a self-contained static HTML dashboard (one page per commodity) — no server, no JS."""

    paths = write_static_site(Path(output_dir), settings=Settings(), as_of=datetime.now(UTC))
    typer.echo(f"Wrote {len(paths)} static pages into {output_dir}")


@app.command()
def ingest_phase0(
    load: bool = typer.Option(False, "--load"),
    trade_date: str | None = None,
    cot_limit: int = 5000,
    commodity: Annotated[list[str] | None, typer.Option("--commodity")] = None,
) -> None:
    """Run the Phase 0 ingestion batch for one or more commodities (default: all)."""

    curve_date = date.fromisoformat(trade_date) if trade_date else date.today()
    result = PhaseZeroIngestionRunner(
        settings=Settings(),
        commodities=_resolve_commodities(commodity),
    ).run(
        load=load,
        trade_date=curve_date,
        cot_limit=cot_limit,
    )
    _echo_batch_result(result)


def _resolve_commodities(names: list[str] | None) -> list[CommodityConfig]:
    if not names:
        return list(COMMODITIES.values())
    return [commodity_config(name) for name in names]


@app.command()
def fetch_uso_pcf(
    url: str | None = typer.Option(None, "--url"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch and parse the latest USO holdings.

    Without ``--url`` this uses the official USCF holdings/dailyprice API that powers the public
    holdings page. ``--url`` remains available for replaying an explicit legacy PCF CSV.
    """

    settings = Settings()
    if url:
        snapshot = UscfPcfConnector(
            fund_ticker="USO",
            pcf_url=url,
            raw_root_dir=settings.raw_data_dir,
        ).fetch_latest()
        typer.echo(f"Fetched USO PCF with {len(snapshot.holdings)} holdings.")
    else:
        snapshot = UscfHoldingsConnector(
            raw_root_dir=settings.raw_data_dir,
        ).fetch_latest(fund_ticker="USO")
        typer.echo(f"Fetched USO official holdings with {len(snapshot.holdings)} holdings.")
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            metric_result = repository.upsert_fund_daily_metrics([snapshot.metric])
            holding_result = repository.upsert_fund_holdings(snapshot.holdings)
            _echo_load_result(
                LoadResult(
                    inserted=metric_result.inserted + holding_result.inserted,
                    updated=metric_result.updated + holding_result.updated,
                    quarantined=metric_result.quarantined + holding_result.quarantined,
                )
            )


@app.command()
def ingest_etf_holdings(
    fund: Annotated[list[str] | None, typer.Option("--fund")] = None,
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch official ETF daily NAV/share/holdings snapshots and optionally load them."""

    settings = Settings()
    tickers = (
        [ticker.upper() for ticker in fund]
        if fund
        else list(default_official_holding_tickers())
    )
    snapshots = _fetch_official_etf_snapshots(settings=settings, tickers=tickers)
    metrics = [snapshot.metric for snapshot in snapshots]
    holdings = [holding for snapshot in snapshots for holding in snapshot.holdings]
    typer.echo(
        f"Fetched {len(snapshots)} official ETF snapshots "
        f"({len(metrics)} metrics, {len(holdings)} holdings; requested {', '.join(tickers)})."
    )
    if load and snapshots:
        with IngestionRepository.from_settings(settings) as repository:
            metric_result = repository.upsert_fund_daily_metrics(metrics)
            holding_result = repository.upsert_fund_holdings(holdings)
            _echo_load_result(
                LoadResult(
                    inserted=metric_result.inserted + holding_result.inserted,
                    updated=metric_result.updated + holding_result.updated,
                    quarantined=metric_result.quarantined + holding_result.quarantined,
                )
            )


@app.command()
def derive_uso_crowding(report_date: str = typer.Option(..., "--report-date")) -> None:
    """Derive and load the USO AUM/OI crowding metric for one report date."""

    metric_date = date.fromisoformat(report_date)
    with IngestionRepository.from_settings(Settings()) as repository:
        metric = repository.derive_fund_crowding_metric(
            fund_ticker="USO",
            commodity="WTI",
            product_code="CL",
            report_date=metric_date,
        )
        result = repository.upsert_fund_crowding_metrics([metric])
    typer.echo(f"Derived USO WTI crowding metric for {metric_date}.")
    _echo_load_result(result)


@app.command()
def build_wti_features(as_of: str = typer.Option(..., "--as-of")) -> None:
    """Build and load one point-in-time WTI feature row."""

    as_of_datetime = datetime.fromisoformat(as_of)
    with IngestionRepository.from_settings(Settings()) as repository:
        feature_row = repository.derive_wti_feature_row(as_of=as_of_datetime)
        result = repository.upsert_daily_feature_rows([feature_row])
    typer.echo(f"Built WTI feature row for {feature_row.report_date}.")
    _echo_load_result(result)


@app.command()
def build_wti_feature_range(
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    as_of_time: str = typer.Option("18:00:00+00:00", "--as-of-time"),
) -> None:
    """Build and load point-in-time WTI feature rows for a date range."""

    with IngestionRepository.from_settings(Settings()) as repository:
        rows = repository.derive_wti_feature_rows(
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            as_of_time=time.fromisoformat(as_of_time),
        )
        result = repository.upsert_daily_feature_rows(rows)
    typer.echo(f"Built {len(rows)} WTI feature rows.")
    _echo_load_result(result)


@app.command()
def build_features(
    commodity: str = typer.Option("WTI", "--commodity", help="Commodity to build."),
    as_of: str = typer.Option(..., "--as-of"),
) -> None:
    """Build and load one point-in-time feature row for any registered commodity."""

    config = commodity_config(commodity)
    as_of_datetime = datetime.fromisoformat(as_of)
    with IngestionRepository.from_settings(Settings()) as repository:
        feature_row = repository.derive_feature_row(config=config, as_of=as_of_datetime)
        result = repository.upsert_daily_feature_rows([feature_row])
    typer.echo(f"Built {config.name} feature row for {feature_row.report_date}.")
    _echo_load_result(result)


@app.command()
def build_feature_range(
    commodity: str = typer.Option("WTI", "--commodity", help="Commodity to build, or ALL."),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    as_of_time: str = typer.Option("18:00:00+00:00", "--as-of-time"),
) -> None:
    """Build and load point-in-time feature rows for a commodity over a date range."""

    config = commodity_config(commodity)
    with IngestionRepository.from_settings(Settings()) as repository:
        rows = repository.derive_feature_rows(
            config=config,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            as_of_time=time.fromisoformat(as_of_time),
        )
        result = repository.upsert_daily_feature_rows(rows)
    typer.echo(f"Built {len(rows)} {config.name} feature rows.")
    _echo_load_result(result)


@app.command()
def export_feature_cache(
    commodity: str = typer.Option("WTI", "--commodity"),
    output_path: str | None = typer.Option(None, "--output-path"),
    start_date: str | None = typer.Option(None, "--start-date"),
    end_date: str | None = typer.Option(None, "--end-date"),
) -> None:
    """Export a commodity's persisted feature rows to a Parquet cache for modeling."""

    settings = Settings()
    config = commodity_config(commodity)
    destination = (
        Path(output_path)
        if output_path
        else settings.processed_data_dir / f"{config.name.lower()}_daily_features.parquet"
    )
    with IngestionRepository.from_settings(settings) as repository:
        rows = repository.list_daily_feature_rows(
            commodity=config.name,
            start_date=date.fromisoformat(start_date) if start_date else None,
            end_date=date.fromisoformat(end_date) if end_date else None,
        )
    exported_path = export_daily_features_to_parquet(rows, destination)
    typer.echo(f"Exported {len(rows)} {config.name} feature rows to {exported_path}.")


@app.command()
def export_wti_feature_cache(
    output_path: str | None = typer.Option(None, "--output-path"),
    start_date: str | None = typer.Option(None, "--start-date"),
    end_date: str | None = typer.Option(None, "--end-date"),
) -> None:
    """Export persisted WTI feature rows to the processed Parquet cache."""

    settings = Settings()
    destination = Path(output_path) if output_path else settings.processed_data_dir
    with IngestionRepository.from_settings(settings) as repository:
        rows = repository.list_daily_feature_rows(
            commodity="WTI",
            start_date=date.fromisoformat(start_date) if start_date else None,
            end_date=date.fromisoformat(end_date) if end_date else None,
        )
    exported_path = export_daily_features_to_parquet(rows, destination)
    typer.echo(f"Exported {len(rows)} WTI feature rows to {exported_path}.")


@app.command()
def backfill_wti_feature_cache(
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    as_of_time: str = typer.Option("18:00:00+00:00", "--as-of-time"),
    output_path: str | None = typer.Option(None, "--output-path"),
) -> None:
    """Build, load, and export WTI feature rows for a date range."""

    settings = Settings()
    feature_start_date = date.fromisoformat(start_date)
    feature_end_date = date.fromisoformat(end_date)
    destination = Path(output_path) if output_path else settings.processed_data_dir
    with IngestionRepository.from_settings(settings) as repository:
        built_rows = repository.derive_wti_feature_rows(
            start_date=feature_start_date,
            end_date=feature_end_date,
            as_of_time=time.fromisoformat(as_of_time),
        )
        load_result = repository.upsert_daily_feature_rows(built_rows)
        export_rows = repository.list_daily_feature_rows(
            commodity="WTI",
            start_date=feature_start_date,
            end_date=feature_end_date,
        )
    exported_path = export_daily_features_to_parquet(export_rows, destination)
    typer.echo(f"Built {len(built_rows)} WTI feature rows.")
    _echo_load_result(load_result)
    typer.echo(f"Exported {len(export_rows)} WTI feature rows to {exported_path}.")


@app.command()
def evaluate_wti_baselines(
    feature_cache: str = typer.Option(..., "--feature-cache"),
    horizon_days: int = typer.Option(5, "--horizon-days"),
    min_train_size: int = typer.Option(252, "--min-train-size"),
    target_name: str = typer.Option("price_direction", "--target-name"),
    report_dir: str | None = typer.Option(None, "--report-dir"),
) -> None:
    """Evaluate WTI naive and logistic baselines with expanding walk-forward windows."""

    rows = load_feature_cache(Path(feature_cache))
    examples = build_supervised_examples(rows, horizon_days=horizon_days)
    report = evaluate_walk_forward_baselines(
        examples,
        target_name=target_name,
        min_train_size=min_train_size,
    )
    typer.echo(
        f"Evaluated {len(report.rows)} walk-forward WTI {report.target_name} predictions."
    )
    if report.metrics:
        typer.echo(_format_metrics(report.metrics))
    if report_dir:
        exported = export_baseline_evaluation_report(report, Path(report_dir))
        typer.echo(
            "Exported baseline predictions to "
            f"{exported.predictions_path} and metrics to {exported.metrics_path}."
        )


@app.command()
def train_wti_logistic_artifact(
    feature_cache: str = typer.Option(..., "--feature-cache"),
    horizon_days: int = typer.Option(5, "--horizon-days"),
    target_name: str = typer.Option("price_direction", "--target-name"),
    output_path: str = typer.Option(..., "--output-path"),
) -> None:
    """Train and save the current WTI logistic baseline model artifact."""

    rows = load_feature_cache(Path(feature_cache))
    examples = build_supervised_examples(rows, horizon_days=horizon_days)
    artifact = train_logistic_artifact(
        examples,
        target_name=target_name,
        horizon_days=horizon_days,
    )
    saved_path = save_model_artifact(artifact, Path(output_path))
    typer.echo(
        f"Trained {artifact.model_type} {artifact.target_name} model on "
        f"{artifact.training_count} examples through {artifact.trained_through}."
    )
    typer.echo(f"Saved model artifact to {saved_path}.")


@app.command()
def train_pooled_artifact(
    feature_cache: Annotated[list[str], typer.Option("--feature-cache")],
    output_path: str = typer.Option(..., "--output-path"),
    horizon_days: int = typer.Option(5, "--horizon-days"),
    target_name: str = typer.Option("price_direction", "--target-name"),
    model_type: str = typer.Option("logistic", "--model-type"),
) -> None:
    """Train one pooled cross-commodity model from per-commodity caches (NAME=path each)."""

    caches = _parse_cache_specs(feature_cache)
    examples = build_pooled_examples(caches, horizon_days=horizon_days)
    if model_type == "gbm":
        from energy_etf_monitor.modeling.gbm import save_gbm_artifact, train_gbm_artifact

        artifact = train_gbm_artifact(
            examples, target_name=target_name, horizon_days=horizon_days
        )
        saved_path = save_gbm_artifact(artifact, Path(output_path))
    else:
        artifact = train_logistic_artifact(
            examples, target_name=target_name, horizon_days=horizon_days
        )
        saved_path = save_model_artifact(artifact, Path(output_path))
    typer.echo(
        f"Trained pooled {artifact.model_type} {artifact.target_name} model on "
        f"{artifact.training_count} examples across {len(caches)} commodities."
    )
    typer.echo(f"Saved model artifact to {saved_path}.")


def _parse_cache_specs(specs: list[str]) -> dict[str, Path]:
    caches: dict[str, Path] = {}
    for spec in specs:
        name, separator, path = spec.partition("=")
        if not separator or not name or not path:
            raise typer.BadParameter(f"--feature-cache must be NAME=path, got: {spec}")
        caches[name.upper()] = Path(path)
    return caches


@app.command()
def train_wti_gbm_artifact(
    feature_cache: str = typer.Option(..., "--feature-cache"),
    horizon_days: int = typer.Option(5, "--horizon-days"),
    target_name: str = typer.Option("price_direction", "--target-name"),
    num_boost_round: int = typer.Option(100, "--num-boost-round"),
    output_path: str = typer.Option(..., "--output-path"),
) -> None:
    """Train and save a WTI LightGBM model artifact (requires the `gbm` extra)."""

    from energy_etf_monitor.modeling.gbm import save_gbm_artifact, train_gbm_artifact

    rows = load_feature_cache(Path(feature_cache))
    examples = build_supervised_examples(rows, horizon_days=horizon_days)
    artifact = train_gbm_artifact(
        examples,
        target_name=target_name,
        horizon_days=horizon_days,
        num_boost_round=num_boost_round,
    )
    saved_path = save_gbm_artifact(artifact, Path(output_path))
    typer.echo(
        f"Trained {artifact.model_type} {artifact.target_name} model on "
        f"{artifact.training_count} examples through {artifact.trained_through}."
    )
    typer.echo(f"Saved model artifact to {saved_path}.")


@app.command()
def predict_daily(
    price_artifact: str = typer.Option(..., "--price-artifact"),
    spread_artifact: str = typer.Option(..., "--spread-artifact"),
    commodity: str = typer.Option("WTI", "--commodity"),
    as_of: str | None = typer.Option(None, "--as-of"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Score the latest point-in-time feature row with both model heads."""

    predicted_at = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    price_model = load_artifact(Path(price_artifact))
    spread_model = load_artifact(Path(spread_artifact))
    with IngestionRepository.from_settings(Settings()) as repository:
        feature_row = repository.latest_daily_feature_row(
            commodity=commodity,
            as_of=predicted_at,
        )
        if feature_row is None:
            raise typer.BadParameter(
                f"No {commodity} feature row available as of {predicted_at.isoformat()}."
            )
        prediction = predict_two_head(
            feature_row=feature_row,
            price_artifact=price_model,
            spread_artifact=spread_model,
            predicted_at=predicted_at,
        )
        typer.echo(
            f"{prediction.commodity} {prediction.report_date} h{prediction.horizon_days}: "
            f"P(price up)={prediction.price_up_probability:.3f} "
            f"P(spread up)={prediction.spread_up_probability:.3f}"
        )
        if prediction.price_naive_probability is not None:
            typer.echo(
                "naive baseline: "
                f"price={prediction.price_naive_probability:.0f} "
                f"spread={prediction.spread_naive_probability:.0f}"
            )
        typer.echo(f"price drivers: {prediction.price_top_drivers}")
        typer.echo(f"spread drivers: {prediction.spread_top_drivers}")
        if load:
            _echo_load_result(repository.upsert_daily_predictions([prediction]))


@app.command()
def run_nightly(
    price_artifact: str | None = typer.Option(
        None,
        "--price-artifact",
        help="Deprecated; prediction is no longer part of the default monitoring run.",
    ),
    spread_artifact: str | None = typer.Option(
        None,
        "--spread-artifact",
        help="Deprecated; prediction is no longer part of the default monitoring run.",
    ),
    commodity: str = typer.Option("WTI", "--commodity"),
    trade_date: str | None = typer.Option(None, "--trade-date"),
    cot_limit: int = typer.Option(5000, "--cot-limit"),
) -> None:
    """Nightly monitoring pipeline: ingest source data -> refresh ETF data -> build factor rows."""

    _ = (price_artifact, spread_artifact)
    settings = Settings()
    curve_date = date.fromisoformat(trade_date) if trade_date else date.today()
    as_of = datetime.now(UTC)

    typer.echo("[1/5] Ingesting futures, inventory, COT, and macro sources...")
    ingest = PhaseZeroIngestionRunner(
        settings=settings,
        commodities=list(COMMODITIES.values()),
    ).run(load=True, trade_date=curve_date, cot_limit=cot_limit)
    _echo_batch_result(ingest)

    typer.echo("[2/5] Ingesting official ETF holdings...")
    _ingest_official_etf_holdings(settings)

    typer.echo("[3/5] Ingesting fallback ETF metric context...")
    _ingest_yahoo_etf_metric_context(settings)

    typer.echo("[4/5] Ingesting news...")
    try:
        news = _collect_news(settings, timespan="1d", max_records=75)
        with IngestionRepository.from_settings(settings) as repository:
            repository.upsert_news_articles(news)
        alerts = alert_worthy(news)
        typer.echo(f"Loaded {len(news)} news events ({len(alerts)} high-impact).")
        _post_alerts(settings, alerts)
    except Exception as exc:  # news is auxiliary — never fail the run on it
        typer.echo(f"News ingestion skipped: {exc}")

    with IngestionRepository.from_settings(settings) as repository:
        target_configs = (
            list(COMMODITIES.values())
            if commodity.upper() == "ALL"
            else [commodity_config(commodity)]
        )
        typer.echo("[5/5] Building factor row(s)...")
        feature_rows = []
        for config in target_configs:
            try:
                feature_row = repository.derive_feature_row(config=config, as_of=as_of)
            except ValueError as exc:
                typer.echo(f"  ! skipped {config.name} feature row - {exc}")
                continue
            feature_rows.append(feature_row)
            typer.echo(f"Feature row for {config.name} {feature_row.report_date} ready.")
        if feature_rows:
            repository.upsert_daily_feature_rows(feature_rows)

    typer.echo("Nightly monitoring run complete.")


def _ingest_official_etf_holdings(settings: Settings) -> None:
    tickers = list(default_official_holding_tickers())
    snapshots = _fetch_official_etf_snapshots(settings=settings, tickers=tickers)
    if not snapshots:
        typer.echo("No official ETF holdings loaded.")
        return
    metrics = [snapshot.metric for snapshot in snapshots]
    holdings = [holding for snapshot in snapshots for holding in snapshot.holdings]
    with IngestionRepository.from_settings(settings) as repository:
        metric_result = repository.upsert_fund_daily_metrics(metrics)
        holding_result = repository.upsert_fund_holdings(holdings)
    _echo_load_result(
        LoadResult(
            inserted=metric_result.inserted + holding_result.inserted,
            updated=metric_result.updated + holding_result.updated,
            quarantined=metric_result.quarantined + holding_result.quarantined,
        )
    )


def _fetch_official_etf_snapshots(settings: Settings, tickers: list[str]):
    connectors = {
        "USCF": UscfHoldingsConnector(raw_root_dir=settings.raw_data_dir),
        "PROSHARES": ProSharesHoldingsConnector(raw_root_dir=settings.raw_data_dir),
    }
    snapshots = []
    for ticker in tickers:
        fund_config = ETF_FUNDS.get(ticker)
        if fund_config is None:
            typer.echo(f"  ! skipped {ticker} - ETF is not in the local registry")
            continue
        connector = connectors.get(fund_config.issuer.upper())
        if connector is None:
            typer.echo(f"  ! skipped {ticker} - no official connector for {fund_config.issuer}")
            continue
        try:
            snapshots.append(connector.fetch_latest(fund_ticker=ticker))
        except Exception as exc:  # one issuer endpoint failure should not drop the whole batch
            typer.echo(f"  ! skipped {ticker} - {exc}")
    return snapshots


def _ingest_yahoo_etf_metric_context(settings: Settings) -> None:
    tickers = list(default_yahoo_metric_tickers())
    if not tickers:
        typer.echo("No fallback ETF metric tickers configured.")
        return
    connector = YahooEtfMetricsConnector(raw_store=RawPayloadStore(settings.raw_data_dir))
    metrics = []
    for ticker in tickers:
        source_ticker = yahoo_metric_source_ticker(ticker)
        try:
            metrics.append(
                connector.fetch_metric(fund_ticker=ticker, yahoo_symbol=source_ticker)
            )
        except Exception as exc:  # crumb/rate-limit failures should not sink the whole run
            typer.echo(f"  ! skipped {ticker} ({source_ticker}) - {exc}")
    if not metrics:
        typer.echo("No fallback ETF metrics loaded.")
        return
    with IngestionRepository.from_settings(settings) as repository:
        _echo_load_result(repository.upsert_fund_daily_metrics(metrics))


def _both_artifacts_exist(price_artifact: str | None, spread_artifact: str | None) -> bool:
    return (
        price_artifact is not None
        and spread_artifact is not None
        and Path(price_artifact).exists()
        and Path(spread_artifact).exists()
    )


@app.command()
def retrain(
    horizon_days: int = typer.Option(5, "--horizon-days"),
    commodity: Annotated[list[str] | None, typer.Option("--commodity")] = None,
    models_dir: str = typer.Option("models", "--models-dir"),
    pooled: bool = typer.Option(True, "--pooled/--no-pooled"),
) -> None:
    """Rebuild feature caches from the DB and retrain per-commodity (and pooled) logistic heads."""

    settings = Settings()
    configs = _resolve_commodities(commodity)
    models_path = Path(models_dir)
    targets = ("price_direction", "spread_direction")

    cache_paths: dict[str, Path] = {}
    with IngestionRepository.from_settings(settings) as repository:
        for config in configs:
            rows = repository.list_daily_feature_rows(commodity=config.name)
            cache = export_daily_features_to_parquet(
                rows,
                settings.processed_data_dir / f"{config.name.lower()}_daily_features.parquet",
            )
            cache_paths[config.name] = cache
            typer.echo(f"Exported {len(rows)} {config.name} feature rows.")

    trained = 0
    for config in configs:
        examples = build_supervised_examples(
            load_feature_cache(cache_paths[config.name]), horizon_days=horizon_days
        )
        if not examples:
            typer.echo(f"Skipping {config.name}: no training examples yet.")
            continue
        for target in targets:
            artifact = train_logistic_artifact(
                examples, target_name=target, horizon_days=horizon_days
            )
            save_model_artifact(
                artifact,
                models_path / f"{config.name.lower()}_{_target_slug(target)}_logistic.json",
            )
            trained += 1

    if pooled and cache_paths:
        pooled_examples = build_pooled_examples(cache_paths, horizon_days=horizon_days)
        if pooled_examples:
            for target in targets:
                artifact = train_logistic_artifact(
                    pooled_examples, target_name=target, horizon_days=horizon_days
                )
                save_model_artifact(
                    artifact, models_path / f"pooled_{_target_slug(target)}_logistic.json"
                )
                trained += 1

    typer.echo(f"Retrained {trained} artifacts into {models_path}.")


def _target_slug(target_name: str) -> str:
    return "price" if target_name == "price_direction" else "spread"


@app.command()
def model_health(
    commodity: str = typer.Option("WTI", "--commodity"),
    as_of: str | None = typer.Option(None, "--as-of"),
    rolling_window: int = typer.Option(20, "--rolling-window"),
    report_dir: str | None = typer.Option(None, "--report-dir"),
) -> None:
    """Score persisted predictions against realized outcomes (decay monitor)."""

    evaluated_at = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    with IngestionRepository.from_settings(Settings()) as repository:
        predictions = repository.list_daily_predictions(commodity=commodity)
        feature_rows = repository.list_daily_feature_rows(commodity=commodity)
    report = build_model_health_report(
        predictions,
        feature_rows,
        as_of=evaluated_at,
        commodity=commodity,
        rolling_window=rolling_window,
    )
    typer.echo(
        f"Scored {len(report.outcomes)} {commodity} predictions with realized outcomes."
    )
    if report.metrics:
        typer.echo(_format_metrics(report.metrics))
    if report_dir:
        exported = export_model_health_report(report, Path(report_dir))
        typer.echo(
            "Exported model-health outcomes to "
            f"{exported.outcomes_path} and metrics to {exported.metrics_path}."
        )


@app.command()
def ingest_news(
    timespan: str = typer.Option("1d", "--timespan"),
    max_records: int = typer.Option(75, "--max-records"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch energy news (GDELT), filter, deduplicate, classify impact, and optionally load."""

    settings = Settings()
    classified = _collect_news(settings, timespan=timespan, max_records=max_records)
    alerts = alert_worthy(classified)
    typer.echo(f"Kept {len(classified)} classified events; {len(alerts)} high-impact alerts.")
    for article in alerts:
        typer.echo(
            f"  ALERT [{round(article.importance_score)}/{article.impact_direction}] "
            f"{article.commodity}: {article.title}"
        )
    _post_alerts(settings, alerts)
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_news_articles(classified))


def _collect_news(settings: Settings, *, timespan: str, max_records: int):
    raw_store = RawPayloadStore(settings.raw_data_dir)
    raw: list = []
    raw += _safe_fetch(
        lambda: GdeltDocConnector(raw_store=raw_store).fetch_articles(
            timespan=timespan, max_records=max_records
        )
    )
    if settings.marketaux_api_key:
        raw += _safe_fetch(
            lambda: MarketauxConnector(
                api_key=settings.marketaux_api_key, raw_store=raw_store
            ).fetch_articles()
        )
    for source, feed_url in DEFAULT_FEEDS:
        raw += _safe_fetch(
            lambda feed_url=feed_url, source=source: RssNewsConnector(
                feed_url=feed_url, source=source, raw_store=raw_store
            ).fetch_articles()
        )
    relevant = deduplicate_articles([article for article in raw if is_relevant(article)])
    classifier = _news_classifier(settings)
    return [classifier.classify(article) for article in relevant]


def _safe_fetch(fetcher):
    # Multi-source news ingestion is resilient: one bad source must not drop the others.
    try:
        return list(fetcher())
    except Exception as exc:
        typer.echo(f"  news source error skipped: {exc}")
        return []


def _news_classifier(settings: Settings):
    if settings.news_classifier == "llm" and settings.anthropic_api_key:
        from energy_etf_monitor.news.llm_classify import LlmNewsClassifier

        return LlmNewsClassifier(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
        )
    return RuleBasedClassifier()


def _post_alerts(settings: Settings, alerts: list) -> None:
    if not alerts or not settings.alert_webhook_url:
        return
    try:
        sent = post_news_alerts(
            alerts,
            webhook_url=settings.alert_webhook_url,
            kind=settings.alert_webhook_kind,
        )
        typer.echo(f"Posted {sent} alert(s) to {settings.alert_webhook_kind} webhook.")
    except Exception as exc:  # alerting is best-effort
        typer.echo(f"Alert webhook post skipped: {exc}")


@app.command()
def fetch_eia(series_id: str, load: bool = typer.Option(False, "--load")) -> None:
    """Fetch one EIA series and persist its raw payload."""

    settings = Settings()
    rows = EiaSeriesConnector(
        api_key=settings.eia_api_key,
        raw_store=RawPayloadStore(settings.raw_data_dir),
    ).fetch_series(series_id)
    typer.echo(f"Fetched {len(rows)} EIA rows for {series_id}.")
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_time_series(rows))


@app.command()
def fetch_fred(series_id: str, load: bool = typer.Option(False, "--load")) -> None:
    """Fetch one FRED series and persist its raw payload."""

    settings = Settings()
    rows = FredSeriesConnector(
        api_key=settings.fred_api_key,
        raw_store=RawPayloadStore(settings.raw_data_dir),
    ).fetch_observations(series_id)
    typer.echo(f"Fetched {len(rows)} FRED rows for {series_id}.")
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_time_series(rows))


@app.command()
def fetch_wti_cot(limit: int = 5000, load: bool = typer.Option(False, "--load")) -> None:
    """Fetch WTI CFTC disaggregated futures-only COT rows."""

    settings = Settings()
    rows = CftcCotConnector(
        app_token=settings.cftc_app_token,
        raw_store=RawPayloadStore(settings.raw_data_dir),
    ).fetch_wti_positions(limit=limit)
    typer.echo(f"Fetched {len(rows)} WTI COT rows.")
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_cot_positions(rows))


@app.command()
def fetch_cme_curve(
    product_code: str = "CL",
    trade_date: str | None = None,
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch a CME settlement curve through the swappable curve-provider interface."""

    settings = Settings()
    curve_date = date.fromisoformat(trade_date) if trade_date else date.today()
    rows = CmeSettlementCurveProvider(
        raw_store=RawPayloadStore(settings.raw_data_dir),
    ).fetch_curve(product_code=product_code, trade_date=curve_date)
    typer.echo(f"Fetched {len(rows)} CME {product_code.upper()} settlements for {curve_date}.")
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_futures_settlements(rows))


@app.command()
def ingest_yahoo_history(
    commodity: str = typer.Option("WTI", "--commodity"),
    range_: str = typer.Option("10y", "--range"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch the continuous front-month futures price history from Yahoo (backfill price line)."""

    settings = Settings()
    config = commodity_config(commodity)
    rows = YahooFuturesConnector(
        raw_store=RawPayloadStore(settings.raw_data_dir),
    ).fetch_front_history(product_code=config.product_code, range_=range_)
    typer.echo(
        f"Fetched {len(rows)} {config.name} front-month settlements from Yahoo "
        f"({range_} of {config.product_code})."
    )
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_futures_settlements(rows))


@app.command()
def ingest_yahoo_curve_history(
    commodity: str = typer.Option("WTI", "--commodity"),
    start_date: str = typer.Option(..., "--start-date"),
    end_date: str = typer.Option(..., "--end-date"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch historical monthly futures contracts from Yahoo for a real backfill term structure."""

    settings = Settings()
    config = commodity_config(commodity)
    rows = YahooFuturesConnector(
        raw_store=RawPayloadStore(settings.raw_data_dir),
    ).fetch_curve_history(
        product_code=config.product_code,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
    )
    typer.echo(
        f"Fetched {len(rows)} {config.name} historical contract settlements from Yahoo."
    )
    if load:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_futures_settlements(rows))


@app.command()
def ingest_etf_metrics(
    fund: Annotated[list[str] | None, typer.Option("--fund")] = None,
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch Yahoo ETF AUM/price context for explicit or non-official fallback funds."""

    settings = Settings()
    tickers = [f.upper() for f in fund] if fund else list(default_yahoo_metric_tickers())
    connector = YahooEtfMetricsConnector(raw_store=RawPayloadStore(settings.raw_data_dir))
    metrics = []
    for ticker in tickers:
        source_ticker = yahoo_metric_source_ticker(ticker)
        try:
            metrics.append(
                connector.fetch_metric(fund_ticker=ticker, yahoo_symbol=source_ticker)
            )
        except Exception as exc:  # one fund failing (crumb/rate-limit) must not abort the rest
            typer.echo(f"  ! skipped {ticker} ({source_ticker}) - {exc}")
    typer.echo(f"Fetched {len(metrics)} ETF metric snapshots ({', '.join(tickers)}).")
    if load and metrics:
        with IngestionRepository.from_settings(settings) as repository:
            _echo_load_result(repository.upsert_fund_daily_metrics(metrics))


def _echo_load_result(result: LoadResult) -> None:
    typer.echo(
        "Loaded "
        f"{result.total} rows "
        f"({result.inserted} inserted, {result.updated} updated, "
        f"{result.quarantined} quarantined)."
    )


def _echo_batch_result(result: BatchIngestionResult) -> None:
    typer.echo(f"Fetched {result.fetched_total} rows across {len(result.runs)} tasks.")
    if result.loaded_total:
        typer.echo(f"Loaded {result.loaded_total} rows ({result.quarantined_total} quarantined).")
    for run in result.failures:
        typer.echo(f"  ! skipped {run.source}:{run.name} — {run.error}")


def _format_metrics(metrics: dict[str, float]) -> str:
    return " ".join(f"{name}={value:.4f}" for name, value in sorted(metrics.items()))


if __name__ == "__main__":
    app()
