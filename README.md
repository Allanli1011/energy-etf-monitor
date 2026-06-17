# energy-etf-monitor

Data-first monitoring system for **futures-based energy commodity ETFs**. The project focuses on
issuer holdings, ETF creation/redemption flow, futures curves, COT positioning, inventories,
macro context, and market-moving news. Prediction-model training is no longer part of the primary
product path.

> Current focus: make the ETF data layer real and reliable. USCF commodity pools are fetched from
> the official USCF/ALPS holdings and dailyprice API, and ProShares leveraged/inverse products are
> parsed from the official fund pages. Yahoo
> Finance remains an explicit fallback/diagnostic source, not the default ETF data layer.

## What This Is

This is a monitoring dashboard and scheduled data pipeline. It answers practical questions:

- Which energy ETFs saw creation/redemption pressure today?
- How large are those flows versus AUM?
- Which contract months are held by the issuer-reported portfolios?
- Are front-month roll funds concentrated in a contract that could matter for roll pressure?
- What do inventories, COT positioning, futures curve shape, and news say about the market state?

It is not currently intended to train or run price/spread prediction models. Legacy model commands
remain in the codebase for reference, but the documented workflow, nightly job, and deployment
path are data-monitoring first.

## Data Sources

| Area | Primary Source | Notes |
|---|---|---|
| USCF ETF NAV, shares, creation/redemption, holdings | USCF public holdings pages via ALPS MarketingAPI | Official daily JSON for `USO`, `USL`, `UNG`, `UNL`, `UGA`, `BNO`; raw payloads saved before parsing. |
| ProShares ETF NAV, shares, holdings | ProShares official fund pages | Official page HTML for `UCO`, `SCO`, `BOIL`, `KOLD`; holdings tables include exposure weights and contract months. |
| ETF fallback AUM/price context | Yahoo Finance quote summary | Explicit fallback for funds without an issuer connector or for cross-checks; no default dashboard ETF currently depends on it. |
| Futures curves | Yahoo Finance futures feed | Daily curve rows by commodity product code, including Brent `BZ=F` / `BZ*.NYM`. |
| Inventory | EIA API | Crude, Cushing, natural gas, and product inventory series; Brent has no EIA-style inventory series configured. |
| Macro | FRED API | USD index, real yields, WTI spot, retail gasoline. |
| Positioning | CFTC Socrata COT | Disaggregated futures-only positioning, including Brent Last Day `06765T`. |
| News | GDELT + RSS, optional Marketaux/LLM | Classified into market-moving event rows and optional alerts. |

## Quick Start

