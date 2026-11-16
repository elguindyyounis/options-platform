#!/bin/bash
# Nightly: export the paper database (secret-free, see src/optplat/export.py) and push it to a PRIVATE repository
# so the research agents can read real results. Fails closed: if the destination is not confirmed private, nothing is pushed.
# Set OPTPLAT_EXPORT_REPO (for example https://github.com/<you>/options-platform-data.git) in config.env to turn it on.
set -euo pipefail
umask 077
APP="${OPTPLAT_APP_DIR:-$HOME/Applications/OptionsPlatform}"
DATA="${OPTPLAT_DATA_DIR:-$HOME/Library/Application Support/OptionsPlatform}"
export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
[ -f "$DATA/config.env" ] && . "$DATA/config.env"
LOG="$DATA/export.log"
exec >>"$LOG" 2>&1
echo "== $(date -u +%FT%TZ) export"
REPO="${OPTPLAT_EXPORT_REPO:-}"
if [ -z "$REPO" ]; then echo "OPTPLAT_EXPORT_REPO is not set; nothing to do"; exit 0; fi
command -v gh >/dev/null || { echo "gh is not installed, so privacy cannot be confirmed; not pushing"; exit 1; }
SLUG="$(printf '%s' "$REPO" | sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##')"
PRIVATE="$(gh repo view "$SLUG" --json isPrivate --jq .isPrivate 2>/dev/null || echo unknown)"
if [ "$PRIVATE" != "true" ]; then echo "repository $SLUG is not confirmed private ($PRIVATE); not pushing"; exit 1; fi
WORK="$DATA/export-repo"
if [ ! -d "$WORK/.git" ]; then git clone --quiet "$REPO" "$WORK"; fi
git -C "$WORK" pull --quiet --ff-only || true
mkdir -p "$WORK/export"
"$APP/.venv/bin/python" -m optplat.export --db "$DATA/optplat.db" --out "$WORK/export"
git -C "$WORK" add -A export
if git -C "$WORK" diff --cached --quiet; then echo "no changes"; exit 0; fi
git -C "$WORK" -c user.name="optplat-export" -c user.email="optplat-export@users.noreply.github.com" commit --quiet -m "Paper data export $(date -u +%F)"
git -C "$WORK" push --quiet origin HEAD
echo "pushed"
