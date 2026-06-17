from datetime import UTC, date, datetime, time
from pathlib import Path

from typer.testing import CliRunner

from energy_etf_monitor import cli
from energy_etf_monitor.ingestion.runner import SourceRunResult

runner = CliRunner()


def test_cli_help_renders() -> None:
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "Energy ETF Monitor" in result.output


def test_init_db_command_uses_configured_settings(monkeypatch) -> None:
    called = {}

    def fake_create_db_and_tables(settings) -> None:
        called["database_url"] = settings.database_url

    monkeypatch.setattr(cli, "create_db_and_tables", fake_create_db_and_tables)

    result = runner.invoke(cli.app, ["init-db"])

    assert result.exit_code == 0
    assert called["database_url"]
    assert "Database tables are ready." in result.output


def test_fetch_eia_command_reports_row_count(monkeypatch) -> None:
    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def fetch_series(self, series_id: str):
            assert series_id == "WCESTUS1"
            return [object(), object()]

    monkeypatch.setattr(cli, "EiaSeriesConnector", FakeConnector)

    result = runner.invoke(cli.app, ["fetch-eia", "WCESTUS1"])

    assert result.exit_code == 0
    assert "Fetched 2 EIA rows" in result.output


def test_fetch_eia_command_loads_rows_when_requested(monkeypatch) -> None:
    rows = [object(), object()]
    loaded = {}

    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def fetch_series(self, series_id: str):
            assert series_id == "WCESTUS1"
            return rows

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def upsert_time_series(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=2, updated=0, quarantined=0)

    monkeypatch.setattr(cli, "EiaSeriesConnector", FakeConnector)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(cli.app, ["fetch-eia", "WCESTUS1", "--load"])

    assert result.exit_code == 0
    assert loaded["records"] == rows
    assert "Loaded 2 rows" in result.output


def test_fetch_fred_command_reports_row_count(monkeypatch) -> None:
    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def fetch_observations(self, series_id: str):
            assert series_id == "DTWEXBGS"
            return [object()]

    monkeypatch.setattr(cli, "FredSeriesConnector", FakeConnector)

    result = runner.invoke(cli.app, ["fetch-fred", "DTWEXBGS"])

    assert result.exit_code == 0
    assert "Fetched 1 FRED rows" in result.output


def test_fetch_wti_cot_command_reports_row_count(monkeypatch) -> None:
    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def fetch_wti_positions(self, limit: int):
            assert limit == 50
            return [object(), object(), object()]

    monkeypatch.setattr(cli, "CftcCotConnector", FakeConnector)

    result = runner.invoke(cli.app, ["fetch-wti-cot", "--limit", "50"])

    assert result.exit_code == 0
    assert "Fetched 3 WTI COT rows" in result.output


def test_fetch_cme_curve_command_reports_row_count(monkeypatch) -> None:
    class FakeProvider:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def fetch_curve(self, *, product_code: str, trade_date: date):
            assert product_code == "CL"
            assert trade_date.isoformat() == "2026-06-12"
            return [object()]

    monkeypatch.setattr(cli, "CmeSettlementCurveProvider", FakeProvider)

    result = runner.invoke(cli.app, ["fetch-cme-curve", "--trade-date", "2026-06-12"])

    assert result.exit_code == 0
    assert "Fetched 1 CME CL settlements" in result.output


def test_ingest_phase0_command_runs_batch_runner(monkeypatch) -> None:
    called = {}

    class FakeRunner:
        def __init__(self, settings, commodities=None) -> None:
            called["settings"] = settings
            called["commodities"] = commodities

        def run(self, *, load: bool, trade_date: date, cot_limit: int):
            called["args"] = (load, trade_date, cot_limit)
            return cli.BatchIngestionResult(
                    runs=[
                    SourceRunResult(source="eia", name="WCESTUS1", fetched=2),
                    SourceRunResult(
                        source="cftc",
                        name="WTI COT",
                        fetched=1,
                        load_result=cli.LoadResult(inserted=1),
                    ),
                ]
            )

    monkeypatch.setattr(cli, "PhaseZeroIngestionRunner", FakeRunner)

    result = runner.invoke(
        cli.app,
        ["ingest-phase0", "--load", "--trade-date", "2026-06-12", "--cot-limit", "25"],
    )

    assert result.exit_code == 0
    assert called["args"] == (True, date(2026, 6, 12), 25)
    # No --commodity given -> defaults to the full registry.
    assert {config.name for config in called["commodities"]} == {
        "WTI",
        "NATGAS",
        "RBOB",
        "BRENT",
    }
    assert "Fetched 3 rows across 2 tasks" in result.output
    assert "Loaded 1 rows" in result.output


def test_ingest_phase0_command_accepts_explicit_commodities(monkeypatch) -> None:
    called = {}

    class FakeRunner:
        def __init__(self, settings, commodities=None) -> None:
            called["commodities"] = commodities

        def run(self, *, load: bool, trade_date: date, cot_limit: int):
            return cli.BatchIngestionResult(runs=[])

    monkeypatch.setattr(cli, "PhaseZeroIngestionRunner", FakeRunner)

    result = CliRunner().invoke(
        cli.app,
        ["ingest-phase0", "--commodity", "NATGAS", "--commodity", "RBOB"],
    )

    assert result.exit_code == 0
    assert [config.name for config in called["commodities"]] == ["NATGAS", "RBOB"]


