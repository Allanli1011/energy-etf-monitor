#!/usr/bin/env bash
set -euo pipefail

STATE_BRANCH="${STATE_BRANCH:-state}"
STATE_DB_PATH="${STATE_DB_PATH:-data/state/energy_etf_monitor.sqlite}"

mkdir -p "$(dirname "$STATE_DB_PATH")"

if git fetch --no-tags --depth=1 origin "$STATE_BRANCH" >/dev/null 2>&1; then
  if git cat-file -e "FETCH_HEAD:$STATE_DB_PATH" 2>/dev/null; then
    git show "FETCH_HEAD:$STATE_DB_PATH" > "$STATE_DB_PATH"
    echo "Restored $STATE_DB_PATH from $STATE_BRANCH."
  else
    echo "State branch $STATE_BRANCH exists, but $STATE_DB_PATH was not found; starting fresh."
  fi
else
  echo "State branch $STATE_BRANCH does not exist yet; starting fresh."
fi
