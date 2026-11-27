#!/bin/bash
# Keeps the dashboard server running (launchd runs this every 5 minutes as com.optionsplatform.watchdog).
# Two failures it fixes on its own:
#   1. the server's LaunchAgent is not loaded at all (for example an install stopped half way after unloading it):
#      it loads it again from ~/Library/LaunchAgents.
#   2. the server is loaded but http://127.0.0.1:8800/api/health has not answered for about 30 seconds: it restarts it.
# It never edits the plist, the config or the database, and it does nothing while an update is running.
# To stop the server on purpose and keep it stopped, create the file "$DATA/server-paused"; delete it to resume.
set -uo pipefail
umask 077
DATA="${OPTPLAT_DATA_DIR:-$HOME/Library/Application Support/OptionsPlatform}"
AGENTS="${OPTPLAT_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LABEL="com.optionsplatform.server"
LAUNCHCTL="${OPTPLAT_LAUNCHCTL:-launchctl}"
CURL="${OPTPLAT_CURL:-curl}"
HEALTH="${OPTPLAT_HEALTH_URL:-http://127.0.0.1:8800/api/health}"
WAIT_S="${OPTPLAT_WATCHDOG_WAIT_S:-10}"
DOMAIN="gui/$(id -u)"
mkdir -p "$DATA"
LOG="$DATA/watchdog.log"
# keep the log short: only the newest 500 lines
if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 1000 ]; then tail -n 500 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
exec >>"$LOG" 2>&1
stamp() { date -u +%FT%TZ; }

if [ -e "$DATA/server-paused" ]; then exit 0; fi           # the owner stopped it on purpose
if [ -d "$DATA/update.lock" ]; then exit 0; fi             # an update is restarting it right now

if ! "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  if [ -f "$AGENTS/$LABEL.plist" ]; then
    if "$LAUNCHCTL" bootstrap "$DOMAIN" "$AGENTS/$LABEL.plist"; then echo "$(stamp) server was not loaded; loaded it again"
    else echo "$(stamp) server was not loaded and loading it failed"; fi
  else
    echo "$(stamp) server is not installed ($AGENTS/$LABEL.plist missing); run deploy/install_mac.sh"
  fi
  exit 0
fi

for _ in 1 2 3; do
  if "$CURL" -fs -m 5 -o /dev/null "$HEALTH"; then exit 0; fi
  sleep "$WAIT_S"
done
echo "$(stamp) server loaded but not answering $HEALTH for about $((3 * WAIT_S)) seconds; restarting it"
"$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" || echo "$(stamp) restart failed"
exit 0
