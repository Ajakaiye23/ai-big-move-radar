"""Daily refresh entry point — run by .github/workflows/daily-update.yml.

    python -m src.predict --config config.yaml [--universe] [--backfill 60]

Loads the FROZEN model + scaler + calibrator + feature list, then for the
tracker universe:
  1. reconcile: mark prior predictions whose outcomes are now known
  2. predict:   build causal features for the latest session, predict next-session
                direction + calibrated confidence for each ticker
  3. write:     append to docs/data/prediction_log.json, recompute per-ticker and
                aggregate hit-rates, paper-portfolio value, streaks, calibration,
                market mood, and emit docs/data/predictions.json for the table

Does NOT retrain. Retraining is a separate, deliberate, walk-forward-validated
step. The prediction log is append-only — predictions made *before* outcomes are
known are the strongest, un-cherry-pickable evidence (references/webapp.md).
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import utils
from .features.build import SECTOR, GROUPS
from .models import prep
from .models.train import load_bundle, predict_proba

log = utils.get_logger("predict")

# human labels for the per-prediction "why"
_LABELS = {
    "sent_mean": "sentiment", "sent_momentum": "sentiment momentum",
    "share_pos": "bullish share", "share_neg": "bearish share",
    "post_volume": "post volume", "put_call_ratio": "put/call ratio",
    "implied_vol": "implied vol", "short_interest": "short interest",
    "rsi_14": "RSI", "macd": "MACD", "vix_level": "VIX", "attn_index": "attention",
    "mkt_ret_1": "market return",
}


def _feature_panel(cfg: dict, tickers: list[str]) -> pd.DataFrame:
    frames = []
    for t in tickers:
        path = utils.p(cfg, "processed") / "features" / f"{t}.csv"
        if path.exists():
            frames.append(pd.read_csv(path, parse_dates=["date"]))
    if not frames:
        raise FileNotFoundError("No feature files; run the build pipeline first.")
    return pd.concat(frames, ignore_index=True).sort_values(["date", "ticker"])


def _threshold(cfg: dict) -> float:
    summ = utils.read_json(utils.p(cfg, "site_data") / "eval_summary.json", {})
    return float(summ.get("threshold", 0.5)) if summ else 0.5


def _why(bundle, importances, row_feats: dict, p_up: float, k: int = 3) -> list[str]:
    """Lightweight per-prediction drivers (true SHAP if importances came from
    SHAP; otherwise gain-weighted standardized features). Labeled as drivers."""
    cols = bundle["feature_cols"]
    mean = bundle["scaler"].mean_
    scale = bundle["scaler"].scale_
    imp = {c: v for c, v in importances}
    contribs = []
    for i, c in enumerate(cols):
        z = (row_feats.get(c, mean[i]) - mean[i]) / (scale[i] or 1.0)
        contribs.append((c, imp.get(c, 0.0) * z))
    contribs.sort(key=lambda kv: abs(kv[1]), reverse=True)
    out = []
    for c, val in contribs[:k]:
        label = _LABELS.get(c, c)
        arrow = "↑" if val > 0 else "↓"
        out.append(f"{arrow} {label}")
    return out


def reconcile_and_predict(cfg: dict, tickers: list[str], backfill: int) -> dict:
    bundle = load_bundle(cfg)
    cols = bundle["feature_cols"]
    thr = _threshold(cfg)
    imp_obj = utils.read_json(utils.p(cfg, "site_data") / "importances.json", {})
    importances = [tuple(x) for x in imp_obj.get("importances", [])]

    panel = _feature_panel(cfg, tickers)
    panel = panel.dropna(subset=[c for c in cols if c in panel.columns])
    sessions = np.sort(panel["date"].unique())
    if len(sessions) == 0:
        raise RuntimeError("No complete feature rows to predict on.")

    log_path = utils.ROOT / cfg["tracker"]["prediction_log"]
    plog = utils.read_json(log_path, default={"predictions": []}) or {"predictions": []}
    logged_dates = {(e["date"], e["ticker"]) for e in plog["predictions"]}
    last_logged = max((e["date"] for e in plog["predictions"]), default=None)

    # which sessions to log this run
    if not plog["predictions"]:
        # Seed the live track record from the start of the UNTOUCHED test window so
        # the public log is genuinely out-of-sample and matches the frozen eval.
        meta = utils.read_json(utils.p(cfg, "site_data") / "eval_summary.json", {})
        test_start = (meta.get("frozen_meta", {}) or {}).get("test_window", [None])[0]
        if test_start:
            seeded = [d for d in sessions
                      if str(pd.Timestamp(d).date()) >= test_start]
            to_log = seeded if seeded else list(sessions[-backfill:])
        else:
            to_log = list(sessions[-backfill:])
    else:
        to_log = [d for d in sessions if str(pd.Timestamp(d).date()) > (last_logged or "")]
        if len(to_log) == 0:
            to_log = sessions[-1:]                          # re-emit today's table

    # ---- predict & append ----
    for d in to_log:
        day = panel[panel["date"] == d]
        X = day[cols].to_numpy(float)
        p_up = predict_proba(bundle, X)
        for (_, r), pu in zip(day.iterrows(), p_up):
            key = (str(pd.Timestamp(d).date()), r["ticker"])
            if key in logged_dates:
                continue
            pred_up = bool(pu >= thr)
            actual_up = (int(r["y"]) == 1) if pd.notna(r["y"]) else None
            entry = {
                "date": key[0],
                "ticker": r["ticker"],
                "sector": SECTOR.get(r["ticker"], "other"),
                "pred_up": pred_up,
                "p_up": round(float(pu), 4),
                "confidence": round(float(max(pu, 1 - pu)), 4),
                "sent_mean": round(float(r.get("sent_mean", 0.0)), 4),
                "earnings_day": int(r.get("earnings_day", 0)),
                "why": _why(bundle, importances, r.to_dict(), pu) if importances else [],
                "actual_up": actual_up,
                "correct": (None if actual_up is None else int(pred_up == actual_up)),
                "realized_ret": (None if pd.isna(r.get("fwd_ret"))
                                 else round(float(r["fwd_ret"]), 5)),
            }
            plog["predictions"].append(entry)
            logged_dates.add(key)

    # ---- reconcile: fill outcomes that became known ----
    outcome = {}
    for t in tickers:
        sub = panel[panel["ticker"] == t]
        for _, r in sub.iterrows():
            if pd.notna(r["y"]):
                outcome[(str(pd.Timestamp(r["date"]).date()), t)] = (
                    int(r["y"] == 1), None if pd.isna(r.get("fwd_ret")) else float(r["fwd_ret"]))
    for e in plog["predictions"]:
        if e["actual_up"] is None and (e["date"], e["ticker"]) in outcome:
            au, ret = outcome[(e["date"], e["ticker"])]
            e["actual_up"] = au
            e["correct"] = int(e["pred_up"] == au)
            e["realized_ret"] = None if ret is None else round(ret, 5)

    plog["predictions"].sort(key=lambda e: (e["date"], e["ticker"]))
    plog["updated_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    plog["data_mode"] = cfg["data"]["mode"]
    utils.write_json(log_path, plog)

    latest = str(pd.Timestamp(sessions[-1]).date())
    _emit_dashboard(cfg, plog, panel, bundle, latest)
    return plog


# --------------------------------------------------------------------------- #
# Dashboard JSON
# --------------------------------------------------------------------------- #
def _hit_rates(predictions: list[dict]) -> tuple[dict, float, int]:
    done = [e for e in predictions if e["correct"] is not None]
    per = {}
    for e in done:
        per.setdefault(e["ticker"], []).append(e["correct"])
    per_rate = {t: {"hit_rate": round(float(np.mean(v)), 4), "n": len(v)}
                for t, v in per.items()}
    agg = round(float(np.mean([e["correct"] for e in done])), 4) if done else None
    return per_rate, agg, len(done)


def _paper_portfolio(cfg: dict, predictions: list[dict]) -> dict:
    """$start follows the model's long/flat equal-weight signals vs buy-and-hold."""
    start = cfg["tracker"]["paper_start_cash"]
    cost = cfg["backtest"]["transaction_cost_bps"] / 1e4
    done = [e for e in predictions if e["correct"] is not None and e["realized_ret"] is not None]
    by_date: dict[str, list[dict]] = {}
    for e in done:
        by_date.setdefault(e["date"], []).append(e)

    dates = sorted(by_date)
    strat, bh = start, start
    s_curve, b_curve = [], []
    prev_held: set = set()
    for d in dates:
        rows = by_date[d]
        held = {e["ticker"] for e in rows if e["pred_up"]}
        held_rets = [e["realized_ret"] for e in rows if e["pred_up"]]
        s_ret = float(np.mean(held_rets)) if held_rets else 0.0
        turnover = len(held.symmetric_difference(prev_held)) / max(len(rows), 1)
        s_ret -= turnover * cost
        prev_held = held
        b_ret = float(np.mean([e["realized_ret"] for e in rows]))
        strat *= (1 + s_ret)
        bh *= (1 + b_ret)
        s_curve.append(round(strat, 2)); b_curve.append(round(bh, 2))
    return {
        "dates": dates,
        "strategy": s_curve,
        "buy_hold": b_curve,
        "start_cash": start,
        "strategy_value": round(strat, 2),
        "buy_hold_value": round(bh, 2),
    }


