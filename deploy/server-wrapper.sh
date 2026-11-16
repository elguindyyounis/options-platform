#!/bin/bash
# Started by launchd (com.optionsplatform.server). Paper platform only: no live trading exists.
set -euo pipefail
umask 077
DATA="$HOME/Library/Application Support/OptionsPlatform"
APP="$HOME/Applications/OptionsPlatform"
[ -f "$DATA/config.env" ] && . "$DATA/config.env"   # user-owned, chmod 600: OPTPLAT_API_TOKEN and optional switches
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
