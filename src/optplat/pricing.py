"""Limit-price helpers. Both stay inside the risk policy's allowed distance from the quote."""
from __future__ import annotations

import math


def buy_limit_for(ask: float) -> float:
    """Ask plus 1%, rounded DOWN to a cent so it can never exceed the policy's 1% ceiling."""
    return max(0.01, math.floor(ask * 1.01 * 100 + 1e-9) / 100)


def sell_limit_for(bid: float) -> float:
    """Bid minus 1%, rounded UP to a cent so it can never undercut the policy's 3% floor."""
    return max(0.01, math.ceil(bid * 0.99 * 100 - 1e-9) / 100)
