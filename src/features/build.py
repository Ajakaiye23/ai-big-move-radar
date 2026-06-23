"""Phase 4 — feature engineering.

    python -m src.features.build --config config.yaml [--universe|--tickers ...]

Builds per-ticker feature tables and a pooled table, with features grouped so
the ablation can drop any group as a block. EVERY feature is causal: the row for
day t uses only data known at the close of day t (the decision point for the
t -> t+H move). Group membership is written to processed/feature_groups.json.

Feature groups (mirror the data-source groups A-F in references/data-pipeline.md):
  market      price/volume technicals
  sentiment   FinBERT/lexicon daily aggregates
  regime      market index + VIX context
  events      earnings/event flags
  positioning options put/call + short interest
  attention   search/attention proxies
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import utils
from ..data.pull import resolve_tickers

log = utils.get_logger("features.build")

SECTOR = {
    "AAPL": "tech", "MSFT": "tech", "NVDA": "semis", "AMD": "semis", "TSLA": "auto",
    "AMZN": "consumer", "GOOGL": "tech", "META": "tech", "AVGO": "semis", "NFLX": "media",
    "AMC": "meme", "GME": "meme", "PLTR": "software", "COIN": "crypto", "SOFI": "fintech",
    "HOOD": "fintech", "SMCI": "semis", "MSTR": "crypto", "INTC": "semis", "MU": "semis",
    "ORCL": "software", "CRM": "software", "ADBE": "software", "CSCO": "tech", "QCOM": "semis",
    "MRVL": "semis", "ARM": "semis", "RIVN": "auto", "LCID": "auto", "NIO": "auto",
    "UBER": "tech", "ABNB": "consumer", "SHOP": "software", "PYPL": "fintech", "DIS": "media",
    "BA": "industrial", "JPM": "financials", "WMT": "consumer", "COST": "consumer",
    "SPY": "etf", "QQQ": "etf",
}
# fixed integer codes so the pooled structural features are reproducible
SECTOR_CODES = {s: i for i, s in enumerate(sorted(set(SECTOR.values()) | {"other"}))}


# --------------------------------------------------------------------------- #
# Technical indicators (all backward-looking / causal)
# --------------------------------------------------------------------------- #
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series) -> pd.Series:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    return ema12 - ema26


# --------------------------------------------------------------------------- #
# Regime context (synthetic market index + VIX in offline mode)
# --------------------------------------------------------------------------- #
def market_context(cfg: dict) -> pd.DataFrame:
    """Market index return + VIX, aligned to sessions. LIVE: real ^GSPC + ^VIX
    from yfinance. OFFLINE: a synthetic index + realized-vol proxy."""
    mode = cfg["data"]["mode"]
    start, end = cfg["data"]["start"], cfg["data"]["end"]

    if mode in ("live", "auto"):
        try:
            import yfinance as yf
            spx = yf.download("^GSPC", start=start, end=end, auto_adjust=True,
                              progress=False, threads=False)
            vixd = yf.download("^VIX", start=start, end=end, auto_adjust=True,
                               progress=False, threads=False)
            if spx is not None and len(spx) > 30:
                if isinstance(spx.columns, pd.MultiIndex):
                    spx.columns = spx.columns.get_level_values(0)
                    vixd.columns = vixd.columns.get_level_values(0)
                date = pd.to_datetime(spx.index)
                mkt_ret = spx["Close"].pct_change()
                vix = vixd["Close"].reindex(spx.index).ffill().bfill() if vixd is not None \
                    else (mkt_ret.rolling(10).std() * np.sqrt(252) * 100).bfill()
                return pd.DataFrame({
                    "date": date.tz_localize(None),
                    "mkt_ret_1": mkt_ret.values,
                    "mkt_vol_10": mkt_ret.rolling(10).std().values,
                    "vix_level": np.asarray(vix).ravel(),
                    "vix_change": pd.Series(np.asarray(vix).ravel()).diff().values,
                })
            if mode == "live":
                raise RuntimeError("could not fetch real ^GSPC/^VIX")
        except Exception as e:  # noqa: BLE001
            if mode == "live":
                raise
            log.warning("regime live fetch failed (%s); using synthetic", e)

    seed = cfg["project"]["seed"]
    spy = utils.synth_prices("SPY", start, end, seed).sort_values("date").reset_index(drop=True)
    mkt_ret = spy["close"].pct_change()
    vix = (mkt_ret.rolling(10).std() * np.sqrt(252) * 100).bfill()
    return pd.DataFrame({
        "date": spy["date"],
        "mkt_ret_1": mkt_ret,
        "mkt_vol_10": mkt_ret.rolling(10).std(),
        "vix_level": vix,
        "vix_change": vix.diff(),
    })


def positioning_features(ticker: str, df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Options put/call + short interest. Synthetic but deterministic offline;
    replaced by yfinance option chains + FINRA/Finnhub in live mode."""
    rng = np.random.default_rng((utils.stable_hash(ticker) ^ cfg["project"]["seed"]) % (2**32))
    n = len(df)
    realized_vol = df["close"].pct_change().rolling(10).std().fillna(0.02)
    # put/call rises with recent downside; short interest drifts slowly
    put_call = np.clip(1.0 + 5 * (-df["close"].pct_change().fillna(0)) +
                       rng.normal(0, 0.1, n), 0.3, 3.0)
    short_interest = np.clip(np.cumsum(rng.normal(0, 0.002, n)) + 0.1, 0.01, 0.6)
    return pd.DataFrame({
        "put_call_ratio": put_call,
        "implied_vol": (realized_vol * 16 + rng.normal(0, 0.01, n)).clip(0.05, 2.0),
        "short_interest": short_interest,
    }, index=df.index)


