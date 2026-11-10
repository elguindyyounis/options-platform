#!/usr/bin/env bash
# One-command start for the PAPER trading platform. No live trading exists in this repo.
#
#   ./run.sh                 fictional demo market (works at any hour)
#   ./run.sh yahoo           free, delayed, unofficial Yahoo data (needs US market hours)
#   ./run.sh yahoo --loop    same, and start the cycle loop automatically
#
# Sets up Python, installs what is needed, starts the server and opens the dashboard already connected.
set -euo pipefail
cd "$(dirname "$0")"

mode="demo"
loop=0
for arg in "$@"; do
  case "$arg" in
    demo|yahoo) mode="$arg" ;;
    --loop) loop=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg   (try ./run.sh --help)"; exit 2 ;;
  esac
done

PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer was not found."
  echo "Install it from https://www.python.org/downloads/ (or: brew install python@3.12), then run ./run.sh again."
  echo "Note: the python3 that comes with Apple's command line tools is too old (3.9)."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating .venv with $("$PY" --version) ..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

extras=""
[ "$mode" = "yahoo" ] && extras="[yahoo]"
stamp=".venv/.installed-${mode}-$(cksum < pyproject.toml | cut -d' ' -f1)"
if [ ! -f "$stamp" ]; then
  echo "Installing dependencies (first run takes a minute or two) ..."
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -e ".${extras}"
  touch "$stamp"
fi

export OPTPLAT_DATA="$mode"
export OPTPLAT_OPEN_BROWSER=1
[ "$loop" = "1" ] && export OPTPLAT_AUTOSTART_LOOP=1
if [ "$mode" = "yahoo" ]; then
  # Yahoo quotes carry no exchange timestamp, so the risk gate rejects them unless this is set. Typing "yahoo"
  # is the explicit opt-in; the platform prints a warning for it.
  export OPTPLAT_ALLOW_UNVERIFIED_QUOTES=1
fi

exec python -m optplat
