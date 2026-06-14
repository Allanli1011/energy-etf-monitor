# energy-etf-monitor

Monitoring system for **futures-based energy commodity ETFs** (US & European markets) — tracking
fund flows, holdings, and roll strategy to produce **probabilistic directional tilt signals** on
the underlying futures price and, primarily, the **calendar (roll) spread**.

> Phase 0 development has started. The repository now includes the Python project skeleton,
> Postgres compose file, point-in-time storage models, quality-gated idempotent loading, first
> ingestion connectors for EIA, FRED, CFTC COT, CME settlement curves, and the initial USO PCF
> parser/storage path. The WTI vertical slice remains the first milestone; see
> [docs/06-roadmap.md](docs/06-roadmap.md) for the full build sequence.

## What this is (and is not)

This is a **monitoring dashboard that emits probabilistic directional tilts**, with SHAP-driver
explanations shown alongside a naive-persistence baseline. It is **not a price oracle**. Every
predictive signal in scope (inventory surprise, COT positioning, carry / term structure,
roll front-running) is — per the academic literature surveyed — weak, low-frequency, and
regime-dependent. The honest, load-bearing framing is in
[docs/01-overview-and-constraints.md](docs/01-overview-and-constraints.md).

The single best shot at a real, structural edge is the **roll/calendar-spread model**, not the
outright price model. See [docs/05-prediction-methodology.md](docs/05-prediction-methodology.md).

## Three hard facts that shape the whole design

1. **Energy is viable; "chemicals" is essentially an empty set in Western markets.** PP, PVC,
   methanol, PTA, ethylene futures trade liquidly only on Chinese exchanges (Zhengzhou / Dalian)
   and have **no US- or UCITS-listed ETF/ETC wrapper**. Chemicals are out of scope permanently.
2. **"Fund flows" are a daily proxy, not true creation/redemption.** Intraday create/redeem and
   the identity of Authorized Participants are never public. The usable proxy is daily
   `shares_outstanding` delta x NAV (T+1). COT positioning lumps all index/ETF exposure into an
   aggregate `Swap Dealers` bucket (cannot isolate one ETF) and is published T+3.
3. **Publication lag is a hard correctness constraint.** COT is T+3, ETF holdings T+1, EIA
   inventory same-day-after-release. Every table carries both `report_date` and `knowledge_date`;
   models may only use data whose `knowledge_date` has arrived. Getting this wrong makes the
   backtest lie.

## Architecture at a glance

Nightly batch pipeline (matched to low-frequency data), single machine, mostly-free data:

```
free sources -> idempotent connectors -> PostgreSQL (dual timestamps) -> features ->
  { price-direction model | roll-spread model }  (LightGBM) -> Streamlit dashboard + alerts
```

See [docs/03-architecture.md](docs/03-architecture.md) and
[docs/architecture.svg](docs/architecture.svg).

## Docs

| Doc | Contents |
|---|---|
| [01-overview-and-constraints](docs/01-overview-and-constraints.md) | Mission, the three hard facts, red lines, honest expectations |
| [02-etf-universe](docs/02-etf-universe.md) | Verified universe of futures-based energy ETFs/ETCs (US + EU) |
| [03-architecture](docs/03-architecture.md) | Layers, recommended stack, what is explicitly out of scope |
| [04-data-sources](docs/04-data-sources.md) | Free backbone + paid upgrade slots, with API endpoints / series IDs |
| [05-prediction-methodology](docs/05-prediction-methodology.md) | Two model heads, feature engineering, evidence, caveats |
| [06-roadmap](docs/06-roadmap.md) | Phased build (WTI end-to-end first), then horizontal expansion |
| [07-deployment](docs/07-deployment.md) | Scheduled runs on GitHub Actions (secrets, hosted DB, email alerts) |

## Development

This project targets Python 3.12+ and uses `uv` for local dependency management.

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```

Start the local Postgres database:

```bash
docker compose up -d postgres
uv run energy-etf-monitor init-db
```

Configure API keys by copying `.env.example` to `.env` and filling in the free keys for EIA and
FRED. CFTC can run without an app token at low volume, though a token is recommended for
production reliability.

Initial connector commands:

```bash
uv run energy-etf-monitor fetch-eia WCESTUS1
uv run energy-etf-monitor fetch-fred DTWEXBGS
uv run energy-etf-monitor fetch-wti-cot --limit 5000
uv run energy-etf-monitor fetch-cme-curve --product-code CL
```

Fetch a USO PCF/holdings CSV once you have the current issuer file URL:

```bash
uv run energy-etf-monitor fetch-uso-pcf --url "https://example.com/uso-pcf.csv"
```

Run the whole Phase 0 WTI batch:

```bash
uv run energy-etf-monitor ingest-phase0
```

Add `--load` to write normalized rows into the configured database after fetching:

```bash
uv run energy-etf-monitor ingest-phase0 --load
uv run energy-etf-monitor fetch-eia WCESTUS1 --load
uv run energy-etf-monitor fetch-fred DTWEXBGS --load
uv run energy-etf-monitor fetch-wti-cot --limit 5000 --load
uv run energy-etf-monitor fetch-cme-curve --product-code CL --load
uv run energy-etf-monitor fetch-uso-pcf --url "https://example.com/uso-pcf.csv" --load
```

After USO PCF data and matching CME CL settlements are loaded for a date, derive the AUM/OI
crowding metric:

```bash
uv run energy-etf-monitor derive-uso-crowding --report-date 2026-06-12
```

After the source rows are loaded, build a point-in-time WTI feature row for a specific decision
timestamp:

```bash
uv run energy-etf-monitor build-wti-features --as-of 2026-06-12T18:00:00+00:00
```

Build a date range for backfill-style feature generation:

```bash
uv run energy-etf-monitor build-wti-feature-range \
  --start-date 2026-06-01 \
  --end-date 2026-06-12 \
  --as-of-time 18:00:00+00:00
