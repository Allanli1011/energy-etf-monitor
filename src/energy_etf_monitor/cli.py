from datetime import UTC, date, datetime, time
from pathlib import Path

import typer

from energy_etf_monitor.config import Settings
from energy_etf_monitor.features.export import export_daily_features_to_parquet
from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.cftc import CftcCotConnector
from energy_etf_monitor.ingestion.cme import CmeSettlementCurveProvider
from energy_etf_monitor.ingestion.eia import EiaSeriesConnector
from energy_etf_monitor.ingestion.fred import FredSeriesConnector
from energy_etf_monitor.ingestion.runner import (
    BatchIngestionResult,
    PhaseZeroIngestionRunner,
)
from energy_etf_monitor.ingestion.uscf import UscfPcfConnector
from energy_etf_monitor.modeling.artifacts import (
    load_model_artifact,
    save_model_artifact,
    train_logistic_artifact,
)
from energy_etf_monitor.modeling.baselines import evaluate_walk_forward_baselines
from energy_etf_monitor.modeling.dataset import build_supervised_examples, load_feature_cache
from energy_etf_monitor.modeling.predict import predict_two_head
from energy_etf_monitor.modeling.reports import export_baseline_evaluation_report
from energy_etf_monitor.storage.db import create_db_and_tables
from energy_etf_monitor.storage.repository import IngestionRepository, LoadResult

app = typer.Typer(help="Energy ETF Monitor development CLI.")


@app.command()
def init_db() -> None:
    """Create database tables in the configured Postgres database."""

    create_db_and_tables(Settings())
    typer.echo("Database tables are ready.")


@app.command()
def ingest_phase0(
    load: bool = typer.Option(False, "--load"),
    trade_date: str | None = None,
    cot_limit: int = 5000,
) -> None:
    """Run the Phase 0 WTI ingestion batch."""

    curve_date = date.fromisoformat(trade_date) if trade_date else date.today()
    result = PhaseZeroIngestionRunner(settings=Settings()).run(
        load=load,
        trade_date=curve_date,
        cot_limit=cot_limit,
    )
    _echo_batch_result(result)


@app.command()
def fetch_uso_pcf(
    url: str = typer.Option(..., "--url"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Fetch and parse the latest USO PCF file."""

    settings = Settings()
    snapshot = UscfPcfConnector(
        fund_ticker="USO",
        pcf_url=url,
        raw_root_dir=settings.raw_data_dir,
    ).fetch_latest()
    typer.echo(f"Fetched USO PCF with {len(snapshot.holdings)} holdings.")
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
def predict_daily(
    price_artifact: str = typer.Option(..., "--price-artifact"),
    spread_artifact: str = typer.Option(..., "--spread-artifact"),
    commodity: str = typer.Option("WTI", "--commodity"),
    as_of: str | None = typer.Option(None, "--as-of"),
    load: bool = typer.Option(False, "--load"),
) -> None:
    """Score the latest point-in-time feature row with both model heads."""

    predicted_at = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    price_model = load_model_artifact(Path(price_artifact))
    spread_model = load_model_artifact(Path(spread_artifact))
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


def _format_metrics(metrics: dict[str, float]) -> str:
    return " ".join(f"{name}={value:.4f}" for name, value in sorted(metrics.items()))


if __name__ == "__main__":
    app()