def attention_features(ticker: str, daily_sent: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Search/attention proxies (Google Trends / Wikipedia). Offline: derived
    from post volume + noise; live: pytrends + Wikipedia REST."""
    rng = np.random.default_rng((utils.stable_hash("attn" + ticker) ^ cfg["project"]["seed"]) % (2**32))
    vol = daily_sent["post_volume"].astype(float)
    attn = (vol / (vol.rolling(20).mean() + 1e-6)).fillna(1.0)
    attn = attn + rng.normal(0, 0.05, len(attn))
    return pd.DataFrame({
        "attn_index": attn.values,
        "attn_change": pd.Series(attn.values).diff().fillna(0).values,
    })


# --------------------------------------------------------------------------- #
# Per-ticker feature assembly
# --------------------------------------------------------------------------- #
GROUPS: dict[str, list[str]] = {
    "market": [
        "ret_1", "ret_2", "ret_3", "ret_5", "ret_10",
        "ma5_ratio", "ma10_ratio", "ma20_ratio",
        "vol_5", "vol_10", "vol_20",
        "rsi_14", "macd", "volume_change", "volume_vs_ma", "dow",
        "rel_strength_sector",      # daily return minus its sector's mean (cross-sectional)
    ],
    "sentiment": [
        "sent_mean", "sent_dispersion", "post_volume", "share_pos", "share_neg",
        "sent_momentum", "no_coverage", "sent_roll3", "sent_roll5", "sent_roll10",
        "sent_surprise",            # z-score of sentiment vs its trailing 20d (change > level)
        "sent_x_volume",            # sentiment weighted by attention (post volume)
        "sent_accel",               # change in sentiment momentum
    ],
    # news vs social split — answers "is it the press or the crowd that helps?"
    "sentiment_news": ["news_sent_mean", "news_post_volume", "news_sent_momentum"],
    "sentiment_social": ["social_sent_mean", "social_post_volume", "social_sent_momentum",
                         "news_social_divergence"],
    "regime": ["mkt_ret_1", "mkt_vol_10", "vix_level", "vix_change"],
    # earnings_day is a META column (always present, used for the exclusion rule);
    # the events FEATURE group is days_since_earnings so it doesn't double-list.
    "events": ["days_since_earnings"],
    "positioning": ["put_call_ratio", "implied_vol", "short_interest"],
    "attention": ["attn_index", "attn_change"],
}
# pooled-only structural features (identify the ticker/sector in a shared model)
POOLED_COLS = ["ticker_code", "sector_code"]

# Groups whose features are currently SYNTHETIC stubs (options/short-interest,
# attention proxies, synthetic earnings flags). They're only honest when prices
# are synthetic too, so we build them in offline mode only. Wire real fetchers
# (yfinance options, FINRA short interest, pytrends/Wikipedia, Finnhub calendar)
# to promote them into live mode.
_SYNTHETIC_ONLY_GROUPS = ("events", "positioning", "attention")


def active_groups(cfg: dict) -> list[str]:
    """Which feature groups to build, given the data mode. LIVE/AUTO use only
    real-backed groups (market, regime, sentiment); OFFLINE uses all."""
    if cfg["data"]["mode"] == "offline":
        return list(GROUPS)
    return [g for g in GROUPS if g not in _SYNTHETIC_ONLY_GROUPS]


def build_ticker(cfg: dict, ticker: str, mkt: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    proc = utils.p(cfg, "processed")
    aligned = pd.read_csv(proc / f"{ticker}_aligned.csv", parse_dates=["date"])
    sent = pd.read_csv(proc / "sentiment" / f"{ticker}.csv", parse_dates=["date"])

    df = aligned.merge(sent, on="date", how="left").sort_values("date").reset_index(drop=True)
    c = df["close"]

    # --- market group (causal: only past+current close/volume) ---
    for k in (1, 2, 3, 5, 10):
        df[f"ret_{k}"] = c.pct_change(k)
    for k in (5, 10, 20):
        df[f"ma{k}_ratio"] = c / c.rolling(k).mean() - 1.0
        df[f"vol_{k}"] = c.pct_change().rolling(k).std()
    df["rsi_14"] = rsi(c, 14)
    df["macd"] = macd(c)
    df["volume_change"] = df["volume"].pct_change()
    df["volume_vs_ma"] = df["volume"] / df["volume"].rolling(20).mean() - 1.0
    df["dow"] = df["date"].dt.dayofweek

    # --- sentiment group (rolling + dynamics on top of daily aggregates) ---
    sent_cols = ["sent_mean", "sent_dispersion", "post_volume", "share_pos",
                 "share_neg", "sent_momentum", "no_coverage",
                 "news_sent_mean", "news_post_volume", "news_sent_momentum",
                 "social_sent_mean", "social_post_volume", "social_sent_momentum",
                 "news_social_divergence"]
    for col in sent_cols:
        if col not in df:
            df[col] = 0.0
    df["sent_roll3"] = df["sent_mean"].rolling(3).mean()
    df["sent_roll5"] = df["sent_mean"].rolling(5).mean()
    df["sent_roll10"] = df["sent_mean"].rolling(10).mean()
    # surprise: how far today's sentiment is from its own recent norm (causal)
    roll_mean = df["sent_mean"].rolling(20).mean()
    roll_std = df["sent_mean"].rolling(20).std()
    df["sent_surprise"] = ((df["sent_mean"] - roll_mean) / (roll_std + 1e-6))
    df["sent_x_volume"] = df["sent_mean"] * np.log1p(df["post_volume"])
    df["sent_accel"] = df["sent_momentum"].diff()

    # --- regime group ---
    if "regime" in groups:
        df = df.merge(mkt, on="date", how="left")

    # --- events group (synthetic-only; gated off in live mode) ---
    if "events" in groups:
        earn_idx = df.index[df["earnings_day"] == 1].to_numpy()
        days_since = np.full(len(df), 999)
        for i in range(len(df)):
            prev = earn_idx[earn_idx <= i]
            if len(prev):
                days_since[i] = i - prev[-1]
        df["days_since_earnings"] = days_since

    # --- positioning group (synthetic-only; gated off in live mode) ---
    if "positioning" in groups:
        pos = positioning_features(ticker, df, cfg)
        for col in pos.columns:
            df[col] = pos[col].values

    # --- attention group (synthetic-only; gated off in live mode) ---
    if "attention" in groups:
        attn = attention_features(ticker, df, cfg)
        for col in attn.columns:
            df[col] = attn[col].values

    # structural (for pooled model) — reproducible integer codes
    df["sector_code"] = SECTOR_CODES.get(SECTOR.get(ticker, "other"), SECTOR_CODES["other"])
    df["ticker_code"] = utils.stable_hash(ticker) % 100_000

    return df


def all_feature_cols() -> list[str]:
    cols: list[str] = []
    for g in GROUPS.values():
        cols += g
    return cols


def run(cfg: dict, tickers: list[str]) -> None:
    utils.set_seed(cfg["project"]["seed"])
    proc = utils.p(cfg, "processed")
    feat_dir = proc / "features"
    feat_dir.mkdir(parents=True, exist_ok=True)
    mkt = market_context(cfg)
    groups = active_groups(cfg)
    feature_cols = [c for g in groups for c in GROUPS[g]]
    keep_meta = ["date", "ticker", "y", "fwd_ret", "fwd_open_ret", "next_open",
                 "close", "open", "earnings_day"]
    # build every ticker (full frames) first, so we can compute cross-sectional features
    avail = [t for t in tickers if (proc / f"{t}_aligned.csv").exists()]
    built = {t: build_ticker(cfg, t, mkt, groups) for t in avail}

    # sector-relative strength: each ticker's daily return minus its sector's mean
    big = pd.concat([d.assign(_t=t) for t, d in built.items()], ignore_index=True)
    big["_sector"] = big["_t"].map(lambda t: SECTOR.get(t, "other"))
    sec_mean = big.groupby(["date", "_sector"])["ret_1"].transform("mean")
    big["rel_strength_sector"] = (big["ret_1"] - sec_mean).fillna(0.0)
    for t, d in built.items():
        rs = big.loc[big["_t"] == t].set_index("date")["rel_strength_sector"]
        d["rel_strength_sector"] = d["date"].map(rs).fillna(0.0).values

    pooled = []
    for t in avail:
        df = built[t]
        cols = [col for col in (keep_meta + feature_cols + POOLED_COLS) if col in df]
        df = df[cols]
        df.to_csv(feat_dir / f"{t}.csv", index=False)
        pooled.append(df)
        log.info("  %-6s rows=%d features=%d", t, len(df), len(feature_cols))

    pooled_df = pd.concat(pooled, ignore_index=True).sort_values(["date", "ticker"])
    pooled_df.to_csv(feat_dir / "_pooled.csv", index=False)

    groups_out = {g: GROUPS[g] for g in groups}
    groups_out.update({"_pooled_structural": POOLED_COLS, "_all": feature_cols,
                       "_meta_cols": keep_meta, "_active_groups": groups,
                       "_data_mode": cfg["data"]["mode"]})
    utils.write_json(feat_dir / "feature_groups.json", groups_out)
    log.info("Built groups %s (mode=%s). feature_groups.json -> %s (pooled rows=%d)",
             groups, cfg["data"]["mode"], feat_dir, len(pooled_df))


def main() -> None:
    ap = argparse.ArgumentParser(description="Build causal grouped features")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--tickers", default=None)
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    run(cfg, resolve_tickers(cfg, args))


if __name__ == "__main__":
    main()
