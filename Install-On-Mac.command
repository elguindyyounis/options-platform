#!/bin/bash
# Double-click once: installs the paper platform so it starts by itself at login, keeps itself up to date from GitHub,
# and opens the dashboard already connected. Paper only: no live trading exists. Needs Python 3.10+ and git.
cd "$(dirname "$0")" || exit 1
bash deploy/install_mac.sh
status=$?
[ $status -eq 0 ] || echo "The install stopped with an error. Read the message above."
read -r -p "Press Return to close."
