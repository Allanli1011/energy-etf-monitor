# 06 - Roadmap

The roadmap is now **data-monitoring first**. Prediction-model training is intentionally out of
scope for the main product path; the priority is dependable ETF data, source freshness, and
decision-useful dashboard views.

## Phases

| Phase | Focus | Deliverable |
|---|---|---|
| 0 | Foundation | SQLite/Postgres storage, raw payload archive, EIA/FRED/CFTC/ICE COT/futures connectors, quality gate. |
| 1 | Official ETF data | USCF and ProShares official ETF connectors for the default dashboard universe; derive flow and contract-month exposure. |
| 2 | Monitoring factors | Point-in-time factor rows for curve, inventory, COT, macro, ETF crowding, roll window, and news. |
| 3 | Dashboard | Streamlit/static report with ETF Flow & Roll Pressure, curve, COT, inventory, and news panels. |
| 4 | Automation | GitHub Actions nightly monitoring, manual data backfill, SQLite state branch, Pages deployment, failure alerts. |
| 5 | Source health | Add source health, live integration tests, freshness checks, and batch-level ETF validation. |
| 6 | Quality hardening | Batch-level freshness checks, AUM/flow jump checks, holiday-aware release calendars, migrations. |

## Current Status

Implemented:

- USCF official holdings/dailyprice API ingestion through `UscfHoldingsConnector`.
- ProShares official HTML holdings ingestion for `UCO`, `SCO`, `BOIL`, and `KOLD` through
  `ProSharesHoldingsConnector`.
- Legacy `fetch-uso-pcf --url ...` remains available for explicit CSV replay, while
  `fetch-uso-pcf` without `--url` now uses the official USCF API.
- `ingest-etf-holdings --load` fetches official snapshots for the default ETF universe:
  `USO`, `USL`, `UCO`, `SCO`, `UNG`, `UNL`, `BOIL`, `KOLD`, `UGA`, `BNO`.
- `ingest-wisdomtree-metrics --load` attempts official WisdomTree Europe fund-list metrics for
  USD-listed Brent, WTI, and natural gas ETPs.
- `ingest-etf-metrics --fund ... --load` remains available for explicit Yahoo cross-checks;
  without `--fund`, it does not fetch any default Yahoo ETF layer.
- Dashboard ETF rows ignore Yahoo estimates for WisdomTree products and show stale/missing
  official data instead.
- `run-nightly` now performs data ingestion, ETF holdings refresh, WisdomTree fund-list metrics,
  news ingestion, and factor-row construction. The scheduled workflow runs with `--commodity ALL`
  so every registered commodity page gets a fresh factor row. It does not run prediction or
  model-health steps.
- GitHub Actions `nightly.yml` follows the data-monitoring path; `monthly-retrain.yml` has been
  removed; `backfill.yml` no longer trains or commits model artifacts.

## ETF Data Priorities

Near-term:

1. Add live integration smoke tests for USCF/ALPS token discovery, `dailyprice`, and
   `holding/{ticker}/full`, and ProShares holdings pages.
2. Add source freshness checks: latest holdings date, latest dailyprice/NAV date, missing ETF rows,
   and stale official metrics.
3. Add batch-level ETF validation: large AUM changes, large flow/AUM moves, missing holdings, and
   holdings weights that are unexpectedly empty or extreme.
4. Add a dashboard freshness banner so stale ETF issuer data is visible immediately.

Issuer coverage:

- USCF: `USO`, `USL`, `UNG`, `UNL`, `UGA`, `BNO`.
- ProShares: `UCO`, `SCO`, `BOIL`, `KOLD`.
- WisdomTree fund-list metrics: Brent (`BRNT`, `SBRT`, `LBRT`, `3BRL`, `3BRS`), WTI (`SOIL`,
  `LOIL`, `3OIL`, `3OIS`), and natural gas (`SNGA`, `LNGA`, `3NGL`, `3NGS`) using same-name USD
  listings where available.
- Brent dashboard: covers `BNO`, `BRNT`, `SBRT`, `LBRT`, `3BRL`, and `3BRS`; Brent futures
  factors use Yahoo `BZ` prices/curve snapshots and ICE Futures Europe COT commodity code `B`.
  EIA-style inventory coverage remains unavailable.

Historical ETF backfill:

- The current issuer endpoints are latest-snapshot oriented. Multi-year historical holdings
  require either archived issuer files, SEC filings, paid data, or saved daily raw payloads going
  forward.
- Going forward, the nightly job will accumulate official raw payloads under
  `data/raw/uscf_api/` and `data/raw/proshares_html/`, making the local
  database and raw archive the durable history.

## Definition Of Done For The Non-Model MVP

A working monitoring loop that, each night:

- updates official ETF NAV, shares, issuer flow where disclosed, and holdings;
- updates official WisdomTree fund-list metrics where configured;
- updates futures curves, inventories, COT, macro, and news;
- builds point-in-time factor rows;
- publishes a dashboard/static report showing ETF flow, roll pressure, contract exposure, curve,
  inventory, positioning, and market-moving news;
- stores raw payloads and normalized rows idempotently with `report_date` and `knowledge_date`.

## Deferred

- Prediction training, prediction inference, and model-health reporting.
- Hosted database setup unless SQLite state-branch persistence becomes insufficient.
- European UCITS ETC ingestion unless a transparent holdings source is identified.
- Broad commodity funds until the single-commodity ETF data layer is robust.