def test_build_features_command_builds_for_requested_commodity(monkeypatch) -> None:
    loaded = {}

    class FakeFeatureRow:
        report_date = date(2026, 6, 12)

    feature_row = FakeFeatureRow()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_feature_row(self, *, config, as_of):
            loaded["config_name"] = config.name
            loaded["as_of"] = as_of
            return feature_row

        def upsert_daily_feature_rows(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=1)

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = CliRunner().invoke(
        cli.app,
        ["build-features", "--commodity", "NATGAS", "--as-of", "2026-06-12T18:00:00+00:00"],
    )

    assert result.exit_code == 0
    assert loaded["config_name"] == "NATGAS"
    assert loaded["as_of"] == datetime(2026, 6, 12, 18, tzinfo=UTC)
    assert loaded["records"] == [feature_row]
    assert "Built NATGAS feature row for 2026-06-12" in result.output


def test_fetch_uso_pcf_command_loads_metric_and_holdings(monkeypatch) -> None:
    loaded = {}

    class FakeSnapshot:
        metric = object()
        holdings = [object(), object()]

    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            loaded["connector_kwargs"] = kwargs

        def fetch_latest(self):
            return FakeSnapshot()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def upsert_fund_daily_metrics(self, records):
            loaded["metrics"] = records
            return cli.LoadResult(inserted=1)

        def upsert_fund_holdings(self, records):
            loaded["holdings"] = records
            return cli.LoadResult(inserted=2)

    monkeypatch.setattr(cli, "UscfPcfConnector", FakeConnector)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(
        cli.app,
        ["fetch-uso-pcf", "--url", "https://example.test/uso.csv", "--load"],
    )

    assert result.exit_code == 0
    assert loaded["connector_kwargs"]["pcf_url"] == "https://example.test/uso.csv"
    assert loaded["metrics"] == [FakeSnapshot.metric]
    assert loaded["holdings"] == FakeSnapshot.holdings
    assert "Fetched USO PCF with 2 holdings" in result.output
    assert "Loaded 3 rows" in result.output


def test_fetch_uso_pcf_without_url_uses_official_holdings_api(monkeypatch) -> None:
    loaded = {}

    class FakeSnapshot:
        metric = object()
        holdings = [object(), object(), object()]

    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            loaded["connector_kwargs"] = kwargs

        def fetch_latest(self, *, fund_ticker: str):
            loaded["fund_ticker"] = fund_ticker
            return FakeSnapshot()

    monkeypatch.setattr(cli, "UscfHoldingsConnector", FakeConnector)

    result = runner.invoke(cli.app, ["fetch-uso-pcf"])

    assert result.exit_code == 0
    assert loaded["fund_ticker"] == "USO"
    assert "Fetched USO official holdings with 3 holdings" in result.output


def test_ingest_etf_holdings_defaults_to_official_registry_funds(monkeypatch) -> None:
    fetched: list[tuple[str, str]] = []
    loaded: dict[str, object] = {}

    class FakeSnapshot:
        def __init__(self, ticker: str) -> None:
            self.metric = f"metric-{ticker}"
            self.holdings = [f"holding-{ticker}-1", f"holding-{ticker}-2"]

    class FakeUscfConnector:
        def __init__(self, **kwargs) -> None:
            loaded["uscf_connector_kwargs"] = kwargs

        def fetch_latest(self, *, fund_ticker: str):
            fetched.append(("USCF", fund_ticker))
            return FakeSnapshot(fund_ticker)

    class FakeProSharesConnector:
        def __init__(self, **kwargs) -> None:
            loaded["proshares_connector_kwargs"] = kwargs

        def fetch_latest(self, *, fund_ticker: str):
            fetched.append(("ProShares", fund_ticker))
            return FakeSnapshot(fund_ticker)

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

        def upsert_fund_daily_metrics(self, metrics):
            loaded["metrics"] = metrics
            return cli.LoadResult(inserted=len(metrics))

        def upsert_fund_holdings(self, holdings):
            loaded["holdings"] = holdings
            return cli.LoadResult(inserted=len(holdings))

    monkeypatch.setattr(cli, "UscfHoldingsConnector", FakeUscfConnector)
    monkeypatch.setattr(cli, "ProSharesHoldingsConnector", FakeProSharesConnector)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(cli.app, ["ingest-etf-holdings", "--load"])

    assert result.exit_code == 0
    fetched_tickers = [ticker for _issuer, ticker in fetched]
    assert {"USO", "USL", "UNG", "UNL", "UGA"}.issubset(fetched_tickers)
    assert "DBO" not in fetched_tickers
    assert all(issuer != "Invesco" for issuer, _ticker in fetched)
    assert {ticker for issuer, ticker in fetched if issuer == "ProShares"} >= {
        "UCO",
        "SCO",
        "BOIL",
        "KOLD",
    }
    assert loaded["metrics"] == [f"metric-{ticker}" for ticker in fetched_tickers]
    assert loaded["holdings"] == [
        holding
        for ticker in fetched_tickers
        for holding in [f"holding-{ticker}-1", f"holding-{ticker}-2"]
    ]
    assert "official ETF snapshots" in result.output


