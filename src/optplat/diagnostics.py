"""Small helpers that make errors and clock problems visible instead of silent."""
from __future__ import annotations

import os
import traceback
from typing import Optional

CLOCK_WARN_S = 3.0  # warn well before the data-quality gate's 5 second limit starts rejecting snapshots


def describe_exc(exc: BaseException, limit: int = 160) -> str:
    """``AttributeError: message [file.py:123 in function]``, pointing at the innermost frame inside this package.
    Without this a failing chain read shows only the exception type and cannot be fixed from the dashboard."""
    where = ""
    here = os.path.dirname(os.path.abspath(__file__))
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if os.path.abspath(frame.filename).startswith(here):
            where = f" [{os.path.basename(frame.filename)}:{frame.lineno} in {frame.name}]"
            break
    return f"{type(exc).__name__}: {str(exc)[:limit]}{where}"


def clock_status(ahead_s: Optional[float], tolerance_s: float) -> dict[str, object]:
    """``ahead_s`` is how far the newest quote timestamp ran ahead of this computer's clock in the last cycle
    (positive means the computer's clock is behind). Display only: this never changes the gate's tolerance."""
    if ahead_s is None:
        return {"behind_s": None, "tolerance_s": tolerance_s, "warning": None}
    behind = max(0.0, float(ahead_s))
    warning = None
    if behind >= CLOCK_WARN_S:
        rejecting = behind > tolerance_s
        warning = (f"this computer's clock is about {behind:.0f}s behind the market data"
                   + (f", so snapshots are being rejected (limit {tolerance_s:.0f}s)" if rejecting else f", close to the {tolerance_s:.0f}s limit")
                   + ". Turn on System Settings > General > Date & Time > Set time and date automatically")
    return {"behind_s": round(behind, 1), "tolerance_s": tolerance_s, "warning": warning}
