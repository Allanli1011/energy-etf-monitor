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

## Monthly retrain (automated)

`.github/workflows/monthly-retrain.yml` runs on the 1st of each month (and on demand). It rebuilds
each commodity's feature cache from the hosted DB, retrains the per-commodity and pooled logistic
heads via `energy-etf-monitor retrain`, and commits the refreshed `models/*.json` back to the repo
(`contents: write`, commit tagged `[skip ci]`). The daily job then predicts with the updated
artifacts. Failures email the same alert address.

## Optional secrets (news enrichment & alerts)

| Secret / setting | Purpose |
|---|---|
| `ENERGY_ETF_MONITOR_MARKETAUX_API_KEY` | Enable the Marketaux news source (free tier) |
| `ENERGY_ETF_MONITOR_ANTHROPIC_API_KEY` + `ENERGY_ETF_MONITOR_NEWS_CLASSIFIER=llm` | Use the LLM news classifier (`llm` extra); otherwise the free rule-based one is used |
| `ENERGY_ETF_MONITOR_ALERT_WEBHOOK_URL` + `..._ALERT_WEBHOOK_KIND` (`slack`/`ntfy`) | Post high-impact news alerts to Slack or ntfy |

All are optional — without them the pipeline runs on free GDELT + RSS news and the rule-based
classifier, and surfaces alerts in logs / the dashboard.

## Node runtime

The workflows set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` to opt the JavaScript actions onto
Node 24 ahead of GitHub's default switch; bump action majors when Node-24-native releases land.
