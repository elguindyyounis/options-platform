"""Versioned research affordability screen; scenarios are not forecasts or probabilities."""
import math
from statistics import mean

VERSION = "movement-cost-v1"

def assess(spot, strike, right, bid, ask, iv, dte, closes, multiplier=100):
    out = {"version": VERSION, "eligible": False, "status": "INSUFFICIENT_EVIDENCE",
           "reasons": [], "assumptions": "Historical RMS daily returns; zero-rate/dividend European approximation, anchored to current midpoint; exit half-spread unchanged; 0.5% slippage and $0.65 each way. Scenarios are not forecasts. No proven edge."}
    def fail(reason):
        out["reasons"].append(reason)
        return out
    def valid(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    if not all(valid(x) for x in (spot, strike, bid, ask, iv, dte, multiplier)):
        return fail("Movement/cost screen unavailable: missing or invalid quote, IV, expiry or underlying.")
    if min(spot, strike, bid, ask, iv, multiplier) <= 0 or ask < bid or not 2 <= dte <= 730 or iv > 3 or right not in ("C", "P"):
        return fail("Movement/cost screen unavailable: invalid contract inputs.")
    prices = list(closes or ())[-61:]
    if len(prices) < 21 or not all(valid(x) and x > 0 for x in prices):
        return fail("At least 21 valid daily closes are required to assess movement against cost.")
    returns = [math.log(b/a) for a,b in zip(prices,prices[1:])]
    if any(abs(x) > .4 for x in returns):
        return fail("Discontinuous price history requires review before movement can be estimated.")
    days = min(10, max(1, int(dte * 5 / 14)))
    calendar_days = min(dte - 1, math.ceil(days * 7 / 5))
    move = math.sqrt(mean(x*x for x in returns) * days)
    if move > .35:
        return fail("Historical movement is too extreme for this approximation.")
    def price(s, vol, days_left):
        t = days_left / 365
        d1 = (math.log(s / strike) + .5 * vol * vol * t) / (vol * math.sqrt(t))
        d2 = d1 - vol * math.sqrt(t)
        n = lambda x: .5 * (1 + math.erf(x / math.sqrt(2)))
        return s*n(d1)-strike*n(d2) if right == "C" else strike*n(-d2)-s*n(-d1)
    base = price(spot, iv, dte)
    direction = 1 if right == "C" else -1
    target = spot * math.exp(direction * move)
    fee = 1.30 / multiplier
    def pnl(s, vol):
        # Anchored changes avoid treating discrepancies in theoretical value as arbitrage.
        exit_bid = max(0., bid + price(s, vol, dte-calendar_days) - base)
        return exit_bid * .995 - ask * 1.005 - fee
    gain = pnl(target, iv)
    stress = pnl(target, iv * .8)
    flat = pnl(spot, iv)
    adverse = pnl(spot * math.exp(-direction * move), iv)
    eligible = gain / ask >= .10 and stress >= 0
    out.update(status="SCREEN_PASS" if eligible else "COST_NOT_JUSTIFIED", eligible=eligible,
               holding_trading_days=days, elapsed_calendar_days=calendar_days,
               historical_observations=len(returns), scenario_move_pct=round(abs(target/spot-1)*100,3),
               target_underlying=round(target,4), premium_per_contract=round(ask*multiplier,2),
               favorable_net_return_pct=round(gain/ask*100,2), iv_down_net_return_pct=round(stress/ask*100,2),
               flat_net_return_pct=round(flat/ask*100,2), adverse_net_return_pct=round(adverse/ask*100,2))
    out["reasons"] = [f"{days}-session historical-movement scenario: {out['scenario_move_pct']}% toward {target:.2f}; entry premium ${ask*multiplier:.2f} per contract.",
                      f"After spread, time decay and assumed fees: favorable {gain/ask*100:+.1f}%, flat {flat/ask*100:+.1f}%, adverse {adverse/ask*100:+.1f}%; favorable with IV down 20%: {stress/ask*100:+.1f}%.",
                      "Passes the research cost screen; direction and liquidity still need validation." if eligible else "Observe only: requires at least 10% favorable net return and nonnegative return with IV down 20%."]
    return out