def _streaks_and_board(per_rate: dict, predictions: list[dict]) -> dict:
    # current streak per ticker (most recent consecutive correct)
    streaks = {}
    by_t: dict[str, list[dict]] = {}
    for e in predictions:
        if e["correct"] is not None:
            by_t.setdefault(e["ticker"], []).append(e)
    for t, es in by_t.items():
        es.sort(key=lambda e: e["date"])
        s = 0
        for e in reversed(es):
            if e["correct"] == 1:
                s += 1
            else:
                break
        streaks[t] = s
    ranked = sorted(per_rate.items(), key=lambda kv: kv[1]["hit_rate"], reverse=True)
    best = [{"ticker": t, **v} for t, v in ranked[:5]]
    worst = [{"ticker": t, **v} for t, v in ranked[-5:]]
    top_streak = max(streaks.items(), key=lambda kv: kv[1], default=(None, 0))
    return {"best": best, "worst": worst, "streaks": streaks,
            "top_streak": {"ticker": top_streak[0], "len": top_streak[1]}}


def _calibration_live(predictions: list[dict], bins=10) -> dict:
    done = [e for e in predictions if e["correct"] is not None]
    if not done:
        return {"pred_prob": [], "obs_freq": [], "counts": []}
    p = np.array([e["confidence"] if e["pred_up"] else 1 - e["confidence"] for e in done])
    # confidence is P(predicted class); convert to P(up) for the curve
    p_up = np.array([e["p_up"] for e in done])
    y = np.array([e["actual_up"] for e in done])
    edges = np.linspace(0, 1, bins + 1)
    xs, ys, ns = [], [], []
    for i in range(bins):
        m = (p_up >= edges[i]) & (p_up < edges[i + 1])
        if m.sum() > 0:
            xs.append(round(float(p_up[m].mean()), 3))
            ys.append(round(float(y[m].mean()), 3))
            ns.append(int(m.sum()))
    return {"pred_prob": xs, "obs_freq": ys, "counts": ns}


