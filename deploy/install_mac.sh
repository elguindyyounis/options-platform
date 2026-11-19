#!/bin/bash
# One-time setup of the managed Mac install: a checkout of `stable`, a venv, and two LaunchAgents
# (the server, and an hourly update check). Re-running it is safe. Needs python 3.10+, git, and git access to the repo.
#   bash deploy/install_mac.sh [repo-url]
set -euo pipefail
REPO="${1:-https://github.com/elguindyyounis/options-platform.git}"
APP="$HOME/Applications/OptionsPlatform"
DATA="$HOME/Library/Application Support/OptionsPlatform"
AGENTS="$HOME/Library/LaunchAgents"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3.10 or newer is required."; exit 1; }
mkdir -p "$DATA" "$AGENTS" "$(dirname "$APP")"; chmod 700 "$DATA"
if [ -d "$APP/.git" ]; then git -C "$APP" fetch --quiet origin stable && git -C "$APP" merge --ff-only --quiet origin/stable
else git clone --quiet --branch stable "$REPO" "$APP"; fi
[ -d "$APP/.venv" ] || "$PY" -m venv "$APP/.venv"
"$APP/.venv/bin/python" -m pip install --quiet --upgrade pip
"$APP/.venv/bin/python" -m pip install --quiet -e "$APP[yahoo]"
if [ ! -f "$DATA/config.env" ]; then
  umask 077; printf 'OPTPLAT_API_TOKEN=%s\n' "$("$APP/.venv/bin/python" -c 'import secrets;print(secrets.token_urlsafe(32))')" >"$DATA/config.env"
fi
chmod 600 "$DATA/config.env"
write_plist() {  # label, then the program arguments, then extra keys
  local label="$1"; shift; local extra="$1"; shift
  { echo '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict>'
    echo "<key>Label</key><string>$label</string><key>ProgramArguments</key><array>"
    for a in "$@"; do echo "<string>$a</string>"; done
    echo "</array>$extra<key>RunAtLoad</key><true/><key>StandardOutPath</key><string>$DATA/$label.log</string><key>StandardErrorPath</key><string>$DATA/$label.log</string></dict></plist>"; } >"$AGENTS/$label.plist"
}
write_plist com.optionsplatform.server '<key>KeepAlive</key><true/>' /bin/bash "$APP/deploy/server-wrapper.sh"
write_plist com.optionsplatform.autoupdate '<key>StartInterval</key><integer>3600</integer>' /bin/bash "$APP/deploy/update.sh"
write_plist com.optionsplatform.export '<key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>15</integer></dict>' /bin/bash "$APP/deploy/export_push.sh"
for l in com.optionsplatform.server com.optionsplatform.autoupdate com.optionsplatform.export; do
  launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$l.plist"
done
echo "Installed. Dashboard: http://127.0.0.1:8800  (token is in: $DATA/config.env)"
# One-click link that carries the token in the URL fragment (never sent to the server). Opening it once connects that browser for good.
TOKEN="$(sed -n 's/^OPTPLAT_API_TOKEN=//p' "$DATA/config.env" | head -n1)"
if printf '%s' "$TOKEN" | grep -Eq '^[A-Za-z0-9_-]{16,200}$'; then
  LINK="$HOME/Applications/Open Options Dashboard.webloc"
  umask 077
  printf '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>URL</key><string>http://127.0.0.1:8800/#token=%s</string></dict></plist>\n' "$TOKEN" >"$LINK"
  echo "Double-click 'Open Options Dashboard' in $(dirname "$APP") to connect any browser. It is already opening now."
  for _ in $(seq 1 30); do curl -fs -o /dev/null http://127.0.0.1:8800/api/health && break; sleep 1; done
  command -v open >/dev/null && open "http://127.0.0.1:8800/#token=$TOKEN" || true
fi
