"""Phase 3 — sentiment extraction.

    python -m src.sentiment.score --config config.yaml [--universe|--tickers ...]

Scores each text item to a signed sentiment (p_positive - p_negative), then
aggregates to DAILY PER-TICKER features under the lag rule (text after the ET
cutoff maps to the next session). Per-document scores are cached on disk keyed
by document id so the model never re-scores the same text.

Scorer selection:
  - FinBERT (ProsusAI/finbert) when transformers+torch are installed — the
    finance-tuned model the methodology recommends.
  - A finance lexicon scorer otherwise (deterministic, no heavy deps), which
    doubles as the "VADER-style fallback / comparison" the skill calls for.
The chosen scorer is recorded in the output so the writeup can name it.
"""
from __future__ import annotations

import argparse
import functools
import os

import numpy as np
import pandas as pd

from .. import utils
from ..data import sources
from ..data.pull import resolve_tickers

log = utils.get_logger("sentiment.score")

# --------------------------------------------------------------------------- #
# Scorers
# --------------------------------------------------------------------------- #
_FINBERT_PHRASES = None


@functools.lru_cache(maxsize=1)
def _load_finbert():
    """Return a callable(texts)->signed scores, or None if unavailable."""
    try:
        import torch
        from transformers import (AutoModelForSequenceClassification,
                                   AutoTokenizer)
    except Exception:  # noqa: BLE001
        return None
    name = "ProsusAI/finbert"
    try:
        tok = AutoTokenizer.from_pretrained(name)
        model = AutoModelForSequenceClassification.from_pretrained(name)
        model.eval()
    except Exception as e:  # noqa: BLE001 — offline / no weights
        log.warning("FinBERT unavailable (%s); using lexicon fallback", e)
        return None
    # ProsusAI/finbert label order: 0=positive, 1=negative, 2=neutral
    id2label = {int(k): v.lower() for k, v in model.config.id2label.items()}
    pos_i = next(i for i, l in id2label.items() if "pos" in l)
    neg_i = next(i for i, l in id2label.items() if "neg" in l)

    def score(texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 32):
            batch = texts[i:i + 32]
            enc = tok(batch, return_tensors="pt", padding=True,
                      truncation=True, max_length=512)
            with torch.no_grad():
                probs = torch.softmax(model(**enc).logits, dim=-1).numpy()
            out.append(probs[:, pos_i] - probs[:, neg_i])
        return np.concatenate(out) if out else np.array([])

    log.info("Using FinBERT (%s)", name)
    return score


# Finance lexicon fallback (Loughran-McDonald flavoured + retail slang).
_LEX_POS = {"beat", "beats", "raised", "raise", "upgrade", "upgraded", "moon", "calls",
            "breakout", "strong", "hike", "squeeze", "record", "bullish", "buy", "buying",
            "loading", "rally", "surge", "outperform", "growth", "gains"}
_LEX_NEG = {"missed", "miss", "cut", "downgrade", "downgraded", "puts", "bagholders",
            "weak", "selling", "overvalued", "lawsuit", "dumping", "bearish", "sell",
            "crash", "drop", "plunge", "underperform", "loss", "losses", "short"}


def _lexicon_score(texts: list[str]) -> np.ndarray:
    scores = np.zeros(len(texts))
    for i, t in enumerate(texts):
        toks = ''.join(c.lower() if c.isalnum() or c.isspace() else ' ' for c in t).split()
        if not toks:
            continue
        pos = sum(tok in _LEX_POS for tok in toks)
        neg = sum(tok in _LEX_NEG for tok in toks)
        if pos + neg:
            scores[i] = (pos - neg) / (pos + neg)
    return scores


def get_scorer(cfg: dict):
    if os.getenv("SENTIMENT_SCORER", "").lower() == "lexicon":
        log.info("Using finance-lexicon scorer (SENTIMENT_SCORER=lexicon)")
        return _lexicon_score, "lexicon"
    fb = _load_finbert()
    if fb is not None:
        return fb, "finbert"
    log.info("Using finance-lexicon fallback scorer (FinBERT not installed)")
    return _lexicon_score, "lexicon"


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #
def _cache_path(cfg: dict, scorer_name: str):
    return utils.p(cfg, "processed") / f"sentiment_cache_{scorer_name}.json"