def test_derive_uso_crowding_command_loads_metric(monkeypatch) -> None:
    loaded = {}

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_fund_crowding_metric(self, **kwargs):
            loaded["derive_kwargs"] = kwargs
            return object()

        def upsert_fund_crowding_metrics(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=1)

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(cli.app, ["derive-uso-crowding", "--report-date", "2026-06-12"])

    assert result.exit_code == 0
    assert loaded["derive_kwargs"] == {
        "fund_ticker": "USO",
        "commodity": "WTI",
        "product_code": "CL",
        "report_date": date(2026, 6, 12),
    }
    assert loaded["records"]
    assert "Derived USO WTI crowding metric" in result.output
    assert "Loaded 1 rows" in result.output


def test_build_wti_features_command_derives_and_loads_row(monkeypatch) -> None:
    loaded = {}

    class FakeFeatureRow:
        report_date = date(2026, 6, 12)

    feature_row = FakeFeatureRow()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_wti_feature_row(self, *, as_of: datetime):
            loaded["as_of"] = as_of
            return feature_row

        def upsert_daily_feature_rows(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=1)

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(
        cli.app,
        ["build-wti-features", "--as-of", "2026-06-12T18:00:00+00:00"],
    )

    assert result.exit_code == 0
    assert loaded["as_of"] == datetime(2026, 6, 12, 18, tzinfo=UTC)
    assert loaded["records"] == [feature_row]
    assert "Built WTI feature row for 2026-06-12" in result.output
    assert "Loaded 1 rows" in result.output


def test_build_wti_feature_range_command_derives_and_loads_rows(monkeypatch) -> None:
    loaded = {}
    feature_rows = [object(), object(), object()]

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_wti_feature_rows(self, **kwargs):
            loaded["derive_kwargs"] = kwargs
            return feature_rows

        def upsert_daily_feature_rows(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=3)

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(
        cli.app,
        [
            "build-wti-feature-range",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-03",
            "--as-of-time",
            "18:00:00+00:00",
        ],
    )

    assert result.exit_code == 0
    assert loaded["derive_kwargs"] == {
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 3),
        "as_of_time": time(18, tzinfo=UTC),
    }
    assert loaded["records"] == feature_rows
    assert "Built 3 WTI feature rows" in result.output
    assert "Loaded 3 rows" in result.output


def test_export_wti_feature_cache_command_exports_rows(monkeypatch, tmp_path: Path) -> None:
    loaded = {}
    feature_rows = [object(), object()]
    output_path = tmp_path / "features.parquet"

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def list_daily_feature_rows(self, **kwargs):
            loaded["list_kwargs"] = kwargs
            return feature_rows

    def fake_export(rows, destination):
        loaded["export_rows"] = rows
        loaded["destination"] = destination
        return output_path

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "export_daily_features_to_parquet", fake_export)

    result = runner.invoke(
        cli.app,
        [
            "export-wti-feature-cache",
            "--output-path",
            str(output_path),
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-12",
        ],
    )

    assert result.exit_code == 0
    assert loaded["list_kwargs"] == {
        "commodity": "WTI",
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 12),
    }
    assert loaded["export_rows"] == feature_rows
    assert loaded["destination"] == output_path
    assert f"Exported 2 WTI feature rows to {output_path}" in result.output


def test_backfill_wti_feature_cache_command_builds_loads_and_exports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    loaded = {}
    built_rows = [object(), object()]
    export_rows = [object()]
    output_path = tmp_path / "wti_daily_features.parquet"

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_wti_feature_rows(self, **kwargs):
            loaded["derive_kwargs"] = kwargs
            return built_rows

        def upsert_daily_feature_rows(self, rows):
            loaded["upsert_rows"] = rows
            return cli.LoadResult(inserted=1, updated=1, quarantined=0)

        def list_daily_feature_rows(self, **kwargs):
            loaded["list_kwargs"] = kwargs
            return export_rows

    def fake_export(rows, destination):
        loaded["export_rows"] = rows
        loaded["destination"] = destination
        return output_path

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "export_daily_features_to_parquet", fake_export)

    result = runner.invoke(
        cli.app,
        [
            "backfill-wti-feature-cache",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-02",
            "--as-of-time",
            "18:00:00+00:00",
            "--output-path",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert loaded["derive_kwargs"] == {
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 2),
        "as_of_time": time(18, tzinfo=UTC),
    }
    assert loaded["upsert_rows"] == built_rows
    assert loaded["list_kwargs"] == {
        "commodity": "WTI",
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 2),
    }
    assert loaded["export_rows"] == export_rows
    assert loaded["destination"] == output_path
    assert "Built 2 WTI feature rows" in result.output
    assert "Loaded 2 rows" in result.output
    assert f"Exported 1 WTI feature rows to {output_path}" in result.output