```

Export persisted WTI feature rows to the DuckDB-readable Parquet cache:

```bash
uv run energy-etf-monitor export-wti-feature-cache \
  --output-path data/processed/wti_daily_features.parquet \
  --start-date 2026-06-01 \
  --end-date 2026-06-12
```

Build, load, and export the WTI feature cache in one step:

```bash
uv run energy-etf-monitor backfill-wti-feature-cache \
  --start-date 2026-06-01 \
  --end-date 2026-06-12 \
  --as-of-time 18:00:00+00:00 \
  --output-path data/processed/wti_daily_features.parquet
```

Evaluate the first Phase 3 walk-forward baselines from a feature cache:

```bash
uv run energy-etf-monitor evaluate-wti-baselines \
  --feature-cache data/processed/wti_daily_features.parquet \
  --horizon-days 5 \
  --min-train-size 252 \
  --target-name price_direction \
  --report-dir data/processed/baseline_reports
```

Train and save the current reusable logistic baseline artifact (train one head per target):

```bash
uv run energy-etf-monitor train-wti-logistic-artifact \
  --feature-cache data/processed/wti_daily_features.parquet \
  --horizon-days 5 \
  --target-name price_direction \
  --output-path data/processed/models/wti_price_logistic.json

uv run energy-etf-monitor train-wti-logistic-artifact \
  --feature-cache data/processed/wti_daily_features.parquet \
  --horizon-days 5 \
  --target-name spread_direction \
  --output-path data/processed/models/wti_spread_logistic.json
```

Optionally train LightGBM heads instead (requires the `gbm` extra); `predict-daily` auto-detects
the model type from the saved artifact:

```bash
uv run --extra gbm energy-etf-monitor train-wti-gbm-artifact \
  --feature-cache data/processed/wti_daily_features.parquet \
  --horizon-days 5 \
  --target-name price_direction \
  --output-path data/processed/models/wti_price_gbm.json
```

Score the latest point-in-time feature row with both heads (add `--load` to persist to the
`daily_predictions` table):

```bash
uv run energy-etf-monitor predict-daily \
  --price-artifact data/processed/models/wti_price_logistic.json \
  --spread-artifact data/processed/models/wti_spread_logistic.json \
  --as-of 2026-06-12T18:00:00+00:00 \
  --load
```

Score persisted predictions against realized outcomes (decay monitor):

```bash
uv run energy-etf-monitor model-health \
  --commodity WTI \
  --rolling-window 20 \
  --report-dir data/processed/model_health
```

Ingest, classify, and load market-moving news (free GDELT + RSS, no key; Marketaux/LLM/webhook
alerts enabled by their optional secrets):

```bash
uv run energy-etf-monitor ingest-news --timespan 1d --load
```

Train a pooled cross-commodity model, or retrain everything from accumulated history:

```bash
uv run energy-etf-monitor train-pooled-artifact \
  --feature-cache WTI=data/processed/wti_daily_features.parquet \
  --feature-cache NATGAS=data/processed/natgas_daily_features.parquet \
  --target-name price_direction \
  --output-path models/pooled_price_logistic.json

uv run energy-etf-monitor retrain --models-dir models   # per-commodity + pooled heads
```

Launch the dashboard (Latest News / Today's Call / Price & Curve / Positioning / Inventory /
Model Health):

```bash
uv run --extra dashboard streamlit run src/energy_etf_monitor/dashboard/app.py
```

Other commodities (NatGas, RBOB) run through the same commands via `--commodity` — e.g. ingest the
whole registry, then build/export/train/predict for one of them:

```bash
uv run energy-etf-monitor ingest-phase0 --load            # all registered commodities
uv run energy-etf-monitor build-features --commodity NATGAS --as-of 2026-06-12T18:00:00+00:00
uv run energy-etf-monitor export-feature-cache --commodity NATGAS \
  --output-path data/processed/natgas_daily_features.parquet
