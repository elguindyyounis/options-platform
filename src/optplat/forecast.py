"""Candle forecasts from Kronos, as an optional research input. Paper only, and off until ``./install-kronos.sh`` has been run (or ``OPTPLAT_KRONOS=1`` is set; ``0`` forces it off).

Kronos is a pretrained model that continues a series of daily candles. This module does three things and no more:
it asks the model for the next few candles, writes every forecast to a journal before the outcome is known, and later
scores each one against what happened, next to the plain "nothing changes" guess. A lane may trade on the forecast
(``kronos-options-swing``), but no limit, exit rule or order path in the main account reads anything from here.

The model is a third-party download, so it is never imported unless asked for, and it is not a hard dependency: install
it with ``./install-kronos.sh``. With it missing, the lane says so and does nothing.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from .marketdata import Bar

HORIZON = 3                  # trading days ahead that a forecast is scored at
CONTEXT_BARS = 400           # most candles shown to the model (Kronos-small reads at most 512)
MIN_CONTEXT = 120            # fewer candles than this and no forecast is made
MIN_RESOLVED = 20            # scored forecasts needed before the scorecard gives a verdict
CALL_MOVE_PCT = 1.0          # the lane acts on a forecast of at least this move in the 3-day close
DEFAULT_MODEL, DEFAULT_TOKENIZER = "NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"


@dataclass(frozen=True)
class Forecast:
    symbol: str
    bar_day: str            # the last candle the model was shown
    model: str
    horizon: int
    made_at: str
    last_close: float
    pred_close: float       # forecast close at ``horizon`` trading days
    pred_high: float        # highest forecast high over the horizon
    pred_low: float         # lowest forecast low over the horizon

    @property
    def move_pct(self) -> float:
        return (self.pred_close / self.last_close - 1) * 100

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "move_pct": round(self.move_pct, 2)}


class Forecaster(Protocol):
    name: str

    def status(self) -> tuple[bool, str]: ...
    def predict(self, symbol: str, bars: Sequence[Bar], horizon: int, now: datetime) -> Optional[Forecast]: ...


def future_days(last: date, n: int) -> list[date]:
    """The next ``n`` weekdays after ``last``. Exchange holidays are not modelled: the model only uses them as calendar features."""
    out, d = [], last
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def has_candles(bars: Sequence[Bar]) -> list[Bar]:
    return [b for b in bars if b.open_ is not None and b.high is not None and b.low is not None]


class KronosForecaster:
    """Loads Kronos lazily from a local clone (see ``install-kronos.sh``). Anything missing is reported by ``status``, not raised."""

    def __init__(self, path: Optional[str] = None, model: Optional[str] = None, tokenizer: Optional[str] = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.path = Path(path or os.environ.get("OPTPLAT_KRONOS_PATH") or root / ".venv" / "kronos")
        self.model_name = model or os.environ.get("OPTPLAT_KRONOS_MODEL", DEFAULT_MODEL)
        self.tokenizer_name = tokenizer or os.environ.get("OPTPLAT_KRONOS_TOKENIZER", DEFAULT_TOKENIZER)
        self.name = self.model_name.rsplit("/", 1)[-1].lower()
        self._predictor: Any = None
        self._error = ""

    def status(self) -> tuple[bool, str]:
        if self._predictor is not None:
            return True, "loaded"
        if not (self.path / "model" / "kronos.py").exists():
            return False, f"Kronos is not installed (no clone at {self.path}). Run ./install-kronos.sh"
        if self._error:
            return False, self._error
        return True, "installed, not loaded yet"

    def _load(self) -> Any:
        if self._predictor is None:
            try:
                sys.path.insert(0, str(self.path))
                from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore[import-not-found]  # noqa: PLC0415

                self._predictor = KronosPredictor(Kronos.from_pretrained(self.model_name), KronosTokenizer.from_pretrained(self.tokenizer_name), max_context=512)
            except Exception as exc:  # noqa: BLE001 - a missing or broken model must never reach the engine
                self._error = f"Kronos could not be loaded: {type(exc).__name__}: {str(exc)[:160]}"
                raise
        return self._predictor

    def predict(self, symbol: str, bars: Sequence[Bar], horizon: int, now: datetime) -> Optional[Forecast]:
        candles = has_candles(bars)[-CONTEXT_BARS:]
        if len(candles) < MIN_CONTEXT:
            return None
        import pandas as pd  # noqa: PLC0415 - installed with Kronos, not a dependency of the platform

        frame = pd.DataFrame({"open": [b.open_ for b in candles], "high": [b.high for b in candles], "low": [b.low for b in candles],
                              "close": [b.close for b in candles], "volume": [b.volume for b in candles]})
        x_ts = pd.Series(pd.to_datetime([b.day for b in candles]))
        y_ts = pd.Series(pd.to_datetime(future_days(candles[-1].day, horizon)))
        out = self._load().predict(df=frame, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=horizon, T=1.0, top_p=0.9, sample_count=1, verbose=False)
        return make_forecast(symbol, candles[-1], self.name, horizon, now, float(out["close"].iloc[-1]), float(out["high"].max()), float(out["low"].min()))


def make_forecast(symbol: str, last: Bar, model: str, horizon: int, now: datetime, close: float, high: float, low: float) -> Optional[Forecast]:
    """A forecast, or None when the numbers are not finite and sensible (a model can emit nonsense; the journal must not hold it)."""
    if not all(math.isfinite(x) and x > 0 for x in (close, high, low)) or low > high or not (low <= close <= high):
        return None
    return Forecast(symbol, last.day.isoformat(), model, horizon, now.isoformat(), last.close, close, high, low)


def from_env() -> Optional[Forecaster]:
    """On when asked for (OPTPLAT_KRONOS=1) or, if unset, when ./install-kronos.sh has put the model in place. OPTPLAT_KRONOS=0 forces it off."""
    flag = os.environ.get("OPTPLAT_KRONOS", "")
    if flag == "0":
        return None
    k = KronosForecaster()
    return k if flag == "1" or (k.path / "model" / "kronos.py").exists() else None


# ---------------------------------------------------------------- the scorecard
def resolve(store: Any, bars_by_symbol: dict[str, Sequence[Bar]], fictional: bool) -> int:
    """Fill in what actually happened for forecasts whose horizon has passed. Returns how many were scored."""
    done = 0
    for f in store.forecasts(fictional, unresolved_only=True):
        days = [b.day.isoformat() for b in bars_by_symbol.get(f["symbol"], [])]
        if f["bar_day"] not in days:
            continue
        i = days.index(f["bar_day"]) + f["horizon"]
        if i < len(days):
            store.resolve_forecast(f["id"], bars_by_symbol[f["symbol"]][i].close, days[i])
            done += 1
    return done


def scorecard(store: Any, fictional: bool, model: Optional[str] = None) -> dict[str, Any]:
    rows = [f for f in store.forecasts(fictional) if model is None or f["model"] == model]
    done = [f for f in rows if f["realized_close"] is not None]
    n = len(done)
    out: dict[str, Any] = {"fictional": fictional, "logged": len(rows), "scored": n, "min_scored": MIN_RESOLVED, "horizon": HORIZON,
                           "models": sorted({f["model"] for f in rows}), "recent": [], "verdict": "none", "headline": "", "note": (
        "Each forecast is logged before the outcome is known and scored at the horizon. 'No change' means guessing the last close. "
        "Forecasts a day apart and on different names overlap and move together, so the real sample is smaller than the count. "
        "A good score on a few weeks proves nothing about later weeks.")}
    for f in rows[:12]:
        move = (f["pred_close"] / f["last_close"] - 1) * 100
        real = None if f["realized_close"] is None else (f["realized_close"] / f["last_close"] - 1) * 100
        out["recent"].append({"symbol": f["symbol"], "bar_day": f["bar_day"], "predicted_move_pct": round(move, 2),
                              "realized_move_pct": None if real is None else round(real, 2),
                              "right_way": None if real is None else (move > 0) == (real > 0)})
    if not n:
        out["headline"] = "Nothing has been scored yet." if rows else "No forecasts have been made yet."
        return out
    hit = sum(1 for f in done if (f["pred_close"] > f["last_close"]) == (f["realized_close"] > f["last_close"])) / n * 100
    up = sum(1 for f in done if f["realized_close"] > f["last_close"]) / n * 100
    mae_model = sum(abs(f["pred_close"] / f["realized_close"] - 1) for f in done) / n * 100
    mae_naive = sum(abs(f["last_close"] / f["realized_close"] - 1) for f in done) / n * 100
    out.update({"direction_hit_pct": round(hit, 1), "always_up_hit_pct": round(max(up, 100 - up), 1), "mae_pct": round(mae_model, 2),
                "mae_no_change_pct": round(mae_naive, 2)})
    if n < MIN_RESOLVED:
        out["verdict"], out["headline"] = "too_few", f"Only {n} scored so far. A verdict needs {MIN_RESOLVED}."
        return out
    margin = 100 / math.sqrt(n)         # roughly two standard errors of a coin flip
    right_way = hit > max(up, 100 - up) + margin
    closer = mae_model < mae_naive
    if right_way and closer:
        out["verdict"], out["headline"] = "ahead", "Ahead of guessing 'no change' on this sample. Not proof."
    elif closer or right_way:
        out["verdict"], out["headline"] = "mixed", "Better on one measure only."
    else:
        out["verdict"], out["headline"] = "behind", "Not better than guessing 'no change'."
    return out
