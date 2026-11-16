#!/bin/bash
# Managed updater for the Mac install (see docs/DEPLOYMENT.md). Only ever fast-forwards the `stable` branch,
# which GitHub Actions advances only after the tests pass. Takes no arguments. Safe to run repeatedly.
set -euo pipefail
umask 077
APP="${OPTPLAT_APP_DIR:-$HOME/Applications/OptionsPlatform}"
DATA="${OPTPLAT_DATA_DIR:-$HOME/Library/Application Support/OptionsPlatform}"
LABEL="com.optionsplatform.server"
LOG="$DATA/update.log"
mkdir -p "$DATA"
exec >>"$LOG" 2>&1
echo "== $(date -u +%FT%TZ) update check"
cd "$APP"
# one update at a time
LOCK="$DATA/update.lock"
if ! mkdir "$LOCK" 2>/dev/null; then echo "another update is running"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then echo "checkout has local changes; refusing to update"; exit 1; fi
OLD="$(git rev-parse HEAD)"
git fetch --quiet origin stable
NEW="$(git rev-parse origin/stable)"
if [ "$OLD" = "$NEW" ]; then echo "already on $OLD"; exit 0; fi
git merge-base --is-ancestor "$OLD" "$NEW" || { echo "stable is not a fast-forward of $OLD; refusing"; exit 1; }

# back up the paper database first (online-consistent copy)
if [ -f "$DATA/optplat.db" ]; then
  mkdir -p "$DATA/backups"
  "$APP/.venv/bin/python" - "$DATA/optplat.db" "$DATA/backups/optplat-$(date -u +%Y%m%dT%H%M%SZ).db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()
PY
fi

rollback() {
  echo "update failed; going back to $OLD"
  git reset --hard --quiet "$OLD"
  "$APP/.venv/bin/python" -m pip install --quiet -e . || true
}
git merge --ff-only --quiet "$NEW"
if ! "$APP/.venv/bin/python" -m pip install --quiet -e . || ! "$APP/.venv/bin/python" -m compileall -q src; then rollback; exit 1; fi
echo "updated $OLD -> $NEW; restarting"
launchctl kickstart -k "gui/$(id -u)/$LABEL" || echo "restart failed; launchd will start the new build on next login"