```

Run the whole nightly pipeline locally (ingest → features → predict → model health). Prediction is
skipped if the model artifacts are not present yet:

```bash
uv run energy-etf-monitor run-nightly \
  --price-artifact models/wti_price_logistic.json \
  --spread-artifact models/wti_spread_logistic.json
```

In the cloud this runs on a schedule via GitHub Actions (`.github/workflows/nightly.yml`) with an
email alert on failure — see [docs/07-deployment.md](docs/07-deployment.md) for the required
secrets, hosted Postgres, and artifact setup.

Raw payloads are saved before parsing under `data/raw/<source>/<date>/`, matching the provenance
rule in the architecture plan. Parsed records carry both `report_date` and `knowledge_date`.
Database writes are idempotent on each table's natural key, and `knowledge_date` is stored as
UTC-naive for consistent SQLite/Postgres behavior. The quality gate runs before persistence and
sets `quarantine=true` for rows that violate point-in-time or plausibility checks. USO PCF loading
also derives the daily implied fund flow as
`(shares_outstanding[t] - shares_outstanding[t-1]) * NAV[t]` when a previous row exists. The
crowding metric keeps both `AUM / OI notional` and `held contracts / OI contracts` for the CL
contract months actually held by the fund. The first Phase 2 feature row combines CL M1/M2 carry,
CME curve spreads/curvature, front-month returns, carry changes, COT swap-dealer net, COT
z-score/index, crude inventory, seasonal inventory surprise, USD index, 10-year real yield,
roll-window flags, and USO crowding while respecting the requested `--as-of` timestamp. Feature
rows can be exported to Parquet under `data/processed/` for modeling and backtests.
The baseline evaluator can also export prediction-level CSV and metrics JSON reports, including
overall metrics and regime slices for 2008, 2014-16, 2020, 2021-22, and all other periods.
The walk-forward evaluator uses a **purged** expanding window: each example carries the date its
label becomes known (`target_report_date`, horizon trading days ahead) and the trainer drops any
training example whose label was not yet realized at the decision date, eliminating look-ahead
leakage. `predict-daily` then loads both logistic heads, scores the latest point-in-time feature
row, and writes `daily_predictions` rows with per-head probabilities, a naive-persistence
reference, model-version stamps, and ranked linear driver contributions.

## Status

Implementation started. Current status: Phase 0 foundation with tested ingestion primitives,
source connectors, raw-payload replay storage, Docker Postgres config, dual-timestamp storage
models, idempotent repository loading, lightweight quality quarantine, and a batch Phase 0
ingestion command. Phase 1 has started with a USO PCF parser, fund daily metric storage, holdings
storage, implied-flow derivation, and AUM/OI crowding metrics. Phase 2 has a first WTI feature
pipeline with point-in-time tests, curve-shape features, front-month return/carry deltas,
historical COT/inventory transforms, roll-window features, range construction, and Parquet export.
It also includes a one-step feature-cache backfill command. Phase 3 has forward target generation,
purged walk-forward naive/logistic baselines (look-ahead leakage fixed), regime-sliced reports, and
reusable logistic model artifacts. Phase 4 has two-head daily inference (`predict-daily`) writing to
the `daily_predictions` table, a point-in-time decay monitor (`model-health`) scoring predictions
against realized outcomes (model-vs-naive accuracy/Brier, overall, per regime, and rolling), a
Streamlit dashboard (`--extra dashboard`) with a tested pure data layer, and LightGBM heads
(`--extra gbm`) sharing one interface with the logistic baseline. **Phase 4 is complete** (MVP
definition of done met). Phase 5 orchestration is in place: a `run-nightly` command and GitHub
Actions workflows (CI on push/PR; a scheduled nightly run with email-on-failure). Phase 6
generalized the pipeline to a `CommodityConfig` registry (WTI, NatGas, RBOB) so ingestion, feature
building, prediction, model health, and the dashboard all work per-commodity via `--commodity`
(Brent pending an ICE curve source). Phase 7 adds the News Impact Monitor: a free GDELT connector,
a transparent rule-based impact classifier (commodity / catalyst / direction / importance /
confidence), URL+title deduplication, a dashboard news lane, and high-impact alert selection;
`ingest-news` and the nightly job populate it. Enhancements on top: multi-source news (Marketaux +
RSS), an optional LLM classifier (`llm` extra), Slack/ntfy alert posting, point-in-time news
features in the model, cross-commodity pooled training, and a monthly auto-retrain workflow that
commits refreshed artifacts. Scheduled in the cloud via three GitHub Actions workflows (CI, nightly,
monthly-retrain) — see [docs/07-deployment.md](docs/07-deployment.md). Target stack remains
Python 3.12+, PostgreSQL 16, LightGBM, Streamlit — all free / self-hostable.
