"""
Module: train_e17_crypto.py
Description: Calibrates e17_crypto's funding-rate positioning-crowding
    read from real historical data -- same discipline as
    train_e16_commodity.py's commercial-positioning percentiles, applied to
    perpetual-futures funding rate instead of CFTC COT data.

    Two things happen here, both against REAL data (ccxt Binance funding
    rate history, no key needed; yfinance daily close for forward returns):

    1. Percentile thresholds (10th/25th/75th/90th) of daily-average funding
       rate, from a chronological TRAIN slice (first 70% of the pulled
       history) -- used by e17_crypto to classify "today's" funding rate
       as crowded_short / normal / crowded_long.
    2. A genuine held-out test of the classic contrarian hypothesis
       (crowded_long funding precedes weaker forward returns than
       crowded_short/normal, because everyone already positioned long is
       paying to stay there): computed on the chronological TEST slice
       (last 30%) using the percentiles fit on TRAIN only, never on data
       the percentiles were fit on. Reported honestly either way --
       contrarian_effect_validated is False, not fabricated True, if the
       held-out data doesn't confirm it. e17_crypto reads this flag and
       only lets a confirmed effect swing E51 confluence confidence by the
       full weight; an unconfirmed effect still classifies (informational)
       but confluence should treat it as unvalidated.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e17_crypto" / "calibration.json"

# ccxt unified perpetual-swap symbol -> yfinance spot symbol, for the two
# crypto assets this platform actually supports (core/config/assets.py).
ASSETS = {
    "BTCUSD": ("BTC/USDT:USDT", "BTC-USD"),
    "ETHUSD": ("ETH/USDT:USDT", "ETH-USD"),
}

FORWARD_RETURN_DAYS = 3
TRAIN_FRACTION = 0.7
HISTORY_DAYS = 365


def _fetch_funding_history(market: str, days: int) -> pd.DataFrame:
    """Paginate ccxt's fetch_funding_rate_history (Binance caps each call,
    typically ~1000 rows / ~333 days at 8h funding) back `days` days."""
    exchange = ccxt.binance()
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    all_rows: list[dict] = []
    while True:
        batch = exchange.fetch_funding_rate_history(market, since=since, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = batch[-1]["timestamp"]
        if last_ts is None or last_ts <= since:
            break
        since = last_ts + 1
        if len(batch) < 1000:
            break
    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame([{"timestamp": r["timestamp"], "funding_rate": r["fundingRate"]} for r in all_rows])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.dropna().drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


def _daily_average_funding(df: pd.DataFrame) -> pd.Series:
    """Funding prints every 8h -- average to one reading per day so it can
    be aligned against daily close-to-close forward returns."""
    daily = df.set_index("timestamp")["funding_rate"].resample("1D").mean().dropna()
    return daily


def _percentiles(train: pd.Series) -> dict[str, float]:
    return {
        "10": float(np.percentile(train, 10)),
        "25": float(np.percentile(train, 25)),
        "75": float(np.percentile(train, 75)),
        "90": float(np.percentile(train, 90)),
    }


def _classify(value: float, p: dict[str, float]) -> str:
    if value < p["10"]:
        return "crowded_short"
    if value > p["90"]:
        return "crowded_long"
    return "normal"


def calibrate_asset(symbol: str, market: str, yahoo_symbol: str) -> dict:
    logger.info("Fetching funding rate history for %s (%s)...", symbol, market)
    funding_raw = _fetch_funding_history(market, HISTORY_DAYS)
    if funding_raw.empty or len(funding_raw) < 60:
        return {"error": f"insufficient funding rate history for {symbol} ({len(funding_raw)} rows)"}
    daily_funding = _daily_average_funding(funding_raw)

    logger.info("Fetching price history for %s (%s)...", symbol, yahoo_symbol)
    price = yf.download(yahoo_symbol, period="2y", interval="1d", progress=False, auto_adjust=True)
    if price.empty:
        return {"error": f"no price history for {yahoo_symbol}"}
    if isinstance(price.columns, pd.MultiIndex):
        price.columns = price.columns.get_level_values(0)
    close = price["Close"]
    close.index = pd.to_datetime(close.index, utc=True)
    forward_return = close.pct_change(FORWARD_RETURN_DAYS).shift(-FORWARD_RETURN_DAYS)

    aligned = pd.DataFrame({"funding": daily_funding}).join(
        pd.DataFrame({"fwd_return": forward_return}), how="inner"
    ).dropna()
    if len(aligned) < 60:
        return {"error": f"only {len(aligned)} aligned funding/price rows for {symbol} -- too few to calibrate"}

    split = int(len(aligned) * TRAIN_FRACTION)
    train, test = aligned.iloc[:split], aligned.iloc[split:]
    if len(test) < 15:
        return {"error": f"held-out slice too small ({len(test)} rows) for {symbol}"}

    percentiles = _percentiles(train["funding"])
    test = test.copy()
    test["regime"] = test["funding"].apply(lambda v: _classify(v, percentiles))

    overall_mean_fwd = float(test["fwd_return"].mean())
    crowded_long_mean_fwd = test.loc[test["regime"] == "crowded_long", "fwd_return"]
    crowded_short_mean_fwd = test.loc[test["regime"] == "crowded_short", "fwd_return"]

    # Contrarian hypothesis: crowded_long precedes WEAKER forward returns
    # than the unconditional held-out mean; crowded_short precedes
    # STRONGER forward returns than the unconditional mean. Both legs must
    # hold, with at least a few held-out observations in each regime, or
    # this is reported honestly as unvalidated -- never fabricated.
    validated = (
        len(crowded_long_mean_fwd) >= 3
        and len(crowded_short_mean_fwd) >= 3
        and float(crowded_long_mean_fwd.mean()) < overall_mean_fwd
        and float(crowded_short_mean_fwd.mean()) > overall_mean_fwd
    )

    return {
        "percentiles": percentiles,
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "held_out_overall_mean_fwd_return_pct": round(overall_mean_fwd * 100, 4),
        "held_out_crowded_long_mean_fwd_return_pct": (
            round(float(crowded_long_mean_fwd.mean()) * 100, 4) if len(crowded_long_mean_fwd) else None
        ),
        "held_out_crowded_short_mean_fwd_return_pct": (
            round(float(crowded_short_mean_fwd.mean()) * 100, 4) if len(crowded_short_mean_fwd) else None
        ),
        "n_held_out_crowded_long": int(len(crowded_long_mean_fwd)),
        "n_held_out_crowded_short": int(len(crowded_short_mean_fwd)),
        "contrarian_effect_validated": bool(validated),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    calibration: dict[str, dict] = {}
    for symbol, (market, yahoo_symbol) in ASSETS.items():
        try:
            calibration[symbol] = calibrate_asset(symbol, market, yahoo_symbol)
        except Exception as e:
            logger.error("Calibration failed for %s: %s", symbol, e)
            calibration[symbol] = {"error": str(e)}

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "forward_return_days": FORWARD_RETURN_DAYS,
        "train_fraction": TRAIN_FRACTION,
        "history_days_requested": HISTORY_DAYS,
        "assets": calibration,
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2))

    print(f"\nSaved calibration to {OUTPUT_PATH}\n")
    for symbol, result in calibration.items():
        if "error" in result:
            print(f"{symbol}: FAILED -- {result['error']}")
            continue
        print(
            f"{symbol}: contrarian_effect_validated={result['contrarian_effect_validated']} "
            f"(held-out: crowded_long fwd={result['held_out_crowded_long_mean_fwd_return_pct']}%, "
            f"crowded_short fwd={result['held_out_crowded_short_mean_fwd_return_pct']}%, "
            f"overall fwd={result['held_out_overall_mean_fwd_return_pct']}%, "
            f"n_test={result['n_test']})"
        )


if __name__ == "__main__":
    main()
