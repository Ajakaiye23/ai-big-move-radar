"""Shared utilities: config, seeding, paths, calendar, logging, synthetic data.

Everything that more than one phase needs lives here so there are no magic
numbers scattered across modules (reproducibility checklist, references/
reproducibility.md). The single source of truth for *choices* is config.yaml;
this module just loads and applies it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

# --------------------------------------------------------------------------- #
# Paths & config
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.yaml"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency): KEY=VALUE lines, '#' comments.
    Does not override variables already set in the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Load config.yaml. All settings flow from here.

    Env overrides (handy for live runs / the daily Action without editing the file):
      DATA_MODE  -> data.mode (offline|auto|live)
      DATA_START -> data.start
      DATA_END   -> data.end
    And data.end may be set to "today"/"auto"/null to mean the current date — so a
    live tracker pulls right up to the latest session.
    """
    import datetime as _dt

    _load_dotenv(ROOT / ".env")  # make API keys available if a .env exists
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["_path"] = str(cfg_path)

    d = cfg.setdefault("data", {})
    if os.getenv("DATA_MODE"):
        d["mode"] = os.environ["DATA_MODE"]
    if os.getenv("DATA_START"):
        d["start"] = os.environ["DATA_START"]
    if os.getenv("DATA_END"):
        d["end"] = os.environ["DATA_END"]
    if d.get("end") in (None, "today", "auto", ""):
        d["end"] = _dt.date.today().isoformat()
    return cfg


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable short hash of the config, minus volatile keys — stamped into artifacts."""
    c = {k: v for k, v in cfg.items() if not k.startswith("_")}
    blob = json.dumps(c, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def p(cfg: dict, key: str) -> Path:
    """Resolve a configured path (relative to repo root) and ensure it exists."""
    rel = cfg["paths"][key]
    path = (ROOT / rel).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def stable_hash(s: str) -> int:
    """Deterministic, cross-process integer hash (builtin hash() is salted)."""
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def set_seed(seed: int) -> None:
    """Fix every RNG we touch (numpy, python, hash) — reproducibility guardrail."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                         datefmt="%H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger


# --------------------------------------------------------------------------- #
# Trading calendar helpers (lag rule lives here, see references/data-pipeline.md)
# --------------------------------------------------------------------------- #
def trading_days(start: str, end: str) -> pd.DatetimeIndex:
    """Business days as a stand-in NYSE calendar (holidays approximated by weekdays).

    Good enough for alignment in a research project; swap in pandas_market_calendars
    for exact holidays in production.
    """
    return pd.bdate_range(start=start, end=end)


def session_for_timestamp(ts_utc: pd.Timestamp, sessions: pd.DatetimeIndex,
                          cutoff_et: str = "16:00") -> pd.Timestamp | None:
    """Map a UTC publish time to the trading session that could first act on it.

    THE LAG RULE. Text published after `cutoff_et` (US/Eastern) on a session, or
    on a non-trading day, maps to the *next* session — never the current one.
    Getting this wrong is silent leakage (methodology.md, leakage type #4).
    """
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.tz_localize("UTC")
    et = ts_utc.tz_convert("US/Eastern")
    hh, mm = (int(x) for x in cutoff_et.split(":"))
    cutoff = et.replace(hour=hh, minute=mm, second=0, microsecond=0)
    # The earliest session on/after the publish date; bump one if past cutoff.
    publish_date = et.normalize().tz_localize(None)
    idx = sessions.searchsorted(publish_date, side="left")
    if idx >= len(sessions):
        return None
    candidate = sessions[idx]
    same_session = candidate.normalize() == publish_date
    if same_session and et > cutoff:
        idx += 1  # after close -> next session
    elif not same_session:
        pass      # already the next available session
    return sessions[idx] if idx < len(sessions) else None


# --------------------------------------------------------------------------- #
# Deterministic synthetic data generator (offline mode)
# --------------------------------------------------------------------------- #
# This lets the WHOLE pipeline run with no network, no API keys, and identical
# output every time — for CI, the leakage tests, and a self-contained demo. The
# synthetic text carries a small, *lagged, noisy* relationship to the next
# session's return so the sentiment ablation has something honest to measure;
# the mechanics (alignment, leakage discipline, calibration, backtest) are real.
# Anything produced in offline mode is clearly labelled synthetic everywhere.
@dataclass
class SynthSpec:
    drift: float          # daily up-probability bias (markets drift up)
    vol: float            # daily return volatility
    sentiment_edge: float # how much next-day return leaks into today's text (0 = none)


# `sentiment_edge` = how strongly today's text tracks the NEXT session's move.
# It is an *injected, known* signal so the ablation has something real to detect
# on synthetic data — kept modest (markets aren't this predictable) and clearly
# documented as synthetic. With live data this edge is whatever the market gives.
_SYNTH_PROFILES = {
    # ticker-specific personalities so the universe isn't homogeneous
    "default": SynthSpec(drift=0.0004, vol=0.018, sentiment_edge=0.18),
    "meme":    SynthSpec(drift=0.0000, vol=0.045, sentiment_edge=0.22),  # GME/AMC-like
    "etf":     SynthSpec(drift=0.0003, vol=0.010, sentiment_edge=0.12),  # SPY/QQQ-like
}

_MEME = {"GME", "AMC", "MSTR", "SMCI", "COIN", "HOOD", "SOFI", "PLTR"}
_ETF = {"SPY", "QQQ"}


def _spec_for(ticker: str) -> SynthSpec:
    if ticker in _ETF:
        return _SYNTH_PROFILES["etf"]
    if ticker in _MEME:
        return _SYNTH_PROFILES["meme"]
    return _SYNTH_PROFILES["default"]