Install and verify:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```

Initialize the database:

```bash
uv run energy-etf-monitor init-db
```

Fetch official ETF holdings and daily metrics:

```bash
uv run energy-etf-monitor ingest-etf-holdings --load
```

This defaults to the official-source products in the registry: `USO`, `USL`, `UCO`, `SCO`,
`UNG`, `UNL`, `BOIL`, `KOLD`, `UGA`, and `BNO`.
For a single fund:

```bash
uv run energy-etf-monitor ingest-etf-holdings --fund USO --load
```

Fetch explicit Yahoo ETF fallback metric context:

```bash
uv run energy-etf-monitor ingest-etf-metrics --fund OILK --load
```

Without `--fund`, this only runs for registry products that do not yet have an issuer connector.

Fetch the rest of the monitoring backbone:

```bash
uv run energy-etf-monitor ingest-phase0 --load
uv run energy-etf-monitor ingest-news --timespan 1d --load
```

Build factor rows and launch the dashboard:

```bash
uv run energy-etf-monitor build-features --commodity WTI --as-of 2026-06-12T18:00:00+00:00
uv run --extra dashboard streamlit run src/energy_etf_monitor/dashboard/app.py
```

Run the scheduled-style local pipeline:

```bash
uv run energy-etf-monitor run-nightly --commodity ALL
```

`run-nightly` now performs data ingestion, official ETF holdings refresh, fallback ETF metric
refresh where configured, news ingestion, and factor-row construction. The GitHub schedule runs it
with `--commodity ALL` so all registered commodity pages, including Brent, receive factor rows. It
does not train models, score predictions, or run model-health reports.

## ETF Coverage

ETF coverage is registry-driven in `src/energy_etf_monitor/etfs.py`.

- WTI: `USO`, `USL`, `UCO`, `SCO`
- Natural gas: `UNG`, `UNL`, `BOIL`, `KOLD`
- RBOB gasoline: `UGA`
- Brent: `BNO`, `BRNT`, `SBRT`, `LBRT`, `3BRL`, `3BRS`

The dashboard separates official issuer data from fallback context:

- USCF funds use official NAV, shares outstanding, creation/redemption (`cr`) and holdings from
  the USCF/ALPS API, including `BNO`.
- `UCO`, `SCO`, `BOIL`, and `KOLD` use official ProShares page NAV, net assets, and holdings
  tables.
- WisdomTree Brent ETC/ETP products are shown on the Brent page as a European ETP sentiment layer;
  they are not default-ingested until a reliable issuer/Yahoo-symbol connector is added.
- Brent futures price/curve context uses Yahoo's free `BZ` futures symbols, and Brent positioning
  uses the CFTC Brent Last Day COT market code `06765T`; exchange-official ICE EOD settlement
  packages remain a paid upgrade path.
- If both sources exist for the same ticker/date, dashboard flow views prefer official issuer
  sources over Yahoo estimates.

## Architecture

```text
free/issuer sources
  -> idempotent connectors + raw payload archive
  -> SQLModel DB (SQLite default; Postgres optional)
  -> factor rows and dashboard projections
  -> Streamlit dashboard + static HTML report + optional alerts
```

Every persisted row carries both `report_date` and `knowledge_date`. This matters even without
prediction models: ETF holdings are T+1, COT is T+3, and EIA has release-time constraints. The
dashboard should never mix data that was not yet public at the selected decision timestamp.

## Docs

| Doc | Contents |
|---|---|
| [01-overview-and-constraints](docs/01-overview-and-constraints.md) | Scope, hard constraints, and market caveats |
| [02-etf-universe](docs/02-etf-universe.md) | Futures-based energy ETF/ETC universe |
| [03-architecture](docs/03-architecture.md) | Data-first architecture and deployment shape |
| [04-data-sources](docs/04-data-sources.md) | Free data sources and paid upgrade slots |
| [05-prediction-methodology](docs/05-prediction-methodology.md) | Archived modeling notes, not the current product path |
| [06-roadmap](docs/06-roadmap.md) | Current non-model roadmap |
| [07-deployment](docs/07-deployment.md) | GitHub Actions scheduled monitoring deployment |
| [08-code-audit-and-optimization](docs/08-code-audit-and-optimization.md) | Code audit, risks, and optimization backlog |

## Current Status

Implemented:

- Official USCF holdings/dailyprice connector with token discovery from USCF's public site.
- Official ProShares HTML holdings connector for `UCO`, `SCO`, `BOIL`, and `KOLD`.
- ETF registry and dashboard views for flow, strategy buckets, and contract-month exposure.
- Yahoo fallback metric ingestion for explicit cross-checks and products without issuer
  connectors.
- EIA, FRED, CFTC, futures-curve, GDELT/RSS/Marketaux, and optional LLM news connectors.
- SQLite/Postgres-compatible point-in-time storage with raw payload replay.
- Streamlit dashboard and static HTML report generation.
- CI, nightly monitoring workflow, manual data backfill workflow, and Pages publishing.

Main remaining work:

- Add live integration smoke tests for USCF/ALPS, ProShares pages, Yahoo, CFTC, EIA,
  and Pages rendering.
- Add batch-level source freshness/sequence checks, especially for ETF AUM jumps and missing
  holdings dates.
- Add versioned migrations before introducing more persisted ETF fields.
