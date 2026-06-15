#!/usr/bin/env bash
set -euo pipefail

STATE_BRANCH="${STATE_BRANCH:-state}"
STATE_DB_PATH="${STATE_DB_PATH:-data/state/energy_etf_monitor.sqlite}"

mkdir -p "$(dirname "$STATE_DB_PATH")"

if git fetch --no-tags --depth=1 origin "$STATE_BRANCH" >/dev/null 2>&1; then
  if git cat-file -e "FETCH_HEAD:$STATE_DB_PATH" 2>/dev/null; then
    git show "FETCH_HEAD:$STATE_DB_PATH" > "$STATE_DB_PATH"
    # Refuse to start from an empty or corrupt restore: silently treating a 0-byte blob as
    # a fresh database would wipe accumulated history without anyone noticing.
    if [[ ! -s "$STATE_DB_PATH" ]]; then
      echo "ERROR: restored $STATE_DB_PATH is empty; refusing to continue." >&2
      rm -f "$STATE_DB_PATH"
      exit 1
    fi
    if command -v sqlite3 >/dev/null 2>&1; then
      if ! sqlite3 "$STATE_DB_PATH" "PRAGMA integrity_check;" | grep -qx "ok"; then
        echo "ERROR: restored $STATE_DB_PATH failed SQLite integrity check; refusing to continue." >&2
        rm -f "$STATE_DB_PATH"
        exit 1
      fi
    fi
    echo "Restored $STATE_DB_PATH from $STATE_BRANCH."
  else
    echo "State branch $STATE_BRANCH exists, but $STATE_DB_PATH was not found; starting fresh."
  fi
else
  echo "State branch $STATE_BRANCH does not exist yet; starting fresh."
fi
