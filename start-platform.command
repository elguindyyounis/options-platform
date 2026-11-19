#!/bin/bash
# Double-click (or run in Terminal) to start the paper platform and open its dashboard. Paper only: no live trading exists.
# The dashboard only exists while this window stays open. Close the window and http://127.0.0.1:8800 stops answering.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  echo "First run: creating a Python environment (a minute or two)..."
  python3 -m venv .venv || { echo "python3 was not found. Install Python 3.10 or newer, then run this again."; read -r -p "Press Return to close."; exit 1; }
  .venv/bin/pip install -q -e . || { echo "Install failed."; read -r -p "Press Return to close."; exit 1; }
fi
# Keep one token between runs, so a browser that is already connected stays connected. Same file the managed install uses.
DATA="$HOME/Library/Application Support/OptionsPlatform"
mkdir -p "$DATA" && chmod 700 "$DATA"
if [ -z "${OPTPLAT_API_TOKEN:-}" ]; then
  [ -f "$DATA/config.env" ] || { umask 077; printf 'OPTPLAT_API_TOKEN=%s\n' "$(.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(32))')" >"$DATA/config.env"; }
  chmod 600 "$DATA/config.env"
  OPTPLAT_API_TOKEN="$(sed -n 's/^OPTPLAT_API_TOKEN=//p' "$DATA/config.env" | head -n1)"; export OPTPLAT_API_TOKEN
fi
export OPTPLAT_OPEN_BROWSER=1
echo "Starting the platform. The page opens by itself; if it does not, use the address printed below."
.venv/bin/python -m optplat
echo "The platform stopped. See the message above."
read -r -p "Press Return to close."
