# 03 — Architecture

Chosen approach: **nightly batch + lightweight gradient-boosted models**. All inputs are
daily/weekly low-frequency data, so a single-machine nightly run matches the cadence exactly — no
streaming, no Kafka, no enterprise orchestration. Three correctness-critical pieces are grafted in
from a heavier "data-platform" design; everything else from that design is deliberately rejected
as over-engineering for a single user.

![architecture](architecture.svg)

## Layers

```
free data sources
   -> idempotent connectors (per source)            [data/raw/<source>/<date>/]
   -> PostgreSQL  (report_date + knowledge_date)     [+ thin quality gate / quarantine]
   -> feature engineering                            [carry, COT index, inventory surprise, crowding]
   -> { price-direction model | roll-spread model }  [LightGBM, two heads]
   -> Streamlit dashboard + rule-based alerts
```

### 1. Ingestion
- Python 3.12 + `httpx`. One idempotent connector per source implementing a common
  `fetch / validate / normalize / load` interface.
- Raw payloads saved dated to `data/raw/<source>/<date>/` before parsing (provenance + replay).
- **Graft #1 — swappable curve-provider interface:** the CME settlement scraper (the most fragile
  component) sits behind a `CurveProvider` protocol so it can be replaced by CME DataMine /
  Barchart OnDemand later without touching downstream code.

### 2. Storage
- Local Docker **PostgreSQL 16** (or Supabase / Neon free tier) via SQLAlchemy / SQLModel.
- **Graft #2 — dual timestamps:** every table carries both `report_date` and `knowledge_date`.
  This is what stops the backtest from lying.
- **Graft #3 — thin quality gate:** lightweight `pydantic` assertions (NOT Great Expectations) —
  freshness checks against the release calendar (EIA Wed/Thu, COT Fri), range/plausibility checks
  (no negative OI, no >50% day-over-day AUM jump, no COT date gaps). Failures get a `quarantine`
  flag so bad batches never silently enter feature builds.
- Parquet files in `data/processed/` read via DuckDB are the analytical cache so backtests never
  hit the live DB.

### 3. Feature engineering
- pandas / polars + DuckDB, run nightly after ingestion. ~15–25 features per commodity per day,
  all publication-lag-adjusted. See [05-prediction-methodology.md](05-prediction-methodology.md).

### 4. Modeling
- **LightGBM**, two heads: `price_direction` and `spread_direction`. scikit-learn
  logistic/ridge as the interpretable baseline.
- Pooled cross-commodity training (commodity-id as a categorical) to fight thin sample size.
- Expanding-window walk-forward, monthly retrain, evaluated across the 2008 / 2014–16 / 2020 /
  2021–22 regimes.

### 5. Inference
- `predict_daily.py` scores the latest feature row per commodity, writes to a `predictions` table
  (direction prob, point estimate, top-3 SHAP features, model_version).

### 6. Orchestration
- macOS `launchd` plist (or a single local Prefect agent if you want retries/UI) running one bash
  script: `ingest -> quality gate -> build_features -> (monthly) retrain -> predict_daily`.
  Logs to file. **Explicitly not Airflow / Dagster.**

### 7. Dashboard + alerts
- **Streamlit + Plotly**, reading Postgres directly. Pages: Today's Calls / Curve Explorer /
  Positioning (COT) / Inventory / **Model Health** (rolling Brier vs naive baseline; flags decay).
- Alerts via free Slack webhook or `ntfy.sh`: pipeline failure, the `USO`-2020 crowding alert
  (AUM/OI above threshold), and the T-10 roll-window-approach notice — all rule-based, independent
  of model output.

## Recommended stack (summary)

| Concern | Choice |
|---|---|
| Ingestion | Python 3.12 + httpx, per-source connectors, swappable `CurveProvider` |
| Storage | PostgreSQL 16 (Docker / Supabase / Neon free tier), dual timestamps, pydantic quality gate |
| Analytical cache | Parquet + DuckDB |
| Orchestration | launchd plist (or local Prefect agent) |
| Modeling | LightGBM (2 heads) + scikit-learn baseline; MLflow file-store later |
| Dashboard | Streamlit + Plotly (Streamlit Community Cloud optional) |
| Alerting | Slack webhook / ntfy.sh |

## Explicitly out of scope (rejected as over-engineering for one user)

Dagster, dbt, Great Expectations, TimescaleDB hypertables, Grafana, FastAPI serving layer, and a
European UCITS ETC ingestion layer. Data volume is thousands of rows/day — none of that
infrastructure is justified, and the predictive edge lives in the data/signals, not the
orchestrator. Chemicals (PP/PVC/methanol/ethylene/PTA) are out of scope permanently — no Western
ETF wrapper exists.
