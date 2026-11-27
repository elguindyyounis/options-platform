#!/bin/bash
# Started by launchd (com.optionsplatform.server). Paper platform only: no live trading exists.
set -euo pipefail
umask 077
DATA="$HOME/Library/Application Support/OptionsPlatform"
APP="$HOME/Applications/OptionsPlatform"
# user-owned, chmod 600: OPTPLAT_API_TOKEN and optional switches. `set -a` exports every assignment, so a plain
# KEY=value line reaches the server exactly like an `export KEY=value` line (before 2026-11-28 only exported lines did).
if [ -f "$DATA/config.env" ]; then set -a; . "$DATA/config.env"; set +a; fi
export OPTPLAT_MANAGED=1
export OPTPLAT_DB="$DATA/optplat.db"
export OPTPLAT_DATA="${OPTPLAT_DATA:-yahoo}"
export OPTPLAT_ALLOW_UNVERIFIED_QUOTES="${OPTPLAT_ALLOW_UNVERIFIED_QUOTES:-1}"
export OPTPLAT_AUTOSTART_LOOP="${OPTPLAT_AUTOSTART_LOOP:-1}"
export OPTPLAT_SCAN_EVERY_S="${OPTPLAT_SCAN_EVERY_S:-1800}"
export OPTPLAT_SHORTTERM="${OPTPLAT_SHORTTERM:-1}" OPTPLAT_SWING="${OPTPLAT_SWING:-1}" OPTPLAT_OPTION_LANES="${OPTPLAT_OPTION_LANES:-1}"
export OPTPLAT_COMMITTEE="${OPTPLAT_COMMITTEE:-active}"
export PYTHONUNBUFFERED=1
export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
exec "$APP/.venv/bin/python" -m optplat
