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
| 5 | 3–4 | Wire up nightly orchestration (GitHub Actions cron) + failure alerting (email) |
| 6 | 4–6 | Horizontal expansion: Brent (`BNO`), NatGas (`UNG`/`UNL`), RBOB (`UGA`) via configs + per-issuer PCF parsers; retrain pooled multi-commodity models |
| 7 | 6+ | Add the News Impact Monitor: a dashboard news lane showing latest energy-futures-moving news, per-article importance, impact direction, confidence, and rationale; then broad funds (`PDBC` / `USCI`), monthly retrain cadence, and decay-triggered review process |

## Definition of done for the MVP (end of Phase 4)

A working WTI loop that, each night, produces:
- a price-direction lean and a spread-direction lean with confidence + top-3 SHAP drivers,
- displayed against a naive-persistence baseline,
- with a Model-Health page tracking rolling accuracy/Brier vs that baseline,

all built on point-in-time-correct data (dual timestamps, COT lagged 3 business days, holdings
T+1).

## Phase 1 implementation notes

The first USO PCF slice is implemented as a configurable CSV/text parser and loader:
- `fetch-uso-pcf --url ...` saves the raw PCF payload, parses fund-level NAV / shares outstanding /
  total net assets, and extracts holdings.
- `--load` writes `fund_daily_metrics` and `fund_holdings` idempotently.
- Implied flow is derived at load time when the previous fund row exists:
  `(shares_outstanding[t] - shares_outstanding[t-1]) * NAV[t]`.
- `derive-uso-crowding --report-date ...` joins loaded USO holdings with matching CME CL settlement
  open interest and writes `fund_crowding_metrics`, including both `AUM / OI notional` and
  `held contracts / OI contracts` for the held contract months.

Still required before Phase 1 is complete: pin the current issuer PCF URL or discovery flow,
validate against live USCF files, add historical backfill tooling, and make the crowding feature
available to the Phase 2 feature pipeline.

## Phase 2 implementation notes

The first WTI feature-pipeline slice is implemented as an as-of builder:
- `build-wti-features --as-of ...` derives and loads one `daily_feature_rows` record for the
  requested decision timestamp.
- `build-wti-feature-range --start-date ... --end-date ... --as-of-time ...` derives and loads a
  range of daily WTI feature rows for backfill-style generation.
- `export-wti-feature-cache --output-path ...` exports persisted feature rows to a DuckDB-readable
  Parquet cache under `data/processed/`.
- `backfill-wti-feature-cache --start-date ... --end-date ... --as-of-time ... --output-path ...`
  runs range build, idempotent load, and Parquet export in one command.
- Current fields include CL front-month settle, M1/M2 carry, M1/M2, M2/M3 and M3/M6 spreads,
  M1/M2/M3 curvature, front-month 1-day return, carry 1-day change, COT swap-dealer
  net/open-interest/z-score/index, EIA crude inventory, seasonal inventory surprise, FRED USD
  index, FRED 10-year real yield, USO AUM/OI crowding, roll-window flag, and roll-window x crowding
  interaction.
- The repository uses `knowledge_date <= as_of` and `report_date <= as_of.date()` for every source,
  with tests proving that a COT row published after the decision timestamp is excluded even when its
  report date is earlier.
- Historical transforms use only rows that were already known as of the requested decision
  timestamp: COT windows are limited by `knowledge_date <= as_of`, and the inventory surprise uses
  same-ISO-week historical observations that were already published.
- Release-lag fixtures cover concrete EIA and COT publication cutoffs: a June 2026 EIA row is
  excluded before its 14:30 UTC release timestamp and included after it; the June 9, 2026 COT row is
  excluded before its June 12, 2026 19:30 UTC release timestamp and included after it.
- Feature-row `knowledge_date` is the max first-known time of the source rows actually used.

Still required before Phase 2 is complete: validate the generated cache shape on real WTI history,
pin live USO PCF discovery/backfill inputs, and decide whether to add broader Cushing-specific
inventory features before handing the cache to Phase 3 model training.

## Phase 3 implementation notes

The first modeling slice is implemented for WTI baseline evaluation:
- `evaluate-wti-baselines --feature-cache ... --horizon-days ... --min-train-size ...` reads the
  DuckDB/Parquet feature cache, creates forward price-direction or spread-direction targets, and
  evaluates walk-forward baselines.
- `--report-dir ...` exports prediction-level CSV and metrics JSON files for baseline review.
- `train-wti-logistic-artifact --feature-cache ... --output-path ...` trains the current reusable
  logistic baseline on the full feature cache and saves a JSON model artifact.
- Target generation is horizon-based: price target is whether future front-month settle is above
  the current settle; spread target is whether future M1/M2 spread is above the current spread.
- The baseline evaluator uses **purged** expanding windows: each prediction trains only on examples
  whose label was already realized before the decision date (see the correction below).
- Current baselines are naive persistence and a lightweight logistic-regression baseline implemented
  without external ML dependencies.
