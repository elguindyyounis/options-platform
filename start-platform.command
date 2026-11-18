#!/bin/bash
# Double-click (or run in Terminal) to start the paper platform and open its dashboard. Paper only: no live trading exists.
# The dashboard only exists while this window stays open. Close the window and http://127.0.0.1:8800 stops answering.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  echo "First run: creating a Python environment (a minute or two)..."
  python3 -m venv .venv || { echo "python3 was not found. Install Python 3.10 or newer, then run this again."; read -r -p "Press Return to close."; exit 1; }
  .venv/bin/pip install -q -e . || { echo "Install failed."; read -r -p "Press Return to close."; exit 1; }
fi
export OPTPLAT_OPEN_BROWSER=1
echo "Starting the platform. The page opens by itself; if it does not, use the address printed below."
.venv/bin/python -m optplat
echo "The platform stopped. See the message above."
read -r -p "Press Return to close."
