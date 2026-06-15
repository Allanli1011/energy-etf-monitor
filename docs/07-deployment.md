# 07 - Deployment

Deployment is a scheduled **monitoring** workflow on GitHub Actions. It refreshes data and reports;
it does not train or run prediction models.

## Workflows

- `.github/workflows/ci.yml`: lint + tests on push, pull request, and manual dispatch.
- `.github/workflows/nightly.yml`: scheduled weekday monitoring run at 22:00 UTC.
- `.github/workflows/backfill.yml`: manual source/factor backfill, no model training.
- `.github/workflows/pages.yml`: builds and deploys the static dashboard to GitHub Pages.

The old monthly retrain workflow has been removed.

## Nightly Flow

`run-nightly` performs:

1. EIA/FRED/CFTC/futures ingestion.
2. Official ETF holdings and NAV/share ingestion from USCF, Invesco, and ProShares.
3. Fallback Yahoo ETF metric context ingestion where configured.
4. News ingestion and optional alerts.
5. Point-in-time factor-row construction.

It does not require `models/*.json`, `gbm`, or model artifact secrets.

## Persistent State

GitHub Actions runners are ephemeral. The default deployment persists SQLite on a dedicated
`state` branch:

```text
data/state/energy_etf_monitor.sqlite
```

Each scheduled/manual workflow:

1. checks out `main`;
2. restores the SQLite file from `state` if present;
3. runs `init-db`;
4. runs the monitoring or backfill command;
5. force-pushes the refreshed SQLite file back to `state`.

The `sqlite-state` concurrency group prevents concurrent jobs from writing state at the same time.

## Required Secrets

| Secret | Purpose |
|---|---|
| `ENERGY_ETF_MONITOR_EIA_API_KEY` | EIA Open Data API key |
| `ENERGY_ETF_MONITOR_FRED_API_KEY` | FRED API key |
| `ENERGY_ETF_MONITOR_CFTC_APP_TOKEN` | Optional CFTC Socrata app token |
| `SMTP_SERVER`, `SMTP_PORT` | SMTP host/port for failure email |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP login |
| `ALERT_EMAIL_TO` | Failure-alert recipient |

No database secret is required for the default SQLite deployment. The built-in `GITHUB_TOKEN` is
used to push the `state` branch.

## Optional News/Alert Secrets

| Secret / setting | Purpose |
|---|---|
| `ENERGY_ETF_MONITOR_MARKETAUX_API_KEY` | Enable Marketaux news source |
| `ENERGY_ETF_MONITOR_ANTHROPIC_API_KEY` + `ENERGY_ETF_MONITOR_NEWS_CLASSIFIER=llm` | Enable optional LLM classifier |
| `ENERGY_ETF_MONITOR_ALERT_WEBHOOK_URL` + `ENERGY_ETF_MONITOR_ALERT_WEBHOOK_KIND` | Post high-impact news alerts to Slack or ntfy |

Without optional secrets the pipeline still runs on EIA/FRED/CFTC/USCF/Invesco/ProShares/Yahoo
fallback/GDELT/RSS and the rule-based classifier.

## Manual Backfill

Use `.github/workflows/backfill.yml` from the Actions tab to rebuild source/factor history. It:

- restores state;
- refreshes official ETF snapshots and any configured fallback ETF metrics;
- ingests each commodity's phase-0 sources;
- backfills historical curve rows;
- builds factor rows and exports temporary Parquet caches;
- pushes only the SQLite state branch.

It intentionally does not commit model artifacts.

## Pages

`pages.yml` rebuilds the static HTML report after pushes, successful nightly runs, successful
backfills, or manual dispatch. It restores SQLite state first, then runs:

```bash
uv run energy-etf-monitor init-db
uv run energy-etf-monitor render-report --output-dir site
```

## Node Runtime

The workflows set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` to opt JavaScript actions onto Node 24.