def test_evaluate_wti_baselines_command_reports_metrics(monkeypatch, tmp_path: Path) -> None:
    loaded = {}
    cache_path = tmp_path / "wti_daily_features.parquet"
    examples = [object(), object(), object()]

    class FakeReport:
        target_name = "price_direction"
        rows = [object(), object()]
        metrics = {
            "naive_accuracy": 0.5,
            "logistic_accuracy": 1.0,
            "naive_brier": 0.5,
            "logistic_brier": 0.25,
        }

    def fake_load_feature_cache(path):
        loaded["path"] = path
        return ["rows"]

    def fake_build_supervised_examples(rows, *, horizon_days):
        loaded["target_rows"] = rows
        loaded["horizon_days"] = horizon_days
        return examples

    def fake_evaluate(examples_arg, **kwargs):
        loaded["examples"] = examples_arg
        loaded["evaluate_kwargs"] = kwargs
        return FakeReport()

    monkeypatch.setattr(cli, "load_feature_cache", fake_load_feature_cache)
    monkeypatch.setattr(cli, "build_supervised_examples", fake_build_supervised_examples)
    monkeypatch.setattr(cli, "evaluate_walk_forward_baselines", fake_evaluate)

    result = runner.invoke(
        cli.app,
        [
            "evaluate-wti-baselines",
            "--feature-cache",
            str(cache_path),
            "--horizon-days",
            "5",
            "--min-train-size",
            "2",
            "--target-name",
            "price_direction",
        ],
    )

    assert result.exit_code == 0
    assert loaded["path"] == cache_path
    assert loaded["target_rows"] == ["rows"]
    assert loaded["horizon_days"] == 5
    assert loaded["examples"] == examples
    assert loaded["evaluate_kwargs"] == {
        "target_name": "price_direction",
        "min_train_size": 2,
    }
    assert "Evaluated 2 walk-forward WTI price_direction predictions" in result.output
    assert "logistic_accuracy=1.0000" in result.output


def test_evaluate_wti_baselines_command_exports_report_when_requested(
    monkeypatch,
    tmp_path: Path,
) -> None:
    loaded = {}
    cache_path = tmp_path / "wti_daily_features.parquet"
    report_dir = tmp_path / "reports"

    class FakeReport:
        target_name = "spread_direction"
        rows = [object()]
        metrics = {"naive_accuracy": 1.0}
        regime_metrics = {"other": {"naive_accuracy": 1.0}}

    class FakeExportedReport:
        predictions_path = report_dir / "baseline_predictions_spread_direction.csv"
        metrics_path = report_dir / "baseline_metrics_spread_direction.json"

    def fake_load_feature_cache(path):
        return ["rows"]

    def fake_build_supervised_examples(rows, *, horizon_days):
        return ["examples"]

    def fake_evaluate(examples_arg, **kwargs):
        return FakeReport()

    def fake_export(report, destination):
        loaded["report"] = report
        loaded["destination"] = destination
        return FakeExportedReport()

    monkeypatch.setattr(cli, "load_feature_cache", fake_load_feature_cache)
    monkeypatch.setattr(cli, "build_supervised_examples", fake_build_supervised_examples)
    monkeypatch.setattr(cli, "evaluate_walk_forward_baselines", fake_evaluate)
    monkeypatch.setattr(cli, "export_baseline_evaluation_report", fake_export)

    result = runner.invoke(
        cli.app,
        [
            "evaluate-wti-baselines",
            "--feature-cache",
            str(cache_path),
            "--horizon-days",
            "5",
            "--min-train-size",
            "2",
            "--target-name",
            "spread_direction",
            "--report-dir",
            str(report_dir),
        ],
    )

    assert result.exit_code == 0
    assert loaded["report"].target_name == "spread_direction"
    assert loaded["destination"] == report_dir
    assert "Exported baseline predictions to" in result.output
    assert str(FakeExportedReport.predictions_path) in result.output
    assert str(FakeExportedReport.metrics_path) in result.output