def _market_mood(panel: pd.DataFrame, latest: str, predictions: list[dict]) -> dict:
    day = panel[panel["date"] == pd.Timestamp(latest)]
    mood = float(day["sent_mean"].mean()) if len(day) else 0.0
    movers = (day[["ticker", "sent_momentum"]].sort_values("sent_momentum")
              if "sent_momentum" in day else pd.DataFrame())
    today = [e for e in predictions if e["date"] == latest]
    sector_dir: dict[str, list[int]] = {}
    for e in today:
        sector_dir.setdefault(e["sector"], []).append(1 if e["pred_up"] else 0)
    heatmap = {s: round(float(np.mean(v)), 3) for s, v in sector_dir.items()}
    return {
        "as_of": latest,
        "universe_sentiment": round(mood, 4),
        "top_bullish": (movers.tail(3)["ticker"].tolist() if len(movers) else []),
        "top_bearish": (movers.head(3)["ticker"].tolist() if len(movers) else []),
        "upcoming_earnings": [e["ticker"] for e in today if e["earnings_day"] == 1],
        "sector_heatmap": heatmap,
    }


def _recent_sentiment(panel: pd.DataFrame, ticker: str, n=20) -> list[float]:
    sub = panel[panel["ticker"] == ticker].sort_values("date").tail(n)
    return [round(float(x), 4) for x in sub.get("sent_mean", pd.Series(dtype=float))]


