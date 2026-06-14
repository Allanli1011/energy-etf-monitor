# 07 — Deployment (scheduled runs on GitHub Actions)

Phase 5 runs the nightly pipeline on GitHub Actions instead of a local scheduler, so it executes in
the cloud without your machine being on. Three workflows are in place:

- `.github/workflows/ci.yml` — lint + tests on every push to `main` and every PR.
- `.github/workflows/nightly.yml` — scheduled `run-nightly` (ingest -> features -> predict -> model
  health) on weekdays at 22:00 UTC, with an email alert on failure.
- `.github/workflows/monthly-retrain.yml` — scheduled retrain on the 1st of each month, committing
  refreshed `models/*.json` artifacts back to `main`.

## Persistent State

GitHub Actions runners are ephemeral, so the database must be restored before each run and saved
afterward. The default deployment uses a SQLite file at:

```text
data/state/energy_etf_monitor.sqlite
```

The workflows do this automatically:

1. Checkout `main`.
2. Restore the SQLite file from the dedicated `state` branch if it exists.
3. Run `init-db` and the pipeline command.
4. Force-push a new single-file `state` branch containing the latest SQLite file.

This avoids hosted database setup and avoids binary database history growth on `main`. The nightly
and monthly workflows share the `sqlite-state` concurrency group, so manual runs queue instead of
writing the database at the same time.

If you prefer a hosted database later, set `ENERGY_ETF_MONITOR_DATABASE_URL` to a
`postgresql+psycopg://...` URL and remove the state-branch restore/push steps from the workflows.

## Repository Secrets

Settings -> Secrets and variables -> Actions -> New repository secret:

| Secret | Purpose |
|---|---|
| `ENERGY_ETF_MONITOR_EIA_API_KEY` | EIA Open Data API key |
| `ENERGY_ETF_MONITOR_FRED_API_KEY` | FRED API key |
| `ENERGY_ETF_MONITOR_CFTC_APP_TOKEN` | Optional CFTC Socrata app token |
| `SMTP_SERVER`, `SMTP_PORT` | SMTP host/port for failure email, e.g. `smtp.gmail.com`, `465` |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP login; Gmail should use an App Password |
| `ALERT_EMAIL_TO` | Where failure alerts are sent |

No database secret is required for the default SQLite deployment. The built-in `GITHUB_TOKEN` is
used to push the `state` branch and monthly model commits.

## Model Artifacts

`run-nightly` skips prediction and stays green until model artifacts exist at
`models/wti_price_logistic.json` and `models/wti_spread_logistic.json`. Once enough history has
accumulated in the SQLite database, run the monthly retrain workflow manually from the Actions tab
or train locally and commit artifacts to `models/` (see [models/README.md](../models/README.md)).

## Email Alerts

The nightly and monthly workflows' final step runs only `if: failure()` and sends mail via
`dawidd6/action-send-mail`. For SMTP over SSL use port 465 with `secure: true`; for STARTTLS use
587 and set `secure: false` in the workflow. As a zero-config fallback, GitHub also emails the repo
owner on workflow failure when Actions email notifications are enabled in account settings.

## Schedule and Manual Runs

The nightly cron is `0 22 * * 1-5` (weekdays 22:00 UTC, after the US settlement window). The
monthly retrain cron is `0 6 1 * *` (06:00 UTC on the 1st of each month). Trigger either workflow
manually any time from the Actions tab via **Run workflow** (`workflow_dispatch`). GitHub may delay
scheduled runs under load and disables schedules on repos with no activity for 60 days.

## Optional Secrets (news enrichment & alerts)

| Secret / setting | Purpose |
|---|---|
| `ENERGY_ETF_MONITOR_MARKETAUX_API_KEY` | Enable the Marketaux news source |
| `ENERGY_ETF_MONITOR_ANTHROPIC_API_KEY` + `ENERGY_ETF_MONITOR_NEWS_CLASSIFIER=llm` | Use the LLM news classifier (`llm` extra); otherwise the free rule-based one is used |
| `ENERGY_ETF_MONITOR_ALERT_WEBHOOK_URL` + `..._ALERT_WEBHOOK_KIND` (`slack`/`ntfy`) | Post high-impact news alerts to Slack or ntfy |

All are optional. Without them the pipeline runs on free GDELT + RSS news and the rule-based
classifier, and surfaces alerts in logs / the dashboard.

## Node Runtime

The workflows set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` to opt the JavaScript actions onto
Node 24 ahead of GitHub's default switch; bump action majors when Node-24-native releases land.