def test_train_wti_logistic_artifact_command_saves_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    loaded = {}
    cache_path = tmp_path / "wti_daily_features.parquet"
    output_path = tmp_path / "price_model.json"
    examples = [object(), object(), object()]

    class FakeArtifact:
        model_type = "logistic_regression"
        target_name = "price_direction"
        training_count = 3
        trained_through = date(2026, 6, 12)

    def fake_load_feature_cache(path):
        loaded["path"] = path
        return ["rows"]

    def fake_build_supervised_examples(rows, *, horizon_days):
        loaded["target_rows"] = rows
        loaded["horizon_days"] = horizon_days
        return examples

    def fake_train(examples_arg, **kwargs):
        loaded["examples"] = examples_arg
        loaded["train_kwargs"] = kwargs
        return FakeArtifact()

    def fake_save(artifact, path):
        loaded["artifact"] = artifact
        loaded["output_path"] = path
        return path

    monkeypatch.setattr(cli, "load_feature_cache", fake_load_feature_cache)
    monkeypatch.setattr(cli, "build_supervised_examples", fake_build_supervised_examples)
    monkeypatch.setattr(cli, "train_logistic_artifact", fake_train)
    monkeypatch.setattr(cli, "save_model_artifact", fake_save)

    result = runner.invoke(
        cli.app,
        [
            "train-wti-logistic-artifact",
            "--feature-cache",
            str(cache_path),
            "--horizon-days",
            "5",
            "--target-name",
            "price_direction",
            "--output-path",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert loaded["path"] == cache_path
    assert loaded["target_rows"] == ["rows"]
    assert loaded["horizon_days"] == 5
    assert loaded["examples"] == examples
    assert loaded["train_kwargs"] == {
        "target_name": "price_direction",
        "horizon_days": 5,
    }
    assert loaded["output_path"] == output_path
    assert "Trained logistic_regression price_direction model on 3 examples" in result.output
    assert str(output_path) in result.output


def test_train_pooled_artifact_command_parses_specs_and_trains(monkeypatch, tmp_path) -> None:
    loaded = {}
    output_path = tmp_path / "pooled.json"

    class FakeArtifact:
        model_type = "logistic_regression"
        target_name = "price_direction"
        training_count = 12
        trained_through = date(2026, 6, 12)

    def fake_build_pooled(caches, *, horizon_days, **kwargs):
        loaded["caches"] = caches
        loaded["horizon_days"] = horizon_days
        return ["examples"]

    def fake_train(examples, **kwargs):
        loaded["train_kwargs"] = kwargs
        return FakeArtifact()

    def fake_save(artifact, path):
        loaded["output_path"] = path
        return path

    monkeypatch.setattr(cli, "build_pooled_examples", fake_build_pooled)
    monkeypatch.setattr(cli, "train_logistic_artifact", fake_train)
    monkeypatch.setattr(cli, "save_model_artifact", fake_save)

    result = CliRunner().invoke(
        cli.app,
        [
            "train-pooled-artifact",
            "--feature-cache",
            "WTI=/tmp/wti.parquet",
            "--feature-cache",
            "NATGAS=/tmp/ng.parquet",
            "--output-path",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert {name for name in loaded["caches"]} == {"WTI", "NATGAS"}
    # Compare Path objects (not their string form) so the assertion is OS-independent:
    # Path("/tmp/wti.parquet") stringifies with backslashes on Windows.
    assert loaded["caches"]["WTI"] == Path("/tmp/wti.parquet")
    assert "across 2 commodities" in result.output


def test_predict_daily_command_scores_latest_feature_row_and_loads(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    loaded = {}
    price_path = tmp_path / "price_model.json"
    spread_path = tmp_path / "spread_model.json"

    class FakeFeatureRow:
        report_date = date(2026, 6, 12)

    feature_row = FakeFeatureRow()

    class FakePrediction:
        commodity = "WTI"
        report_date = date(2026, 6, 12)
        horizon_days = 5
        price_up_probability = 0.62
        spread_up_probability = 0.38
        price_naive_probability = 1.0
        spread_naive_probability = 0.0
        price_top_drivers = '[{"feature": "cl_carry_m1_m2", "contribution": 1.0}]'
        spread_top_drivers = "[]"

    prediction = FakePrediction()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def latest_daily_feature_row(self, *, commodity, as_of):
            loaded["commodity"] = commodity
            loaded["as_of"] = as_of
            return feature_row

        def upsert_daily_predictions(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=1)

    def fake_load_artifact(path):
        loaded.setdefault("artifact_paths", []).append(path)
        return path

    def fake_predict_two_head(*, feature_row, price_artifact, spread_artifact, predicted_at):
        loaded["predict_kwargs"] = {
            "feature_row": feature_row,
            "price_artifact": price_artifact,
            "spread_artifact": spread_artifact,
            "predicted_at": predicted_at,
        }
        return prediction

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "load_artifact", fake_load_artifact)
    monkeypatch.setattr(cli, "predict_two_head", fake_predict_two_head)

    result = runner.invoke(
        cli.app,
        [
            "predict-daily",
            "--price-artifact",
            str(price_path),
            "--spread-artifact",
            str(spread_path),
            "--as-of",
            "2026-06-12T18:00:00+00:00",
            "--load",
        ],
    )

    assert result.exit_code == 0
    assert loaded["commodity"] == "WTI"
    assert loaded["as_of"] == datetime(2026, 6, 12, 18, tzinfo=UTC)
    assert loaded["artifact_paths"] == [price_path, spread_path]
    assert loaded["predict_kwargs"]["feature_row"] is feature_row
    assert loaded["records"] == [prediction]
    assert "P(price up)=0.620" in result.output
    assert "P(spread up)=0.380" in result.output
    assert "Loaded 1 rows" in result.output


def test_predict_daily_command_errors_when_no_feature_row(monkeypatch, tmp_path) -> None:
    runner = CliRunner()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def latest_daily_feature_row(self, *, commodity, as_of):
            return None

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "load_artifact", lambda path: path)
    monkeypatch.setattr(cli, "predict_two_head", lambda **kwargs: None)

    result = runner.invoke(
        cli.app,
        [
            "predict-daily",
            "--price-artifact",
            str(tmp_path / "price.json"),
            "--spread-artifact",
            str(tmp_path / "spread.json"),
            "--as-of",
            "2026-06-12T18:00:00+00:00",
        ],
    )

    assert result.exit_code != 0
    assert "No WTI feature row available" in result.output


def test_run_nightly_command_chains_all_steps(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    loaded = {}
    price_path = tmp_path / "price.json"
    spread_path = tmp_path / "spread.json"
    price_path.write_text("{}")
    spread_path.write_text("{}")

    class FakeFeatureRow:
        report_date = date(2026, 6, 12)

    feature_row = FakeFeatureRow()

    class FakeIngest:
        def __init__(self, *, settings, commodities=None):
            loaded["ingest_settings"] = settings

        def run(self, *, load, trade_date, cot_limit):
            loaded["ingest_run"] = {"load": load, "trade_date": trade_date, "cot_limit": cot_limit}
            from energy_etf_monitor.ingestion.runner import BatchIngestionResult

            return BatchIngestionResult()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_feature_row(self, *, config, as_of):
            loaded["derive_as_of"] = as_of
            loaded["derive_config"] = config.name
            return feature_row

        def upsert_daily_feature_rows(self, records):
            loaded["feature_records"] = records
            return cli.LoadResult(inserted=1)

        def upsert_news_articles(self, records):
            loaded["news_records"] = records
            return cli.LoadResult(inserted=len(records))

    monkeypatch.setattr(cli, "PhaseZeroIngestionRunner", FakeIngest)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(
        cli, "_collect_news", lambda settings, *, timespan, max_records: []
    )
    monkeypatch.setattr(
        cli,
        "_ingest_official_etf_holdings",
        lambda settings: loaded.setdefault("official_etf", True),
    )
    monkeypatch.setattr(
        cli,
        "_ingest_wisdomtree_etf_metric_context",
        lambda settings: loaded.setdefault("wisdomtree_etf", True),
    )
    monkeypatch.setattr(
        cli,
        "_ingest_yahoo_etf_metric_context",
        lambda settings: loaded.setdefault("yahoo_etf", True),
    )

    result = runner.invoke(
        cli.app,
        [
            "run-nightly",
            "--price-artifact",
            str(price_path),
            "--spread-artifact",
            str(spread_path),
            "--trade-date",
            "2026-06-12",
        ],
    )

    assert result.exit_code == 0
    assert loaded["ingest_run"]["load"] is True
    assert loaded["ingest_run"]["trade_date"] == date(2026, 6, 12)
    assert loaded["official_etf"] is True
    assert loaded["wisdomtree_etf"] is True
    assert loaded["yahoo_etf"] is True
    assert loaded["feature_records"] == [feature_row]
    assert "Building factor row" in result.output
    assert "Nightly monitoring run complete." in result.output


def test_run_nightly_command_runs_without_prediction_artifacts(monkeypatch) -> None:
    runner = CliRunner()

    class FakeFeatureRow:
        report_date = date(2026, 6, 12)

    class FakeIngest:
        def __init__(self, *, settings, commodities=None):
            pass

        def run(self, *, load, trade_date, cot_limit):
            from energy_etf_monitor.ingestion.runner import BatchIngestionResult

            return BatchIngestionResult()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_feature_row(self, *, config, as_of):
            return FakeFeatureRow()

        def upsert_daily_feature_rows(self, records):
            return cli.LoadResult(inserted=1)

        def upsert_news_articles(self, records):
            return cli.LoadResult(inserted=len(records))

    monkeypatch.setattr(cli, "PhaseZeroIngestionRunner", FakeIngest)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(
        cli, "_collect_news", lambda settings, *, timespan, max_records: []
    )
    monkeypatch.setattr(
        cli,
        "_ingest_official_etf_holdings",
        lambda settings: None,
    )
    monkeypatch.setattr(
        cli,
        "_ingest_wisdomtree_etf_metric_context",
        lambda settings: None,
    )
    monkeypatch.setattr(
        cli,
        "_ingest_yahoo_etf_metric_context",
        lambda settings: None,
    )

    result = runner.invoke(cli.app, ["run-nightly"])

    assert result.exit_code == 0
    assert "Predicting" not in result.output
    assert "Model health" not in result.output
    assert "Nightly monitoring run complete." in result.output


def test_run_nightly_command_can_build_all_commodity_feature_rows(monkeypatch) -> None:
    runner = CliRunner()
    derived: list[str] = []
    loaded: dict[str, object] = {}

    class FakeFeatureRow:
        def __init__(self, commodity: str) -> None:
            self.commodity = commodity
            self.report_date = date(2026, 6, 12)

    class FakeIngest:
        def __init__(self, *, settings, commodities=None):
            pass

        def run(self, *, load, trade_date, cot_limit):
            from energy_etf_monitor.ingestion.runner import BatchIngestionResult

            return BatchIngestionResult()

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def derive_feature_row(self, *, config, as_of):
            derived.append(config.name)
            return FakeFeatureRow(config.name)

        def upsert_daily_feature_rows(self, records):
            loaded["feature_records"] = records
            return cli.LoadResult(inserted=len(records))

        def upsert_news_articles(self, records):
            return cli.LoadResult(inserted=len(records))

    monkeypatch.setattr(cli, "PhaseZeroIngestionRunner", FakeIngest)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "_collect_news", lambda settings, *, timespan, max_records: [])
    monkeypatch.setattr(cli, "_ingest_official_etf_holdings", lambda settings: None)
    monkeypatch.setattr(cli, "_ingest_wisdomtree_etf_metric_context", lambda settings: None)
    monkeypatch.setattr(cli, "_ingest_yahoo_etf_metric_context", lambda settings: None)

    result = runner.invoke(cli.app, ["run-nightly", "--commodity", "ALL"])

    assert result.exit_code == 0
    assert derived == ["WTI", "NATGAS", "RBOB", "BRENT"]
    assert [row.commodity for row in loaded["feature_records"]] == derived
    assert "Feature row for BRENT 2026-06-12 ready." in result.output


def test_ingest_news_command_reports_alerts_and_loads(monkeypatch) -> None:
    from energy_etf_monitor.records import NewsArticle

    runner = CliRunner()
    loaded = {}

    def _news(importance: float, direction: str, suffix: str) -> NewsArticle:
        published = datetime(2026, 6, 12, 9, tzinfo=UTC)
        return NewsArticle(
            source="gdelt",
            report_date=published.date(),
            knowledge_date=published,
            published_at=published,
            url=f"https://a.com/{suffix}",
            url_hash=f"hash-{suffix}",
            title=f"headline {suffix}",
            commodity="WTI",
            impact_direction=direction,
            importance_score=importance,
            confidence=0.6,
        )

    articles = [_news(85, "Bullish", "1"), _news(20, "Neutral", "2")]

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def upsert_news_articles(self, records):
            loaded["records"] = records
            return cli.LoadResult(inserted=len(records))

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(
        cli, "_collect_news", lambda settings, *, timespan, max_records: articles
    )

    result = runner.invoke(cli.app, ["ingest-news", "--load"])

    assert result.exit_code == 0
    assert "Kept 2 classified events; 1 high-impact alerts." in result.output
    assert loaded["records"] == articles


def test_retrain_command_trains_per_commodity_artifacts(monkeypatch, tmp_path) -> None:
    saved: list = []

    class FakeArtifact:
        model_type = "logistic_regression"
        target_name = "price_direction"
        training_count = 5
        trained_through = date(2026, 6, 12)

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def list_daily_feature_rows(self, *, commodity):
            return ["row"]

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "export_daily_features_to_parquet", lambda rows, dest: dest)
    monkeypatch.setattr(cli, "load_feature_cache", lambda path: ["cached"])
    monkeypatch.setattr(cli, "build_supervised_examples", lambda rows, *, horizon_days: ["ex"])
    monkeypatch.setattr(cli, "train_logistic_artifact", lambda examples, **kwargs: FakeArtifact())

    def _fake_save(artifact, path):
        saved.append(path)
        return path

    monkeypatch.setattr(cli, "save_model_artifact", _fake_save)

    result = CliRunner().invoke(
        cli.app,
        ["retrain", "--commodity", "WTI", "--no-pooled", "--models-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    names = sorted(p.name for p in saved)
    assert names == ["wti_price_logistic.json", "wti_spread_logistic.json"]
    assert "Retrained 2 artifacts" in result.output


def test_model_health_command_scores_and_reports(monkeypatch, tmp_path) -> None:
    runner = CliRunner()
    loaded = {}
    report_dir = tmp_path / "health"

    class FakeReport:
        outcomes = [object(), object()]
        metrics = {"price_model_accuracy": 0.75}

    class FakeExported:
        outcomes_path = report_dir / "model_health_outcomes_WTI.csv"
        metrics_path = report_dir / "model_health_metrics_WTI.json"

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def list_daily_predictions(self, *, commodity):
            loaded["pred_commodity"] = commodity
            return ["prediction"]

        def list_daily_feature_rows(self, *, commodity):
            loaded["feature_commodity"] = commodity
            return ["feature"]

    def fake_build(predictions, feature_rows, *, as_of, commodity, rolling_window):
        loaded["build_kwargs"] = {
            "predictions": predictions,
            "feature_rows": feature_rows,
            "as_of": as_of,
            "commodity": commodity,
            "rolling_window": rolling_window,
        }
        return FakeReport()

    def fake_export(report, destination):
        loaded["export"] = (report, destination)
        return FakeExported()

    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)
    monkeypatch.setattr(cli, "build_model_health_report", fake_build)
    monkeypatch.setattr(cli, "export_model_health_report", fake_export)

    result = runner.invoke(
        cli.app,
        [
            "model-health",
            "--as-of",
            "2026-06-12T18:00:00+00:00",
            "--rolling-window",
            "10",
            "--report-dir",
            str(report_dir),
        ],
    )

    assert result.exit_code == 0
    assert loaded["pred_commodity"] == "WTI"
    assert loaded["feature_commodity"] == "WTI"
    assert loaded["build_kwargs"]["as_of"] == datetime(2026, 6, 12, 18, tzinfo=UTC)
    assert loaded["build_kwargs"]["rolling_window"] == 10
    assert loaded["build_kwargs"]["predictions"] == ["prediction"]
    assert "Scored 2 WTI predictions" in result.output
    assert "price_model_accuracy=0.7500" in result.output
    assert str(FakeExported.metrics_path) in result.output


def test_ingest_etf_metrics_defaults_to_wisdomtree_fallbacks(monkeypatch) -> None:
    fetched: list[tuple[str, str | None]] = []
    loaded: dict[str, object] = {}
    expected = [
        ("SOIL", "SOIL.L"),
        ("LOIL", "LOIL.L"),
        ("3OIL", "3OIL.L"),
        ("3OIS", "3OIS.L"),
        ("SNGA", "SNGA.L"),
        ("LNGA", "LNGA.L"),
        ("3NGL", "3NGL.L"),
        ("3NGS", "3NGS.L"),
        ("BRNT", "BRNT.MI"),
        ("SBRT", "SBRT.MI"),
        ("LBRT", "LBRT.L"),
        ("3BRL", "3BRL.MI"),
        ("3BRS", "3BRS.MI"),
    ]

    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            loaded["connector_kwargs"] = kwargs

        def fetch_metric(self, *, fund_ticker: str, yahoo_symbol: str | None = None):
            fetched.append((fund_ticker, yahoo_symbol))
            return f"metric-{fund_ticker}"

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

        def upsert_fund_daily_metrics(self, metrics):
            loaded["metrics"] = metrics
            return cli.LoadResult(inserted=len(metrics))

    monkeypatch.setattr(cli, "YahooEtfMetricsConnector", FakeConnector)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(cli.app, ["ingest-etf-metrics", "--load"])

    assert result.exit_code == 0
    assert fetched == expected
    assert loaded["metrics"] == [f"metric-{ticker}" for ticker, _ in expected]
    assert "Fetched 13 ETF metric snapshots" in result.output


def test_ingest_wisdomtree_metrics_fetches_usd_fundlist_rows(monkeypatch) -> None:
    fetched: list[list[str]] = []
    loaded: dict[str, object] = {}

    class FakeMetric:
        def __init__(self, fund_ticker: str) -> None:
            self.fund_ticker = fund_ticker

    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            loaded["connector_kwargs"] = kwargs

        def fetch_metrics(self, *, fund_tickers: list[str]):
            fetched.append(fund_tickers)
            return [FakeMetric(ticker) for ticker in fund_tickers[:2]]

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

        def upsert_fund_daily_metrics(self, metrics):
            loaded["metrics"] = metrics
            return cli.LoadResult(inserted=len(metrics))

    monkeypatch.setattr(cli, "WisdomTreeFundListConnector", FakeConnector)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(cli.app, ["ingest-wisdomtree-metrics", "--load"])

    assert result.exit_code == 0
    assert fetched
    assert fetched[0][:4] == ["SOIL", "LOIL", "3OIL", "3OIS"]
    assert [metric.fund_ticker for metric in loaded["metrics"]] == ["SOIL", "LOIL"]
    assert "WisdomTree fund-list missing USD rows" in result.output
    assert "Fetched 2 WisdomTree metric snapshots" in result.output


def test_ingest_etf_metrics_fetches_explicit_yahoo_fallback_funds(monkeypatch) -> None:
    fetched: list[tuple[str, str | None]] = []
    loaded: dict[str, object] = {}

    class FakeConnector:
        def __init__(self, **kwargs) -> None:
            loaded["connector_kwargs"] = kwargs

        def fetch_metric(self, *, fund_ticker: str, yahoo_symbol: str | None = None):
            fetched.append((fund_ticker, yahoo_symbol))
            return f"metric-{fund_ticker}"

    class FakeRepository:
        @classmethod
        def from_settings(cls, settings):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

        def upsert_fund_daily_metrics(self, metrics):
            loaded["metrics"] = metrics
            return cli.LoadResult(inserted=len(metrics))

    monkeypatch.setattr(cli, "YahooEtfMetricsConnector", FakeConnector)
    monkeypatch.setattr(cli, "IngestionRepository", FakeRepository)

    result = runner.invoke(
        cli.app,
        ["ingest-etf-metrics", "--fund", "OILK", "--fund", "UCO", "--load"],
    )

    assert result.exit_code == 0
    assert fetched == [("OILK", "OILK"), ("UCO", "UCO")]
    assert loaded["metrics"] == ["metric-OILK", "metric-UCO"]
    assert "ETF metric snapshots" in result.output