- Reports include overall metrics plus regime-sliced metrics for `gfc_2008`,
  `oil_crash_2014_2016`, `covid_2020`, `inflation_2021_2022`, and `other`.

### Phase 3 correction — walk-forward label leakage (fixed)

The first walk-forward slice trained on every example whose `report_date` preceded the decision
date — but each example's label is realized `horizon_days` later, so the most recent `horizon_days`
training examples carried labels from *after* the decision date. That is look-ahead leakage and it
inflates backtest metrics (it also corrupted the naive-persistence baseline). Fixed by tagging each
`SupervisedExample` with `target_report_date` and purging (embargoing) any training example whose
`target_report_date >= the decision date`. A dedicated regression test
(`test_walk_forward_purges_examples_whose_label_realizes_on_or_after_decision`) locks the behavior.

Still required before Phase 3 is complete: add scikit-learn / LightGBM training, monthly
walk-forward retraining, LightGBM artifact persistence, richer model diagnostics, and comparison
reports that decide whether the learned models beat the naive baseline robustly enough to feed
Phase 4.

## Phase 4 implementation notes

The first daily-inference slice is implemented:
- `predict-daily --price-artifact ... --spread-artifact ... [--as-of ...] [--load]` loads the
  latest point-in-time WTI feature row (`report_date <= as_of` and `knowledge_date <= as_of`,
  non-quarantined), scores both logistic heads, prints the call, and (with `--load`) writes a row
  to the `daily_predictions` table.
- Each prediction stores `price_up_probability`, `spread_up_probability`, a naive-persistence
  reference per head (sign of the latest 1-day move), both `*_model_version` stamps, and
  `*_top_drivers` (ranked linear log-odds contributions `weight * value / scale`).
- Point-in-time guards: inference refuses when `predicted_at` precedes the feature row's
  `knowledge_date`, and refuses swapped or horizon-mismatched model heads. Out-of-range
  probabilities are quarantined by the quality gate.

Model health / decay monitor (implemented):
- `model-health --commodity ... [--as-of ...] [--rolling-window N] [--report-dir ...]` scores
  persisted predictions against realized outcomes and reports model-vs-naive accuracy and Brier,
  overall, per regime, and over a trailing rolling window.
- Scoring is point-in-time: a prediction is only graded once the feature row `horizon` trading
  days later is available AND its `knowledge_date <= as_of`, so the monitor never credits an
  outcome that could not yet have been observed. Quarantined predictions are skipped.
- `model_minus_naive_accuracy` per head is the headline decay signal.

Streamlit dashboard (implemented):
- `uv run --extra dashboard streamlit run src/energy_etf_monitor/dashboard/app.py` renders Today's
  Call (per-head probability vs naive + driver tables), Price & Curve, Positioning (COT), Inventory,
  and Model Health.
- All data shaping lives in `dashboard/data.py` (pure, unit-tested); `app.py` is a thin rendering
  shell, so the dashboard logic is covered without a headless-browser test. `streamlit` is an
  optional `dashboard` extra, keeping the core install light.

LightGBM heads (implemented):
- `train-wti-gbm-artifact ...` trains a LightGBM head per target and saves it; `predict-daily`
  transparently loads either a logistic or a LightGBM artifact via `model_type` dispatch. Both
  backends share the `PredictionModel` interface, and LightGBM driver explanations use its
  `pred_contrib` (SHAP) values — the same log-odds-contribution framing as the logistic model.
- `lightgbm` is an optional `gbm` extra; the logistic baseline remains the always-available
  default and the backtest benchmark.

**Phase 4 is complete** — the MVP definition of done is met: a WTI loop producing price- and
spread-direction leans with confidence and top drivers, displayed against a naive baseline, with a
point-in-time model-health/decay monitor, all on dual-timestamp data. Next: Phase 5 (nightly
orchestration + alerting), then Phase 6 (Brent / NatGas / RBOB expansion).

## Phase 5 implementation notes

Orchestration runs on GitHub Actions (cloud cron) rather than a local scheduler:
- `run-nightly` chains ingest → feature build → predict (skipped if artifacts absent) → model
  health, propagating a non-zero exit on genuine failures so the scheduler can alert.
- `.github/workflows/nightly.yml` runs it weekdays at 22:00 UTC against a hosted Postgres, with an
  email alert on failure (`dawidd6/action-send-mail`). `.github/workflows/ci.yml` runs ruff + tests
  on push/PR.
- Committed model artifacts live in `models/` (not the gitignored `data/processed/`). Setup —
  secrets, hosted DB, SMTP, artifacts — is documented in
  [07-deployment.md](./07-deployment.md).

Still pending for Phase 5: an automated monthly retrain workflow (daily runs currently predict with
committed artifacts; retraining is manual).

## Phase 6 implementation notes

Multi-commodity expansion (WTI, NatGas, RBOB) on free CME + EIA data:
- `commodities.py` holds a `CommodityConfig` registry; the feature builder
  (`derive_feature_row(config, ...)`) and CFTC connector (`fetch_positions`) are now
  commodity-parameterized, with WTI wrappers kept for back-compat.
