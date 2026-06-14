# models/

Trained model artifacts (committed JSON) consumed by the nightly GitHub Actions workflow.

This directory is intentionally tracked (unlike `data/processed/`, which is gitignored) so the
scheduled job can load models from a checkout. Train and commit artifacts with:

```bash
uv run energy-etf-monitor train-wti-logistic-artifact \
  --feature-cache data/processed/wti_daily_features.parquet \
  --target-name price_direction \
  --output-path models/wti_price_logistic.json

uv run energy-etf-monitor train-wti-logistic-artifact \
  --feature-cache data/processed/wti_daily_features.parquet \
  --target-name spread_direction \
  --output-path models/wti_spread_logistic.json
```

Until artifacts exist here, `run-nightly` ingests data and builds features but skips prediction
(the job stays green while history accumulates). LightGBM artifacts (`--extra gbm`,
`train-wti-gbm-artifact`) are loaded transparently by `model_type` when committed here instead.
