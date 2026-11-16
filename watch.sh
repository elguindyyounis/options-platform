#!/usr/bin/env bash
# Keeps the PAPER platform running and restarts it on the newest code from the branch you are on.
#
#   ./watch.sh                  same as ./run.sh yahoo --loop, plus automatic updates
#   ./watch.sh demo             fictional demo market
#   ./watch.sh yahoo --loop     any run.sh arguments are passed through
#
# Every minute it asks GitHub whether your branch has new commits. If it does, and your copy has no local changes, it
# fast-forwards to them (never a merge commit, never a force), stops the platform and starts it again. Then refresh
# the dashboard page. The simulated account is rebuilt from the database on start, so nothing is lost by a restart.
# The dashboard token is kept in .venv/.optplat_token so the open page stays connected across restarts.
#
#   OPTPLAT_UPDATE_SECONDS=60   how often to check for updates
#   OPTPLAT_WATCH_BRANCH=name   branch to follow (default: the branch you are on; you must be on it)
#
# Whatever is pushed to that branch runs on this computer. It is paper-only code, but nobody has reviewed it before it
# starts, so follow a branch you trust.
set -uo pipefail
cd "$(dirname "$0")"

case "${1:-}" in -h|--help) sed -n '2,19p' "$0"; exit 0 ;; esac
ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(yahoo --loop)
INTERVAL="${OPTPLAT_UPDATE_SECONDS:-60}"
CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
BRANCH="${OPTPLAT_WATCH_BRANCH:-$CURRENT}"
if [ -z "$BRANCH" ] || [ "$BRANCH" = "HEAD" ] || [ "$BRANCH" != "$CURRENT" ]; then
  echo "Check out the branch to follow first, for example:  git checkout agent/2026-11-13-reliability-and-ports"
  exit 2
fi

if [ -z "${OPTPLAT_API_TOKEN:-}" ]; then
  tokfile=".venv/.optplat_token"
  mkdir -p .venv
  if [ ! -s "$tokfile" ]; then
    ( umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > "$tokfile" )
  fi
  OPTPLAT_API_TOKEN="$(cat "$tokfile")"
fi
export OPTPLAT_API_TOKEN

PID=""
start() {
  if [ -n "${OPTPLAT_RUN_CMD:-}" ]; then bash -c "$OPTPLAT_RUN_CMD" & else ./run.sh "${ARGS[@]}" & fi
  PID=$!
  # The browser opens once, on the first start; later restarts keep the tab you already have.
  export OPTPLAT_OPEN_BROWSER=0
}
stop() {
  [ -z "$PID" ] && return
  pkill -TERM -P "$PID" 2>/dev/null || true
  kill -TERM "$PID" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  kill -KILL "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  PID=""
}
cleanup() { echo; echo "Stopping."; stop; exit 0; }
trap cleanup INT TERM

echo "Following origin/$BRANCH every ${INTERVAL}s. Press Ctrl+C to stop."
echo "Dashboard token, if the page asks for it: $OPTPLAT_API_TOKEN"
start
warned=""
while true; do
  sleep "$INTERVAL" & wait $!
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "The platform stopped on its own. Restarting in 5 seconds."
    sleep 5; start; continue
  fi
  git fetch -q origin "$BRANCH" 2>/dev/null || { echo "Could not reach GitHub; will try again."; continue; }
  remote="$(git rev-parse "origin/$BRANCH" 2>/dev/null || true)"
  [ -z "$remote" ] && continue
  [ "$remote" = "$(git rev-parse HEAD)" ] && continue
  if ! git merge-base --is-ancestor HEAD "$remote" 2>/dev/null; then
    [ "$warned" != "$remote" ] && echo "origin/$BRANCH has new commits but this copy has commits of its own, so it was not updated."
    warned="$remote"; continue
  fi
  if ! git diff --quiet || ! git diff --cached --quiet; then
    [ "$warned" != "$remote" ] && echo "origin/$BRANCH has new commits but this copy has uncommitted changes, so it was not updated."
    warned="$remote"; continue
  fi
  git merge --ff-only -q "$remote" || { echo "Update failed; leaving the running copy alone."; continue; }
  echo "Updated to: $(git log -1 --oneline). Restarting; refresh the dashboard page in a few seconds."
  stop; start
done
