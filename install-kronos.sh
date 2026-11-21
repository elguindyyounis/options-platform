#!/usr/bin/env bash
# Optional: installs the Kronos candle-forecast model so the "Kronos forecast options" lane can run. PAPER research only.
#
#   ./install-kronos.sh
#
# What it does: clones github.com/shiyu-coder/Kronos (pinned to a reviewed commit) into .venv/kronos, installs PyTorch and a few
# small packages into .venv, downloads the small open model from Hugging Face (no account needed), and runs one test forecast.
# Nothing here touches your orders, limits or database. Remove it any time with: rm -rf .venv/kronos
set -euo pipefail
cd "$(dirname "$0")"

PIN="67b630e67f6a18c9e9be918d9b4337c960db1e9a"   # the commit that was read before this was added; change it only after reading the new code
REPO="https://github.com/shiyu-coder/Kronos"
DIR=".venv/kronos"

if [ ! -d .venv ]; then
  echo "There is no .venv yet. Run ./run.sh once first (it creates it), stop it with Ctrl-C, then run this again."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -d "$DIR/.git" ]; then
  echo "Cloning Kronos ..."
  git clone --quiet "$REPO" "$DIR"
fi
git -C "$DIR" fetch --quiet origin
git -C "$DIR" checkout --quiet "$PIN"
echo "Kronos source pinned at $(git -C "$DIR" rev-parse --short HEAD)."

echo "Installing PyTorch and helpers into .venv (a few hundred MB, takes a minute or two) ..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet torch numpy pandas einops huggingface_hub safetensors tqdm

echo "Downloading the model and running one test forecast (first run downloads about 100 MB) ..."
OPTPLAT_KRONOS_DIR="$DIR" python - <<'PY'
import math, os, random, sys
from datetime import date, timedelta
sys.path.insert(0, os.environ["OPTPLAT_KRONOS_DIR"])
import pandas as pd
from model import Kronos, KronosPredictor, KronosTokenizer

tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
predictor = KronosPredictor(model, tok, max_context=512)

rng, price, rows, d = random.Random(1), 100.0, [], date(2025, 1, 1)
while len(rows) < 200:
    d += timedelta(days=1)
    if d.weekday() >= 5:
        continue
    o = price
    price *= math.exp(rng.gauss(0, 0.01))
    rows.append((d, o, max(o, price) * 1.003, min(o, price) * 0.997, price, 1e6))
frame = pd.DataFrame(rows, columns=["day", "open", "high", "low", "close", "volume"])
future = pd.Series(pd.to_datetime([rows[-1][0] + timedelta(days=i) for i in (1, 4, 5)]))
out = predictor.predict(df=frame[["open", "high", "low", "close", "volume"]], x_timestamp=pd.Series(pd.to_datetime(frame["day"])),
                        y_timestamp=future, pred_len=3, T=1.0, top_p=0.9, sample_count=1, verbose=False)
assert len(out) == 3 and out["close"].notna().all()
print("Test forecast worked (on made-up prices; it means nothing about any market).")
PY
echo
echo "Done. Restart the platform (./watch.sh or ./run.sh yahoo) and the Kronos lane will start forecasting."
echo "It makes at most 6 forecasts per check; see Research -> Candle forecasts for the scorecard."
