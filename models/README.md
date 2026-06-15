# models/

This directory is retained for legacy or experimental model artifacts only.

The current product path does **not** require committed model files. `run-nightly` now refreshes
data, official ETF holdings, news, and factor rows without loading `models/*.json`, running
prediction, or producing model-health reports.

Historical model CLI commands still exist for reference/backward compatibility, but they are not
called by GitHub Actions and are not part of the documented monitoring workflow.
