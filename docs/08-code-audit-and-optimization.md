# 08 - Code audit and optimization backlog

Audit date: 2026-06-15.

## Verification

Reviewed scope:

- Python source under `src/energy_etf_monitor/`.
- Unit tests under `tests/unit/`.
- GitHub Actions workflows.
- README, documentation, dashboard report template, and ETF registry.

Local checks:

```powershell
.\.venv\Scripts\ruff.exe check .
New-Item -ItemType Directory -Force tmp | Out-Null
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp tmp\pytest
```

Results:

- Ruff: `All checks passed`.
- Pytest: `174 passed`.
- Coverage report total: `89%`.

Live ETF smoke test:

```powershell
energy-etf-monitor init-db
energy-etf-monitor ingest-etf-holdings --load
```

Result against live issuer endpoints:

- `10` official ETF snapshots fetched.
- `10` daily metric rows parsed.
- `74` issuer holding rows parsed.
- `84` rows loaded into a temporary SQLite database.
- Requested universe: `USO`, `USL`, `UNG`, `UNL`, `UGA`, `DBO`, `UCO`, `SCO`, `BOIL`, `KOLD`.

Environment note: `uv` was not on PATH in this Windows workspace, so the checked-in `.venv` was
used for verification. Pytest cache writes were disabled because the local `.pytest_cache` and
default Windows temp pytest directory were not writable in this sandbox.

## Current strengths

- The project now matches the user's desired product shape: data monitoring first, prediction
  training outside the primary workflow.
- ETF coverage is registry-driven and no longer crowded into one or two products per commodity.
- Default ETF holdings ingestion now uses official issuer sources:
  - USCF/ALPS API for `USO`, `USL`, `UNG`, `UNL`, `UGA`.
  - Invesco DNG API for `DBO`.
  - ProShares official fund pages for `UCO`, `SCO`, `BOIL`, `KOLD`.
- Raw payloads are saved before parsing, including USCF JSON, Invesco JSON, and ProShares HTML.
- Dashboard ETF rows prefer official issuer metrics over Yahoo fallback estimates for the same
  ticker/date.
- Point-in-time discipline remains central: persisted rows keep `report_date` and
  `knowledge_date`, and repository reads filter by known-at time.
- Workflows have moved to monitoring: nightly refreshes data and factor rows; backfill does not
  train or commit model artifacts; the monthly retrain workflow has been removed.

## Findings and optimization backlog

Priority labels are implementation urgency, not business importance.

| Priority | Area | Finding | Suggested next step |
|---|---|---|---|
| P1 | Source freshness | The pipeline can fetch issuer data, but it does not yet persist a structured per-source run status, latest as-of date, or stale-source reason. | Add run reports under `data/processed/run_reports/` and surface freshness in the dashboard. |
| P1 | Batch validation | Record-level quality gates exist, but there are no batch checks for missing ETF rows, abnormal AUM jumps, extreme holdings weights, or holiday-shifted release calendars. | Add post-ingestion validation before factor-row builds and store reason codes. |
| P1 | HTTP robustness | Invesco requires a curl path because the DNG edge returns 406 to Python/httpx. Other connectors still lack shared retries/backoff/source-health metrics. | Add a shared fetch wrapper with retries, backoff, status capture, and source-specific client overrides. |
| P1 | Repository size | `IngestionRepository` mixes upserts, dashboard read models, feature assembly, and derived metrics. | Split persistence, feature building, dashboard queries, and derived metric services. |
| P1 | Migrations | Schema evolution is not versioned for SQLite/Postgres. | Add Alembic or a minimal versioned migration table before expanding ETF fields further. |
| P2 | Live integration suite | The live smoke was manual. CI should not hit free endpoints on every push, but manual integration tests would catch endpoint drift. | Add `pytest -m integration` tests for USCF/ALPS, Invesco DNG, ProShares pages, Yahoo futures, CFTC, and EIA. |
| P2 | CLI naming | Some legacy WTI/model-era commands remain visible. | Add generic aliases and mark modeling commands as archived/research in help text. |
| P2 | Dashboard UX | The dashboard lacks a compact source-health banner and stale-data warnings. | Show latest issuer as-of date, source, and fallback/official status per ETF. |
| P3 | Performance | Per-row upserts are fine for current volumes but will slow if historical backfills grow. | Add bulk upsert only after profiling shows it matters. |

## Resolved in this update

- Added `InvescoHoldingsConnector` for `DBO` official DNG API data.
- Added `ProSharesHoldingsConnector` for `UCO`, `SCO`, `BOIL`, and `KOLD` official fund-page data.
- Expanded ETF registry source routing with official USCF/Invesco/ProShares groups.
- Changed `ingest-etf-holdings --load` to fetch the full official default ETF universe.
- Changed Yahoo ETF metrics into explicit fallback/cross-check behavior.
- Updated dashboard source priority to prefer `uscf`, `invesco`, and `proshares` over `yahoo_etf`.
- Updated README, data-source docs, architecture docs, roadmap, deployment notes, and architecture
  diagram for the non-model official ETF data path.

## Suggested next implementation sequence

1. Add structured source run reports and dashboard freshness banners.
2. Add manual integration tests for live issuer endpoints.
3. Add ETF batch anomaly checks for missing data, large AUM/flow moves, and unexpected holdings
   weights.
4. Split repository responsibilities.
5. Add versioned migrations.