def score_documents(cfg: dict, text: pd.DataFrame, scorer, scorer_name: str) -> pd.DataFrame:
    if text.empty:
        return text.assign(doc_score=pd.Series(dtype=float))
    cache_path = _cache_path(cfg, scorer_name)
    cache = utils.read_json(cache_path, default={}) or {}
    todo = text[~text["id"].astype(str).isin(cache)]
    if len(todo):
        new_scores = scorer(todo["text"].astype(str).tolist())
        for did, sc in zip(todo["id"].astype(str), new_scores):
            cache[did] = float(sc)
        utils.write_json(cache_path, cache)
    text = text.copy()
    text["doc_score"] = text["id"].astype(str).map(cache).astype(float)
    return text


# --------------------------------------------------------------------------- #
# Daily aggregation (with the lag rule)
# --------------------------------------------------------------------------- #
def _is_social(source: str) -> bool:
    s = str(source).lower()
    return s.startswith(("reddit", "twitter", "stocktwits", "social"))


def aggregate_daily(cfg: dict, ticker: str, scored: pd.DataFrame,
                    sessions: pd.DatetimeIndex) -> pd.DataFrame:
    cutoff = cfg["data"]["knowledge_cutoff_et"]
    # per-session score buckets: combined, news-only, social-only
    rows = {d: {"all": [], "news": [], "social": []} for d in sessions}

    if not scored.empty:
        ts = pd.to_datetime(scored["timestamp_utc"], utc=True)
        srcs = scored["source"] if "source" in scored else ["news"] * len(scored)
        for t_utc, sc, src in zip(ts, scored["doc_score"], srcs):
            sess = utils.session_for_timestamp(t_utc, sessions, cutoff)
            if sess is not None and sess in rows:
                rows[sess]["all"].append(sc)
                rows[sess]["social" if _is_social(src) else "news"].append(sc)

    recs = []
    prev = {"all": 0.0, "news": 0.0, "social": 0.0}
    for d in sessions:
        s = np.array(rows[d]["all"], dtype=float)
        n = len(s)
        if n > 0:
            mean, disp = float(np.mean(s)), float(np.std(s))
            share_pos, share_neg, no_cov = float((s > 0.1).mean()), float((s < -0.1).mean()), 0
        else:
            mean, disp, share_pos, share_neg, no_cov = 0.0, 0.0, 0.0, 0.0, 1
        nw = np.array(rows[d]["news"], dtype=float)
        so = np.array(rows[d]["social"], dtype=float)
        news_mean = float(np.mean(nw)) if len(nw) else 0.0
        social_mean = float(np.mean(so)) if len(so) else 0.0
        rec = {
            "date": d,
            "sent_mean": mean, "sent_dispersion": disp, "post_volume": n,
            "share_pos": share_pos, "share_neg": share_neg,
            "sent_momentum": mean - prev["all"], "no_coverage": no_cov,
            "news_sent_mean": news_mean, "news_post_volume": len(nw),
            "news_sent_momentum": news_mean - prev["news"],
            "social_sent_mean": social_mean, "social_post_volume": len(so),
            "social_sent_momentum": social_mean - prev["social"],
            "news_social_divergence": news_mean - social_mean,
        }
        recs.append(rec)
        if n > 0:
            prev["all"] = mean
        if len(nw):
            prev["news"] = news_mean
        if len(so):
            prev["social"] = social_mean
    return pd.DataFrame(recs)


def run(cfg: dict, tickers: list[str]) -> None:
    utils.set_seed(cfg["project"]["seed"])
    scorer, scorer_name = get_scorer(cfg)
    out_dir = utils.p(cfg, "processed") / "sentiment"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"scorer": scorer_name, "model": cfg["sentiment"]["model"]}

    for t in tickers:
        if not (utils.p(cfg, "raw") / "prices" / f"{t}.csv").exists():
            continue
        prices = sources.load_raw_prices(cfg, t)
        sessions = pd.DatetimeIndex(pd.to_datetime(prices["date"]).sort_values().unique())
        text = sources.load_raw_text(cfg, t)
        scored = score_documents(cfg, text, scorer, scorer_name)
        daily = aggregate_daily(cfg, t, scored, sessions)
        daily.to_csv(out_dir / f"{t}.csv", index=False)
        cov = float((daily["no_coverage"] == 0).mean())
        log.info("  %-6s docs=%d coverage=%.2f mean_sent=%+.3f (scorer=%s)",
                 t, len(text), cov, float(daily["sent_mean"].mean()), scorer_name)
    utils.write_json(out_dir / "_scorer.json", meta)
    log.info("Daily sentiment written to %s", out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="FinBERT/lexicon sentiment -> daily features")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--tickers", default=None)
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    run(cfg, resolve_tickers(cfg, args))


if __name__ == "__main__":
    main()
