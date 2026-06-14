#!/usr/bin/env bash
set -euo pipefail

STATE_BRANCH="${STATE_BRANCH:-state}"
STATE_DB_PATH="${STATE_DB_PATH:-data/state/energy_etf_monitor.sqlite}"

if [[ ! -f "$STATE_DB_PATH" ]]; then
  echo "No SQLite database at $STATE_DB_PATH; nothing to push."
  exit 0
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

mkdir -p "$tmpdir/$(dirname "$STATE_DB_PATH")"
cp "$STATE_DB_PATH" "$tmpdir/$STATE_DB_PATH"

git -C "$tmpdir" init --initial-branch="$STATE_BRANCH"
git -C "$tmpdir" config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git -C "$tmpdir" config user.email "${GIT_AUTHOR_EMAIL:-github-actions[bot]@users.noreply.github.com}"
git -C "$tmpdir" add "$STATE_DB_PATH"
git -C "$tmpdir" commit -m "chore: update sqlite state [skip ci]"
git -C "$tmpdir" \
  -c http.extraheader="AUTHORIZATION: bearer ${GITHUB_TOKEN:?GITHUB_TOKEN is required}" \
  push --force "https://github.com/${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}.git" \
  "$STATE_BRANCH:$STATE_BRANCH"

echo "Pushed $STATE_DB_PATH to $STATE_BRANCH."
