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
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

# GitHub's git-over-HTTPS expects HTTP basic auth (base64 of "x-access-token:<token>"); the
# bearer scheme is rejected and silently falls back to an interactive username prompt. This is
# the same header actions/checkout persists, so the token never appears in the push URL or logs.
auth_basic="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 | tr -d '\n')"
git -C "$tmpdir" \
  -c http.extraheader="AUTHORIZATION: basic ${auth_basic}" \
  push --force "https://github.com/${GITHUB_REPOSITORY}.git" \
  "$STATE_BRANCH:$STATE_BRANCH"

echo "Pushed $STATE_DB_PATH to $STATE_BRANCH."
