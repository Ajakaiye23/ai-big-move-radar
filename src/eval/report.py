"""Phase 7 — evaluation, ablation, backtest, explainability.

    python -m src.eval.report --config config.yaml

Loads the FROZEN model and evaluates once on the untouched test period:
  - metrics table: model vs persistence / majority / buy-and-hold
  - confusion matrix
  - feature-group ablation (the headline) + walk-forward sentiment delta
  - backtest equity curve vs buy-and-hold, after costs
  - probability calibration curve
  - SHAP (or XGBoost gain) feature attribution
  - per-ticker AND aggregate test hit-rate (aggregate is the honest headline)

Writes JSON to docs/data/ (read by the dashboard) and static figures to
docs/assets/, then refreshes reports/model_card.md and the README headline.
"""
from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .. import utils  # noqa: E402
from ..models import baselines, prep  # noqa: E402
from ..models.train import load_bundle, predict_proba, run as train_run  # noqa: E402
from . import ablation as ablation_mod  # noqa: E402
from .backtest import backtest_portfolio, volatility_eval  # noqa: E402
from .metrics import (classification_metrics, confusion,  # noqa: E402
                      primary_metric, tune_threshold)

log = utils.get_logger("eval.report")


def _get_bundle_and_split(cfg: dict):
    try:
        bundle = load_bundle(cfg)
    except FileNotFoundError:
        log.info("No frozen model found; training one now.")
        train_run(cfg, pooled=(cfg["tracker"]["model_scope"] == "pooled"))
        bundle = load_bundle(cfg)
    df = prep.load_pooled(cfg)
    split = prep.chronological_split(df, cfg, bundle["feature_cols"])
    return bundle, split, df


