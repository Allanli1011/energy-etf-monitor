# 06 — Roadmap

Build **WTI end-to-end first** — it has the richest free data (CME settlements, EIA Cushing stocks,
CFTC disaggregated COT since 2006, USCF PCF holdings since 2006) and is the best test of the two
hardest-to-get-right pieces: point-in-time (dual-timestamp) joins and the decay scoreboard. Once
those are proven, the other commodities are largely config-driven expansion.

| Phase | Weeks | Deliverable |
|---|---|---|
| 0 | 1 | Stand up Postgres (Docker); get EIA + FRED keys; write & test EIA-inventory, FRED-macro, CFTC-COT(WTI) connectors; verify CME CL settlement scraping for M1–M6 |
| 1 | 1–2 | `USO` PCF connector (holdings + shares outstanding + NAV) → derive implied flow & AUM/OI; backfill WTI history to 2006–2010 |
| 2 | 2 | Feature pipeline (carry, COT index, inventory surprise, crowding, macro) **with dual-timestamp / lag unit tests on known historical dates** |
| 3 | 2–3 | Logistic-regression baseline + LightGBM price-head and spread-head via walk-forward; evaluate vs naive-persistence across 2008 / 2014–16 / 2020 / 2021–22 |
| 4 | 3 | `predict_daily.py` + flat-file prediction log + single-page Streamlit (Today's Call + Curve Explorer + Model Health), **WTI only** |
| 5 | 3–4 | Wire up nightly orchestration (launchd / Prefect agent) + failure alerting (Slack / ntfy) |
| 6 | 4–6 | Horizontal expansion: Brent (`BNO`), NatGas (`UNG`/`UNL`), RBOB (`UGA`) via configs + per-issuer PCF parsers; retrain pooled multi-commodity models |
| 7 | 6+ | Add GDELT sentiment; broad funds (`PDBC` / `USCI`); monthly retrain cadence; decay-triggered review process |

## Definition of done for the MVP (end of Phase 4)

A working WTI loop that, each night, produces:
- a price-direction lean and a spread-direction lean with confidence + top-3 SHAP drivers,
- displayed against a naive-persistence baseline,
- with a Model-Health page tracking rolling accuracy/Brier vs that baseline,

all built on point-in-time-correct data (dual timestamps, COT lagged 3 business days, holdings
T+1).

## What to defer (and why)

- **Brent / NatGas / RBOB / broad funds** — architecture is identical; mostly ticker configs +
  per-issuer PCF parsers. Add after the WTI loop is proven.
- **GDELT sentiment** — nice-to-have; add after the core loop works.
- **MLflow** — start with a flat pickle + CSV prediction log; add the file-store once the loop is
  stable.
- **Hosted Postgres** — start with local Docker (or SQLite if Docker is friction).
- **European UCITS layer** — swap-based, holdings opaque; low payoff, secondary sentiment only.

## Per-issuer onboarding cost (a real risk, not "just a config")

USCF PCF file formats are issuer-specific and not standardized (CSV/XLS/PDF, differing layouts).
Each fund family's holdings/roll-detection parser must be built and tested individually. Budget for
this when expanding beyond WTI/`USO`.