def _emit_dashboard(cfg, plog, panel, bundle, latest):
    site = utils.p(cfg, "site_data")
    preds = plog["predictions"]
    per_rate, agg, n_done = _hit_rates(preds)
    conv_thr = float(cfg["tracker"].get("conviction_threshold", 0.58))
    big_move = cfg["target"]["type"] == "big_move"

    # Headline metric & baseline are TARGET-AWARE:
    #  - direction: accuracy vs the ~50% coin-flip.
    #  - big_move:  PRECISION on flagged calls (when it says 'big', was it?) vs the
    #               base rate of big-move days (rare event — 50% is the wrong bar).
    baseline = 0.5
    if big_move:
        done = [e for e in preds if e["correct"] is not None]
        flagged = [e for e in done if e["pred_up"]]
        agg = round(float(np.mean([e["correct"] for e in flagged])), 4) if flagged else None
        baseline = round(float(np.mean([int(e["actual_up"]) for e in done])), 4) if done else None
        n_done = len(flagged)

    # latest close per ticker — lets the in-browser paper-trading game price trades
    latest_close = (panel[panel["date"] == pd.Timestamp(latest)]
                    .set_index("ticker")["close"].to_dict())

    # For big-move we rank by P(big move) = p_up; for direction by confidence.
    def rank_score(e):
        return e["p_up"] if big_move else e["confidence"]

    today_rows = sorted([e for e in preds if e["date"] == latest], key=rank_score, reverse=True)
    # For big-move, absolute probabilities are low (big moves are rare), so a
    # focused radar highlights TODAY's top slice by rank, not a fixed threshold.
    n_today = len(today_rows)
    elevated_cut = max(1, int(round(0.20 * n_today)))   # top ~20% = "elevated"
    conv_cut = max(1, int(round(0.07 * n_today)))       # top ~7%  = "high"
    watchlist = []
    for rank_i, e in enumerate(today_rows):
        pr = per_rate.get(e["ticker"], {"hit_rate": None, "n": 0})
        if big_move:
            e = {**e, "_flagged": rank_i < elevated_cut, "_conv": rank_i < conv_cut}
        watchlist.append({
            "ticker": e["ticker"], "sector": e["sector"],
            # direction model: ▲/▼.  big-move model: probability of an outsized move.
            "direction": "▲" if e["pred_up"] else "▼",
            "pred_up": e["pred_up"], "confidence": e["confidence"], "p_up": e["p_up"],
            "big_move_prob": e["p_up"],
            "flagged": bool(e["_flagged"]) if big_move else bool(e["pred_up"]),
            "conviction": bool(e["_conv"]) if big_move else bool(rank_score(e) >= conv_thr),
            "price": round(float(latest_close.get(e["ticker"], 0.0)), 2),
            "sentiment": e["sent_mean"], "sentiment_spark": _recent_sentiment(panel, e["ticker"]),
            "hit_rate": pr["hit_rate"], "n_predictions": pr["n"],
            "why": e.get("why", []), "earnings_day": e["earnings_day"],
        })

    predictions_json = {
        "as_of": latest,
        "data_mode": cfg["data"]["mode"],
        "target_type": cfg["target"]["type"],
        "aggregate_hit_rate": agg,
        "n_reconciled": n_done,
        "baseline": baseline,
        "watchlist": watchlist,
        "disclaimer": ("Experimental volatility radar — flags stocks likely to make an "
                       "outsized move (either direction). Not a buy signal, not financial advice."
                       if big_move else
                       "Experimental directional signals — not financial advice. Backtest ≠ live."),
        "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    utils.write_json(site / "predictions.json", predictions_json)
    utils.write_json(site / "portfolio.json", _paper_portfolio(cfg, preds))
    board = _streaks_and_board(per_rate, preds)
    board.update({"aggregate_hit_rate": agg, "n_reconciled": n_done,
                  "per_ticker": per_rate})
    utils.write_json(site / "scoreboard.json", board)
    utils.write_json(site / "calibration_live.json", _calibration_live(preds))
    utils.write_json(site / "market_mood.json", _market_mood(panel, latest, preds))
    log.info("Dashboard JSON written. as_of=%s aggregate_hit_rate=%s (n=%d)",
             latest, agg, n_done)


def run(cfg: dict, tickers: list[str] | None = None, backfill: int = 60) -> dict:
    utils.set_seed(cfg["project"]["seed"])
    tickers = tickers or cfg["universe"]
    # only tickers that actually have built features
    avail = [t for t in tickers
             if (utils.p(cfg, "processed") / "features" / f"{t}.csv").exists()]
    if not avail:
        raise FileNotFoundError("No built features for requested tickers.")
    log.info("Daily refresh over %d ticker(s); backfill=%d", len(avail), backfill)
    return reconcile_and_predict(cfg, avail, backfill)


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily reconcile + predict + publish JSON")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--tickers", default=None)
    ap.add_argument("--backfill", type=int, default=60,
                    help="sessions of track record to seed when the log is empty")
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = cfg["universe"] if args.universe else cfg["universe"]
    run(cfg, tickers, args.backfill)


if __name__ == "__main__":
    main()