def _calibration_curve(y_true, p_pos, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    xs, ys, ns = [], [], []
    for i in range(bins):
        m = (p_pos >= edges[i]) & (p_pos < edges[i + 1])
        if m.sum() > 0:
            xs.append(float(p_pos[m].mean()))
            ys.append(float(np.mean(np.asarray(y_true)[m])))
            ns.append(int(m.sum()))
    return {"pred_prob": xs, "obs_freq": ys, "counts": ns}


def _importances(bundle, split):
    """SHAP mean|value| if available, else XGBoost gain importances."""
    cols = bundle["feature_cols"]
    Xte, _ = prep.xy(split.test, cols)
    Xs = bundle["scaler"].transform(Xte)
    try:
        import shap
        expl = shap.TreeExplainer(bundle["model"])
        sv = expl.shap_values(Xs)
        if isinstance(sv, list):
            sv = sv[-1]
        imp = np.abs(sv).mean(axis=0)
        method = "shap"
    except Exception as e:  # noqa: BLE001
        log.info("SHAP unavailable (%s); using XGBoost gain importances", e)
        imp = np.asarray(bundle["model"].feature_importances_, dtype=float)
        method = "xgb_gain"
    order = np.argsort(imp)[::-1]
    return method, [(cols[i], float(imp[i])) for i in order]


def _fig_backtest(bt, path):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    if bt.get("kind") == "big_move":
        ax.plot(bt["strategy_pnl"], label="Bet on flagged days (net of premium)", lw=2)
        ax.plot(bt["always_straddle_pnl"], label="Bet every day", lw=2, ls="--")
        ax.axhline(0, color="gray", lw=0.8)
        ax.set_title("Big-move 'straddle' P&L: flagged days vs every day")
        ax.set_xlabel("Trading day in test period"); ax.set_ylabel("Cumulative P&L (return units)")
    else:
        ax.plot(bt["strategy_equity"], label="Model (long/flat, after costs)", lw=2)
        ax.plot(bt["buy_hold_equity"], label="Buy & hold (equal weight)", lw=2, ls="--")
        ax.set_title("Backtest: model vs buy-and-hold (test period)")
        ax.set_xlabel("Trading day in test period"); ax.set_ylabel("Equity (×)")
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def _fig_calibration(cal, path):
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], ls=":", color="gray", label="Perfect")
    ax.plot(cal["pred_prob"], cal["obs_freq"], "o-", label="Model")
    ax.set_title("Calibration: predicted vs observed P(up)")
    ax.set_xlabel("Predicted probability"); ax.set_ylabel("Observed frequency")
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def _fig_importances(imps, method, path):
    top = imps[:15][::-1]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh([k for k, _ in top], [v for _, v in top], color="#2b8a78")
    ax.set_title(f"Feature attribution ({method})")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def _fig_ablation(ab, path):
    rows = [("market-only", ab["market_only"]["f1"]),
            ("market+sentiment", ab["market_plus_sentiment"]["f1"]),
            ("all groups", ab["all_groups"]["f1"])]
    for g, m in ab["market_plus_each_group"].items():
        rows.append((f"market+{g}", m["f1"]))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar([r[0] for r in rows], [r[1] for r in rows], color="#3b6ea5")
    ax.set_ylabel("Test F1"); ax.set_title("Feature-group ablation (test F1)")
    plt.xticks(rotation=35, ha="right"); ax.grid(alpha=0.3, axis="y")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def run(cfg: dict) -> dict:
    utils.set_seed(cfg["project"]["seed"])
    bundle, split, df = _get_bundle_and_split(cfg)
    cols = bundle["feature_cols"]
    assets = utils.p(cfg, "site_data").parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    site = utils.p(cfg, "site_data")

    # ---- model on test, threshold tuned on val ----
    _obj = "bigmove" if cfg["target"]["type"] == "big_move" else "f1"
    Xva, yva = prep.xy(split.val, cols)
    Xte, yte = prep.xy(split.test, cols)
    thr = tune_threshold(yva, predict_proba(bundle, Xva), _obj) if len(yva) else 0.5
    p_te = predict_proba(bundle, Xte)
    pred = (p_te >= thr).astype(int)

    model_m = classification_metrics(yte, pred, p_te)

    ttype = cfg["target"]["type"]

    # ---- baselines ----
    base = {
        "persistence": classification_metrics(yte, baselines.persistence(split.test, ttype)),
        "majority_class": classification_metrics(
            yte, baselines.majority_class(prep.xy(split.train, cols)[1], len(yte))),
    }
    table = {"model": model_m, **base}
    beats = {k: model_m["accuracy"] - v["accuracy"] for k, v in base.items()}

    # ---- ablation ----
    ablation = ablation_mod.run_ablation(cfg, df, bundle["pooled"])

    # ---- backtest: long/flat for direction, straddle/captured-move for big_move ----
    if ttype == "big_move":
        bt = volatility_eval(split.test, pred)
    else:
        bt = backtest_portfolio(split.test, pred, cfg["backtest"]["transaction_cost_bps"],
                                cfg["backtest"]["trade_on"])

    # ---- calibration ----
    cal = _calibration_curve(yte, p_te)

    # ---- importances ----
    method, imps = _importances(bundle, split)

    # ---- per-ticker + aggregate hit-rate on test ----
    test = split.test.copy()
    test["pred"] = pred
    test["correct"] = (test["pred"] == test["y"]).astype(int)
    per_ticker = (test.groupby("ticker")["correct"].agg(["mean", "count"])
                  .rename(columns={"mean": "hit_rate", "count": "n"})
                  .round(4).reset_index().to_dict("records"))
    aggregate_hit = float(test["correct"].mean())

    # ---- figures ----
    _fig_backtest(bt, assets / "backtest.png")
    _fig_calibration(cal, assets / "calibration.png")
    _fig_importances(imps, method, assets / "importances.png")
    _fig_ablation(ablation, assets / "ablation.png")

    # ---- write JSON for dashboard / report ----
    summary = {
        "frozen_meta": utils.read_json(utils.p(cfg, "artifacts") / "meta.json", {}),
        "target_type": ttype,
        "threshold": thr,
        "metrics_table": table,
        "model_beats_baselines_accuracy": beats,
        "confusion_matrix": confusion(yte, pred),
        "aggregate_test_hit_rate": aggregate_hit,
        "per_ticker_test_hit_rate": per_ticker,
        "headline_ablation": {
            "metric": "roc_auc" if ttype == "big_move" else "f1",
            "market_only_f1": primary_metric(ablation["market_only"], ttype),
            "market_sentiment_f1": primary_metric(ablation["market_plus_sentiment"], ttype),
            "sentiment_delta_f1": (primary_metric(ablation["market_plus_sentiment"], ttype)
                                   - primary_metric(ablation["market_only"], ttype)),
            "walk_forward": ablation["sentiment_walk_forward"],
        },
        "backtest": {k: v for k, v in bt.items() if k not in ("dates",)},
    }
    utils.write_json(site / "ablation.json", ablation)
    utils.write_json(site / "calibration.json", cal)
    utils.write_json(site / "backtest.json", bt)
    utils.write_json(site / "importances.json",
                     {"method": method, "importances": imps[:25]})
    utils.write_json(site / "eval_summary.json", summary)

    _print_summary(summary, ablation)
    _write_model_card(cfg, summary, ablation, method)
    _update_readme(cfg, summary, ablation)
    log.info("Evaluation complete. Figures -> %s ; JSON -> %s", assets, site)
    return summary