- `PhaseZeroIngestionRunner` takes a `commodities` set and ingests each one's COT (by contract
  code) and curve (by product code), folding each commodity's EIA inventory series into the fetch
  list. `ingest-phase0 --commodity ...` (default: all) and the nightly job ingest the full set.
- Generic CLI: `build-features`, `build-feature-range`, `export-feature-cache` all take
  `--commodity`; `predict-daily` and `model-health` already did. So a non-WTI commodity goes
  end-to-end: ingest → build → export cache → train artifacts → predict → health. The dashboard
  commodity selector is populated from the registry.

Caveats / still pending:
- COT contract-market codes for NatGas (023651) and RBOB (111659) are best-known values and should
  be verified against the CFTC API; a wrong code yields empty COT (soft failure), not a crash.
- Brent is ICE-listed and its curve is paywalled, so it is excluded from the registry until an ICE
  curve provider exists.
- Cross-commodity pooled model training (one model over all commodities, per the design) is not yet
  wired — each commodity currently trains its own per-cache artifacts.

## Phase 7: News Impact Monitor

Turn the current GDELT sentiment placeholder into a first-class monitoring-panel module that
answers: "what just happened, how important is it, and which way does it likely push energy
futures?"

Deliverables:
- **Connectors:** add idempotent GDELT 2.0 DOC API and Marketaux connectors, with optional RSS/API
  adapters for official sources such as EIA, OPEC, IEA, CME notices, exchange status pages, and
  major energy-news publishers. Save every raw payload to `data/raw/news/<date>/` before
  normalization.
- **Storage:** add `news_articles` and `news_impacts` tables with `published_at`, `fetched_at`,
  `knowledge_date`, `source`, `url_hash`, `title`, `summary`, `commodity`, `contract_family`,
  `catalyst_type`, `importance_score`, `impact_direction`, `confidence`, `rationale`, and
  `quarantine` fields.
- **Deduplication:** collapse syndicated articles and near-identical headlines by `url_hash`,
  canonical URL, source, title fingerprint, and publish-time window so the panel shows events, not
  repeated copies.
- **Relevance filters:** start with WTI, Brent, natural gas, RBOB, and heating oil; prioritize
  catalysts such as OPEC/OPEC+, EIA/API inventory, refinery outages, weather, LNG flows,
  geopolitics, sanctions, shipping disruptions, USD, rates, and recession/demand shocks.
- **Impact scoring:** label every retained article with importance (`High` / `Medium` / `Low` or
  0-100), direction (`Bullish` / `Bearish` / `Neutral` / `Mixed`), confidence, and a one-sentence
  explanation. Score outright price and roll/calendar-spread impact separately when the catalyst
  has different implications for flat price vs curve shape.
- **Dashboard:** add a "Latest Market-Moving News" lane to the monitoring panel, visible on
  Today's Calls above or beside the model cards. Each article row must show headline, source,
  publish time, affected commodity, catalyst type, importance badge, direction badge, confidence,
  short rationale, and source link. Filters: commodity, time window, importance, impact direction,
  source, and catalyst type.
- **Panel behavior:** sort by `importance_score`, then recency; pin high-importance items for the
  current trading session; mark stale items; show separate chips for `Price Impact` and
  `Spread Impact` when they differ.
- **Alerts:** send optional Slack / `ntfy.sh` alerts only for high-importance news with a clear
  direction and sufficient confidence.
- **Modeling boundary:** keep article-level news labels as display/explanation/alerting data first.
  Only promote aggregated features (article count, tone, direction-weighted importance) into the
  price/spread models after enough point-in-time history exists and walk-forward tests show value
  over the naive baseline.
- **Acceptance tests:** include fixture-based connector tests, deduplication tests, point-in-time
  `knowledge_date` tests, and classifier fixtures that verify importance/direction labels for known
  examples such as inventory surprises, OPEC supply changes, refinery outages, and geopolitical
  disruptions.

## What to defer (and why)

- **Brent / NatGas / RBOB / broad funds** — architecture is identical; mostly ticker configs +
  per-issuer PCF parsers. Add after the WTI loop is proven.
- **News-derived model features** — defer until the News Impact Monitor has enough point-in-time
  history to test honestly. The Phase 7 panel can still be useful before news becomes a model input.
- **MLflow** — start with a flat pickle + CSV prediction log; add the file-store once the loop is
  stable.
- **Hosted Postgres** — start with local Docker (or SQLite if Docker is friction).
- **European UCITS layer** — swap-based, holdings opaque; low payoff, secondary sentiment only.

## Per-issuer onboarding cost (a real risk, not "just a config")

USCF PCF file formats are issuer-specific and not standardized (CSV/XLS/PDF, differing layouts).
Each fund family's holdings/roll-detection parser must be built and tested individually. Budget for
this when expanding beyond WTI/`USO`.
