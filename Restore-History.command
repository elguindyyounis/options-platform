#!/bin/bash
# Double-click. Pick your old paper database (optplat.db, or a .zip containing it) in the window that opens; it is copied into the
# installed platform, which then restarts. Your old file is not changed. Paper only: no live trading exists.
cd "$(dirname "$0")" || exit 1
APP="$HOME/Applications/OptionsPlatform"
DATA="$HOME/Library/Application Support/OptionsPlatform"
PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
[ -n "$PY" ] || { echo "Python was not found. Run Install-On-Mac.command first."; read -r -p "Press Return to close."; exit 1; }
PICK="$(osascript -e 'POSIX path of (choose file with prompt "Choose your old optplat.db (or a .zip containing it)")' 2>/dev/null)"
[ -n "$PICK" ] || { echo "No file chosen. Nothing changed."; read -r -p "Press Return to close."; exit 0; }
mkdir -p "$DATA"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
case "$PICK" in *.zip|*.ZIP) unzip -q -o "$PICK" -d "$WORK" || { echo "Could not unzip that file."; read -r -p "Press Return to close."; exit 1; }
                             SRC="$(find "$WORK" -name optplat.db -type f | head -n1)";; *) SRC="$PICK";; esac
[ -f "$SRC" ] || { echo "No optplat.db found in that choice. Nothing changed."; read -r -p "Press Return to close."; exit 1; }
launchctl bootout "gui/$(id -u)/com.optionsplatform.server" 2>/dev/null || true
"$PY" "$(dirname "$0")/deploy/restore_db.py" "$DATA" "$SRC"; status=$?
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.optionsplatform.server.plist" 2>/dev/null || true
if [ $status -eq 0 ]; then
  for _ in $(seq 1 30); do curl -fs -o /dev/null http://127.0.0.1:8800/api/health && break; sleep 1; done
  command -v open >/dev/null && open "http://127.0.0.1:8800/" || true
  echo "Done. The dashboard is opening."
else
  echo "Restore did not complete. Read the message above."
fi
read -r -p "Press Return to close."
