"""Phase 2 — target definition & calendar alignment.

    python -m src.data.align --config config.yaml [--universe|--tickers ...]

Produces, per ticker, a clean daily frame aligned to the trading calendar with:
  - the precisely-defined target (binary up/down, or 3-class with dead-band)
  - forward return for the backtest (trade on NEXT open after the signal)
  - an earnings/event flag (outlier days — flag at minimum, optionally exclude)

The label and the lag rule are the two places projects silently cheat
(methodology.md). Both are pinned here and reused everywhere downstream.
"""
from __future__ import annotations

import argparse
import hashlib

import numpy as np
import pandas as pd

from .. import utils
from . import sources
from .pull import resolve_tickers

log = utils.get_logger("data.align")


def _earnings_flag(ticker: str, dates: pd.Series, seed: int, mode: str) -> np.ndarray:
    """~quarterly earnings days. OFFLINE: a deterministic synthetic flag. LIVE:
    no fabricated flags (the real Finnhub earnings calendar isn't wired yet), so
    return zeros rather than invent event days on real prices — honesty over a
    fake feature. Wire the Finnhub calendar here to light this up for real."""
    if mode != "offline":
        return np.zeros(len(dates), dtype=int)
    h = int(hashlib.sha256(f"{ticker}{seed}".encode()).hexdigest(), 16)
    offset = h % 63
    idx = np.arange(len(dates))
    return ((idx - offset) % 63 == 0).astype(int)


def build_target(prices: pd.DataFrame, cfg: dict, ticker: str) -> pd.DataFrame:
    H = cfg["target"]["horizon_days"]
    ttype = cfg["target"]["type"]
    eps = float(cfg["target"]["dead_band"])
    seed = cfg["project"]["seed"]

    df = prices.sort_values("date").reset_index(drop=True).copy()
    df["fwd_ret"] = df["close"].shift(-H) / df["close"] - 1.0
    # backtest acts on next open -> next-open-to-next-open return for realism
    df["next_open"] = df["open"].shift(-1)
    df["fwd_open_ret"] = df["open"].shift(-(H + 1)) / df["open"].shift(-1) - 1.0

    if ttype == "binary":
        df["y"] = (df["fwd_ret"] > 0).astype("Int64")
    elif ttype == "three_class":
        df["y"] = np.select(
            [df["fwd_ret"] > eps, df["fwd_ret"] < -eps],
            [2, 0], default=1).astype("Int64")  # 0=down,1=flat,2=up
    elif ttype == "big_move":
        # 1 if next session's move is large vs the stock's LONGER-RUN daily vol.
        # The baseline window must be longer than the short-vol features (5/10/20d)
        # so that short-term vol spikes — which cluster (GARCH) and which the model
        # can see — actually predict threshold exceedances. (Defining 'big' vs the
        # immediate trailing vol would normalize the clustering signal away.)
        k = float(cfg["target"].get("big_move_k", 1.5))
        win = int(cfg["target"].get("big_move_vol_window", 60))
        daily_ret = df["close"].pct_change()
        base_std = daily_ret.rolling(win, min_periods=20).std()   # causal long-run vol
        df["move_threshold"] = k * base_std
        df["y"] = (df["fwd_ret"].abs() > df["move_threshold"]).astype("Int64")
        df.loc[base_std.isna(), "y"] = pd.NA
    else:
        raise ValueError(f"unknown target.type {ttype!r}")
    # rows where the future is unknown (last H rows) have no label
    df.loc[df["fwd_ret"].isna(), "y"] = pd.NA

    df["earnings_day"] = _earnings_flag(ticker, df["date"], seed, cfg["data"]["mode"])
    df["ticker"] = ticker
    return df


def run(cfg: dict, tickers: list[str]) -> None:
    out_dir = utils.p(cfg, "processed")
    for t in tickers:
        if not (utils.p(cfg, "raw") / "prices" / f"{t}.csv").exists():
            log.warning("  %-6s skipped (no raw prices)", t)
            continue
        prices = sources.load_raw_prices(cfg, t)
        aligned = build_target(prices, cfg, t)
        path = out_dir / f"{t}_aligned.csv"
        aligned.to_csv(path, index=False)
        n_lbl = int(aligned["y"].notna().sum())
        up_rate = float(aligned["y"].dropna().astype(int).mean()) if n_lbl else float("nan")
        log.info("  %-6s sessions=%d labelled=%d up-rate=%.3f earnings=%d",
                 t, len(aligned), n_lbl, up_rate, int(aligned["earnings_day"].sum()))
    log.info("Aligned frames written to %s", out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="Define target + align to calendar")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--tickers", default=None)
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    run(cfg, resolve_tickers(cfg, args))


if __name__ == "__main__":
    main()