def _print_summary(summary, ablation):
    t = summary["metrics_table"]
    log.info("── HONEST RESULTS (test period) ──")
    log.info("  model        acc=%.3f f1=%.3f auc=%.3f",
             t["model"]["accuracy"], t["model"]["f1"], t["model"]["roc_auc"])
    log.info("  persistence  acc=%.3f", t["persistence"]["accuracy"])
    log.info("  majority     acc=%.3f", t["majority_class"]["accuracy"])
    h = summary["headline_ablation"]
    log.info("  sentiment Δf1 (test): %+.4f  | walk-forward mean Δf1: %+.4f ± %.4f",
             h["sentiment_delta_f1"], h["walk_forward"]["mean"], h["walk_forward"]["std"])
    bt = summary["backtest"]
    if bt.get("kind") == "big_move":
        log.info("  flagged move above own-stock norm: %+.3f%% (vs %+.3f%% all days)",
                 bt["lift_vs_own_norm_flagged"] * 100, bt["lift_vs_own_norm_all"] * 100)
        log.info("  straddle P&L (per-stock premium): flagged %.3f vs every-day %.3f",
                 bt["strategy_total_pnl"], bt["always_total_pnl"])
    else:
        log.info("  backtest: strat %.1f%% vs B&H %.1f%% (after %d bps); Sharpe %.2f vs %.2f",
                 bt["strategy_total_return"] * 100, bt["buy_hold_total_return"] * 100,
                 int(bt["cost_bps"]), bt["strategy_sharpe"], bt["buy_hold_sharpe"])
    log.info("  aggregate test hit-rate: %.3f", summary["aggregate_test_hit_rate"])


def _backtest_md(bt: dict) -> str:
    if bt.get("kind") == "big_move":
        return (f"- Flagged days move **{bt['lift_vs_own_norm_flagged']*100:+.2f}%** above each stock's "
                f"own typical move (vs {bt['lift_vs_own_norm_all']*100:+.2f}% across all days)\n"
                f"- Straddle P&L (per-stock premium): betting only on flags **{bt['strategy_total_pnl']:+.3f}** "
                f"vs betting every day {bt['always_total_pnl']:+.3f}")
    return (f"- Strategy total return: {bt['strategy_total_return']*100:.1f}%  | "
            f"Sharpe {bt['strategy_sharpe']:.2f}  | MaxDD {bt['strategy_max_drawdown']*100:.1f}%\n"
            f"- Buy & hold: {bt['buy_hold_total_return']*100:.1f}%  | "
            f"Sharpe {bt['buy_hold_sharpe']:.2f}  | MaxDD {bt['buy_hold_max_drawdown']*100:.1f}%")


