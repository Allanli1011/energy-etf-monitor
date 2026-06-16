# 03 - Architecture

Chosen approach: **nightly data monitoring + issuer ETF holdings first**. The system no longer
treats predictive modeling as the product center. The core value is a reliable, point-in-time data
view of ETF flows, issuer holdings, futures curves, inventories, COT positioning, macro context,
and news.

![architecture](architecture.svg)

## Layers

```text
free and issuer data sources
   -> idempotent connectors                         [data/raw/<source>/<date>/]
   -> SQLModel DB (SQLite default; Postgres optional) [+ quality quarantine]
   -> factor rows and dashboard projections          [ETF flow, exposure, curve, COT, inventory]
   -> Streamlit dashboard + static HTML report + rule-based alerts
```

## Ingestion

- Python 3.12 + `httpx`; one connector per source.
- Raw payloads are saved before parsing for provenance and replay.
- USCF ETF data is fetched from the official public holdings stack:
  - `api_key.php` provides the bearer token and MarketingAPI base URL.
  - `dailyprice/{ticker}` provides NAV, shares outstanding, total NAV, and
    creation/redemption shares.
  - `holding/{ticker}/full` provides issuer holdings, weights, market value, and futures symbols.
- ProShares `UCO`, `SCO`, `BOIL`, and `KOLD` data is parsed from the official fund pages:
  - the price/snapshot blocks provide NAV and net assets.
  - the holdings table provides exposure weights, descriptions, contracts, and notional values.
- Yahoo ETF metrics are a fallback context source for explicit cross-checks or products without an
  issuer connector.
- The futures curve provider remains swappable so CME DataMine, Barchart, or another paid source
  can replace the free provider later.

## Storage

- SQLite is the default; PostgreSQL remains supported with `ENERGY_ETF_MONITOR_DATABASE_URL`.
- Every record stores both `report_date` and `knowledge_date`.
- The repository performs idempotent upserts on natural keys.
- The quality gate quarantines rows for point-in-time impossibilities and basic plausibility
  failures.
- Raw payloads are stored under `data/raw/`; processed factor exports live under `data/processed/`.

## ETF Data Model

The ETF registry in `etfs.py` describes fund role, commodity, issuer, strategy, leverage, and
whether a product should appear in dashboard or ingest defaults.

Current default official-holdings coverage:

- WTI: `USO`, `USL`, `UCO`, `SCO`
- Natural gas: `UNG`, `UNL`, `BOIL`, `KOLD`
- RBOB gasoline: `UGA`

Current fallback metric context:

- No default dashboard ETF currently depends on Yahoo fallback metrics.
- `ingest-etf-metrics --fund ...` remains available for explicit Yahoo cross-checks or future
  products without issuer coverage.

Dashboard flow views prefer official issuer metrics over Yahoo estimates when both sources exist
for the same fund/date. USCF `cr` is converted to flow as `cr * NAV`; if an issuer source does not
provide creation/redemption shares, the repository can still derive a net flow proxy from changes
in shares outstanding.

## Factor Rows

Feature/factor rows remain useful even without model training. They are a compact, point-in-time
state snapshot for dashboards and backfills:

- futures curve spreads, carry, curvature, and front-month returns;
- COT net positioning, z-scores, and open interest;
- EIA inventory levels and seasonal surprise;
- macro levels such as USD and real yields;
- ETF crowding and roll-window interaction;
- aggregated point-in-time news features.

The CLI names still include some historical "feature" terminology. In the current product framing,
these rows are monitoring factors, not model inputs.

## Orchestration

GitHub Actions is the default scheduler:

- `ci.yml`: lint + tests.
- `nightly.yml`: scheduled monitoring run, SQLite state restore/push, email on failure.
- `backfill.yml`: manual source/factor backfill, no model training.
- `pages.yml`: static report build and deployment.

The previous monthly retrain workflow has been removed from the documented path.

## Dashboard And Alerts

Implemented dashboard sections:

- Latest Market-Moving News
- ETF Flow & Roll Pressure
- Price & Curve
- Positioning (COT)
- Inventory

The static report mirrors the same data-first view for GitHub Pages. Alerts are rule-based and
independent of model output: workflow failure, high-impact news, roll-window notices, and crowded
ETF/contract exposure.

## Recommended Stack

| Concern | Choice |
|---|---|
| Ingestion | Python 3.12 + httpx, per-source connectors |
| Storage | SQLite default or PostgreSQL, dual timestamps, pydantic quality gate |
| Analytical cache | Parquet + DuckDB |
| Orchestration | GitHub Actions cron + manual workflows |
| Dashboard | Streamlit app + self-contained static HTML report |
| Alerting | Email failure alerts, Slack/ntfy optional |

## Explicitly Out Of Scope

Prediction-model training is not part of the current product path. The old modeling modules and
CLI commands are retained for reference/backward compatibility, but scheduled jobs and docs should
not depend on them.

Still out of scope as over-engineering for this project: Dagster, dbt, Great Expectations,
TimescaleDB hypertables, Grafana, and a FastAPI serving layer. European UCITS ETCs remain
secondary because most are swap-based and do not disclose transparent futures holdings.
