"""Build id and the refresh-triggered update request. Paper research app: nothing here touches orders or risk.

The Mac runs a managed checkout of the ``stable`` branch (see docs/DEPLOYMENT.md). ``build_id`` is the commit of
that checkout. ``request_update`` starts ``deploy/update.sh`` in the background, but only when the server was
installed as managed (``OPTPLAT_MANAGED=1``), only once per ``MIN_INTERVAL_S``, and it takes no input from the caller:
no branch, commit or command can be chosen through the API."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
MIN_INTERVAL_S = 300
_last_request = 0.0


def build_id(root: Path = ROOT) -> str:
    """Short commit id of the running checkout, or "unknown" (not a git checkout, or git missing)."""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown" if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def request_update(root: Path = ROOT, now: Optional[float] = None, launch: Any = None) -> dict[str, Any]:
    """Ask the managed updater to check ``stable``. Returns a status; never raises."""
    global _last_request
    if os.environ.get("OPTPLAT_MANAGED") != "1":
        return {"status": "UNMANAGED", "queued": False}
    script = root / "deploy" / "update.sh"
    if not script.is_file():
        return {"status": "UNMANAGED_NO_UPDATER", "queued": False}
    t = time.monotonic() if now is None else now
    if _last_request and t - _last_request < MIN_INTERVAL_S:
        return {"status": "RECENT_CHECK_OR_IN_PROGRESS", "queued": False}
    _last_request = t
    try:
        (launch or _launch)(script)
    except OSError:
        return {"status": "UPDATER_LAUNCH_FAILED", "queued": False}
    return {"status": "QUEUED", "queued": True}


def _launch(script: Path) -> None:
    subprocess.Popen(["/bin/bash", str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
