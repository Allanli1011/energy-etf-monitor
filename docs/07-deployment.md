# 07 — Deployment (scheduled runs on GitHub Actions)

Phase 5 runs the nightly pipeline on GitHub Actions instead of a local scheduler, so it executes in
the cloud without your machine being on. Two workflows:

- `.github/workflows/ci.yml` — lint + tests on every push to `main` and every PR.
- `.github/workflows/nightly.yml` — scheduled `run-nightly` (ingest → features → predict → model
  health) on weekdays at 22:00 UTC, with an email alert on failure.

## Prerequisites

### 1. A hosted Postgres (state must persist across runs)

GitHub Actions runners are ephemeral, so the database cannot live on the runner. Use a free hosted
Postgres (Supabase or Neon) and put its connection string in a secret. Use the `postgresql+psycopg`
driver prefix, e.g.:

```
postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
```

### 2. Repository secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Purpose |
|---|---|
| `ENERGY_ETF_MONITOR_DATABASE_URL` | Hosted Postgres connection string |
| `ENERGY_ETF_MONITOR_EIA_API_KEY` | EIA Open Data API key |
| `ENERGY_ETF_MONITOR_FRED_API_KEY` | FRED API key |
| `ENERGY_ETF_MONITOR_CFTC_APP_TOKEN` | (optional) CFTC Socrata app token |
| `SMTP_SERVER`, `SMTP_PORT` | SMTP host/port for failure email (e.g. `smtp.gmail.com`, `465`) |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP login (Gmail: use an App Password, not your account password) |
| `ALERT_EMAIL_TO` | Where failure alerts are sent |

The app reads its config from `ENERGY_ETF_MONITOR_`-prefixed environment variables, which the
nightly workflow maps from the secrets above.

### 3. Model artifacts (optional at first)

`run-nightly` skips prediction (and stays green) until model artifacts exist at
`models/wti_price_logistic.json` and `models/wti_spread_logistic.json`. Once enough history has
accumulated in the hosted DB, build a feature cache, train both heads, and commit the artifacts to
`models/` (see [models/README.md](../models/README.md)). LightGBM artifacts are loaded
transparently by `model_type` if committed instead.

## Email alerts

The nightly workflow's final step runs only `if: failure()` and sends mail via
`dawidd6/action-send-mail`. For SMTP over SSL use port 465 with `secure: true`; for STARTTLS use 587
and set `secure: false` in the workflow. As a zero-config fallback, GitHub also emails the repo
owner on workflow failure when Actions email notifications are enabled in account settings.

## Schedule and manual runs

The cron is `0 22 * * 1-5` (weekdays 22:00 UTC, after the US settlement window). Trigger a run
manually any time from the Actions tab via **Run workflow** (`workflow_dispatch`). Note that GitHub
may delay scheduled runs under load and disables schedules on repos with no activity for 60 days.

## Monthly retrain (manual for now)

Daily runs predict with the committed artifacts; retraining is not yet automated. Periodically
rebuild the feature cache and retrain the heads (purged walk-forward governs evaluation), then
commit the refreshed artifacts. A scheduled monthly retrain workflow is a natural follow-up.