def _verdict(summary) -> str:
    beats = summary["model_beats_baselines_accuracy"]
    h = summary["headline_ablation"]
    sd = summary["sentiment_delta_f1"] if "sentiment_delta_f1" in summary else h["sentiment_delta_f1"]
    bt = summary["backtest"]
    parts = []
    if bt.get("kind") == "big_move":
        auc = summary["metrics_table"]["model"]["roc_auc"]
        lift = bt.get("lift_vs_own_norm_flagged", 0.0)
        parts.append(f"ranks big-move days at AUC {auc:.3f} (>0.5 = real signal)")
        parts.append(f"sentiment changed AUC by {sd:+.4f}")
        parts.append(f"flagged days move {lift*100:+.2f}pp above each stock's own norm"
                     if lift > 0 else "flagged days do NOT exceed each stock's own norm")
        return "; ".join(parts)
    beat_all = all(v > 0 for v in beats.values())
    parts.append("beats both baselines" if beat_all else "does NOT clearly beat all baselines")
    parts.append(f"sentiment changed test F1 by {sd:+.4f}")
    if True:
        parts.append("beats buy-and-hold after costs"
                     if bt["strategy_total_return"] > bt["buy_hold_total_return"]
                     else "does NOT beat buy-and-hold after costs")
    return "; ".join(parts)


def _write_model_card(cfg, summary, ablation, method):
    meta = summary["frozen_meta"]
    t = summary["metrics_table"]
    h = summary["headline_ablation"]
    big = cfg["target"]["type"] == "big_move"
    use = ("experimental **volatility / big-move radar** — flags stocks likely to make an outsized "
           "move (either direction). It does NOT predict direction (that's ~a coin flip) and is not a buy signal."
           if big else "experimental directional signal tracker")
    card = f"""# Model Card — AI {'Big-Move Radar' if big else 'Stock Sentiment Tracker'}

**Intended use:** {use} For research/education. **Not financial advice.**
**Not for:** real trading decisions, illiquid/small-cap names outside the universe.

- **Universe:** see `config.yaml` `universe`
- **Core study tickers:** {", ".join(cfg["core_study"])}
- **Target:** {"next-session BIG MOVE — |return| > %g x trailing-%dd vol (magnitude, not direction)" % (cfg['target'].get('big_move_k',1.5), cfg['target'].get('big_move_vol_window',60)) if big else "next-session direction"} (H={cfg['target']['horizon_days']}), `{cfg['target']['type']}`
- **Model scope:** {meta.get('model_scope')} (one model, ticker/sector as features)
- **Data mode:** `{meta.get('data_mode')}`  ({'SYNTHETIC data — mechanics demo, not a market finding' if meta.get('data_mode') == 'offline' else 'live sources'})
- **Sentiment scorer:** {meta.get('scorer')}
- **Training window:** {meta.get('train_window')}  (n_train={meta.get('n_train')})
- **Frozen test window:** {meta.get('test_window')}  (n_test={meta.get('n_test')})
- **Frozen date:** {meta.get('frozen_date')}  |  config `{meta.get('config_hash')}`

## Headline metrics vs baselines (untouched test period)
| Predictor | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|---|
| **Model** | {t['model']['accuracy']:.3f} | {t['model']['precision']:.3f} | {t['model']['recall']:.3f} | {t['model']['f1']:.3f} | {t['model']['roc_auc']:.3f} |
| Persistence | {t['persistence']['accuracy']:.3f} | {t['persistence']['precision']:.3f} | {t['persistence']['recall']:.3f} | {t['persistence']['f1']:.3f} | – |
| Majority class | {t['majority_class']['accuracy']:.3f} | {t['majority_class']['precision']:.3f} | {t['majority_class']['recall']:.3f} | {t['majority_class']['f1']:.3f} | – |

Aggregate test hit-rate: **{summary['aggregate_test_hit_rate']:.3f}** (vs ~0.50 chance).

## Feature-group ablation deltas (test F1 vs market-only)
- market-only F1: {ablation['market_only']['f1']:.3f}
- market + sentiment F1: {ablation['market_plus_sentiment']['f1']:.3f}  (**Δ {h['sentiment_delta_f1']:+.4f}**)
- walk-forward sentiment Δf1: **{h['walk_forward']['mean']:+.4f} ± {h['walk_forward']['std']:.4f}** over {h['walk_forward']['folds']} folds
- incremental value of each group (market + group):
""" + "".join(
        f"  - {g}: F1 {m['f1']:.3f} (Δ {m['delta_f1_vs_market']:+.4f})\n"
        for g, m in ablation["market_plus_each_group"].items()
    ) + f"""
## Economic test
{_backtest_md(summary['backtest'])}

## Explainability
Feature attribution via **{method}** (top features in `docs/assets/importances.png`).

## Verdict (honest)
{_verdict(summary)}.

## Known limitations & failure modes
- Selection bias (curated liquid/popular universe), fixed historical window.
- Sentiment coverage gaps and platform biases; after-hours text lagged to next session.
- Simple transaction-cost model; no slippage/latency/borrow costs.
- Multiple-comparisons risk across the universe — lead with the aggregate hit-rate, not per-ticker bests.
- Model decays as markets shift; retrain trigger: live hit-rate < {cfg['monitoring']['retrain_if_hitrate_below']} over {cfg['monitoring']['rolling_window_days']} days.
"""
    out = utils.p(cfg, "reports") / "model_card.md"
    out.write_text(card, encoding="utf-8")
    log.info("Model card -> %s", out)