def _ticker_seed(ticker: str, base_seed: int) -> int:
    h = int(hashlib.sha256(ticker.encode()).hexdigest(), 16)
    return (h + base_seed) % (2**32)


def synth_prices(ticker: str, start: str, end: str, base_seed: int) -> pd.DataFrame:
    """Deterministic OHLCV for one ticker. Geometric random walk + mild momentum."""
    sessions = trading_days(start, end)
    rng = np.random.default_rng(_ticker_seed(ticker, base_seed))
    spec = _spec_for(ticker)
    n = len(sessions)

    # GARCH(1,1)-style volatility clustering so big moves are *predictable* (they
    # cluster) — the whole premise of the volatility/big-move target. Real markets
    # behave this way; a constant-vol random walk does not.
    alpha, beta = 0.10, 0.85
    omega = spec.vol ** 2 * (1 - alpha - beta)
    rets = np.zeros(n)
    var = spec.vol ** 2
    for i in range(n):
        if i > 0:
            var = omega + alpha * rets[i - 1] ** 2 + beta * var
        rets[i] = rng.normal(spec.drift, np.sqrt(max(var, 1e-8)))
    # mild autocorrelation so persistence is a non-trivial baseline
    for i in range(1, n):
        rets[i] += 0.05 * rets[i - 1]
    price0 = 50 + rng.uniform(0, 250)
    close = price0 * np.exp(np.cumsum(rets))
    open_ = close / (1 + rng.normal(0, spec.vol / 3, size=n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, spec.vol / 2, size=n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, spec.vol / 2, size=n)))
    vol = rng.lognormal(mean=15.5, sigma=0.4, size=n).astype(np.int64)

    return pd.DataFrame({
        "date": sessions,
        "open": open_.round(4),
        "high": high.round(4),
        "low": low.round(4),
        "close": close.round(4),
        "volume": vol,
    })


# A small finance-flavoured vocabulary for synthetic posts. The generator picks
# bullish/bearish phrasing with a probability nudged by the *next* day's return,
# then timestamps the post BEFORE that move — the sentiment scorer must recover
# the signal and the lag logic must keep it causal.
_BULL = ["beat earnings", "raised guidance", "huge upgrade", "to the moon", "buying calls",
         "breakout incoming", "strong demand", "analyst price target hike", "squeeze setup",
         "record revenue", "loading up shares", "bullish momentum"]
_BEAR = ["missed estimates", "cut guidance", "downgrade", "selling puts", "bagholders",
         "weak demand", "insider selling", "overvalued", "dead cat bounce", "lawsuit risk",
         "dumping shares", "bearish breakdown"]
_NEUTRAL = ["sideways action", "waiting for earnings", "holding for now", "low volume day",
            "no clear direction", "watching the chart", "earnings next week"]


def synth_text(ticker: str, prices: pd.DataFrame, base_seed: int,
               cutoff_et: str = "16:00") -> pd.DataFrame:
    """Deterministic timestamped posts/news for one ticker.

    Returns rows: id, ticker, timestamp_utc (ISO), source, text.
    Posts are timestamped on the session *before* the move they hint at, with a
    realistic spread of intraday and after-hours times so the lag rule matters.
    """
    rng = np.random.default_rng(_ticker_seed(ticker, base_seed) ^ 0x5151)
    spec = _spec_for(ticker)
    closes = prices["close"].to_numpy()
    next_ret = np.zeros(len(closes))
    next_ret[:-1] = closes[1:] / closes[:-1] - 1.0

    rows = []
    sources = ["reddit:wallstreetbets", "reddit:stocks", "news:finnhub", "news:gdelt"]
    for i, day in enumerate(prices["date"]):
        # attention spikes: more posts when |move| is large (also tests volume feature)
        base_posts = 2 if ticker in _ETF else 4
        n_posts = max(0, int(rng.poisson(base_posts + 20 * abs(next_ret[i]))))
        # probability of a bullish post nudged by the (lagged-into-future) move
        edge = spec.sentiment_edge
        p_bull = np.clip(0.50 + (next_ret[i] / max(spec.vol, 1e-6)) * edge
                         + rng.normal(0, 0.035), 0.05, 0.95)
        for _ in range(n_posts):
            r = rng.random()
            if r < p_bull * 0.8:
                text = rng.choice(_BULL)
            elif r < p_bull * 0.8 + (1 - p_bull) * 0.8:
                text = rng.choice(_BEAR)
            else:
                text = rng.choice(_NEUTRAL)
            # random time of day in ET; some after-hours to exercise the lag
            hour = int(rng.integers(6, 22))
            minute = int(rng.integers(0, 60))
            et = pd.Timestamp(day).tz_localize("US/Eastern") + pd.Timedelta(hours=hour, minutes=minute)
            ts_utc = et.tz_convert("UTC")
            src = sources[int(rng.integers(0, len(sources)))]
            text_full = f"${ticker} {text}"
            doc_id = hashlib.sha1(f"{ticker}|{ts_utc.isoformat()}|{text_full}|{rng.random()}"
                                  .encode()).hexdigest()[:16]
            rows.append({
                "id": doc_id,
                "ticker": ticker,
                "timestamp_utc": ts_utc.isoformat(),
                "source": src,
                "text": text_full,
            })
    return pd.DataFrame(rows, columns=["id", "ticker", "timestamp_utc", "source", "text"])


def _json_safe(obj: Any) -> Any:
    """Recursively replace NaN/Infinity with None — they are invalid JSON and
    break browser JSON.parse (the dashboard reads these files)."""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.floating):
        return _json_safe(float(obj))
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_json_safe(obj), fh, indent=2, default=str, allow_nan=False)


def read_json(path: Path, default: Any = None) -> Any:
    if not Path(path).exists():
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
