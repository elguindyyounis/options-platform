#!/bin/bash
# One-time setup of the nightly paper-data export (run it once on the Mac; needs `gh auth login` first).
# Creates a PRIVATE GitHub repo (default: <you>/options-platform-data) if it does not exist, writes OPTPLAT_EXPORT_REPO
# into config.env, and runs one export now. Refuses to continue if the repo is not private. Never prints the token.
# The nightly job (com.optionsplatform.export, 21:15) is already installed by install_mac.sh and does the rest.
set -euo pipefail
umask 077
DATA="${OPTPLAT_DATA_DIR:-$HOME/Library/Application Support/OptionsPlatform}"
APP="${OPTPLAT_APP_DIR:-$HOME/Applications/OptionsPlatform}"
GH="${OPTPLAT_GH:-gh}"
export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
command -v "$GH" >/dev/null || { echo "Install the GitHub CLI first (brew install gh), then run: gh auth login"; exit 1; }
"$GH" auth status >/dev/null 2>&1 || { echo "Run: gh auth login   (then run this script again)"; exit 1; }
OWNER="$("$GH" api user --jq .login)"
SLUG="${1:-$OWNER/options-platform-data}"
if ! "$GH" repo view "$SLUG" >/dev/null 2>&1; then
  "$GH" repo create "$SLUG" --private --description "Private paper-trading data export (simulated, secret-free)" >/dev/null
  echo "Created private repo $SLUG"
fi
[ "$("$GH" repo view "$SLUG" --json isPrivate --jq .isPrivate)" = "true" ] || { echo "$SLUG is NOT private; refusing to continue"; exit 1; }
mkdir -p "$DATA"
touch "$DATA/config.env"; chmod 600 "$DATA/config.env"
if grep -q '^OPTPLAT_EXPORT_REPO=' "$DATA/config.env"; then
  echo "OPTPLAT_EXPORT_REPO already set in config.env; left as it is"
else
  printf 'OPTPLAT_EXPORT_REPO=https://github.com/%s.git\n' "$SLUG" >>"$DATA/config.env"
  echo "Added OPTPLAT_EXPORT_REPO to config.env"
fi
bash "$APP/deploy/export_push.sh" || true
echo "First export attempted. Details: $DATA/export.log"
echo "Last step (in Claude): give the scheduled task access to $SLUG."