def _update_readme(cfg, summary, ablation):
    if not cfg.get("publish_readme", True):
        return  # tests / isolated runs must not clobber the real README
    readme = utils.ROOT / "README.md"
    if not readme.exists():
        return
    txt = readme.read_text(encoding="utf-8")
    t = summary["metrics_table"]
    h = summary["headline_ablation"]
    block = (
        "<!-- AUTO-RESULTS:START -->\n"
        f"- **Data mode:** `{summary['frozen_meta'].get('data_mode')}` "
        f"({'synthetic mechanics demo' if summary['frozen_meta'].get('data_mode')=='offline' else 'live'}); "
        f"test window {summary['frozen_meta'].get('test_window')}\n"
        f"- **Model vs baselines (test accuracy):** model {t['model']['accuracy']:.3f} | "
        f"persistence {t['persistence']['accuracy']:.3f} | majority {t['majority_class']['accuracy']:.3f}\n"
        f"- **With vs without sentiment (test F1):** "
        f"{ablation['market_plus_sentiment']['f1']:.3f} vs {ablation['market_only']['f1']:.3f} "
        f"(Δ {h['sentiment_delta_f1']:+.4f}; walk-forward {h['walk_forward']['mean']:+.4f} ± {h['walk_forward']['std']:.4f})\n"
        f"- **Economic test:** {_backtest_md(summary['backtest']).replace(chr(10), '; ').replace('- ', '')}\n"
        f"- **Aggregate test hit-rate:** {summary['aggregate_test_hit_rate']:.3f}\n"
        f"- **Verdict:** {_verdict(summary)}\n"
        "<!-- AUTO-RESULTS:END -->"
    )
    import re
    if "<!-- AUTO-RESULTS:START -->" in txt:
        txt = re.sub(r"<!-- AUTO-RESULTS:START -->.*?<!-- AUTO-RESULTS:END -->",
                     block, txt, flags=re.S)
        readme.write_text(txt, encoding="utf-8")
        log.info("README headline updated.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate, ablate, backtest, explain")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    run(cfg)


if __name__ == "__main__":
    main()
