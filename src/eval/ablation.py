"""The ablation — the headline result (references/methodology.md & modeling.md).

Answers not just "does sentiment help?" but "which feature groups help?" by
re-fitting the same model/splits/seed with different groups enabled and
comparing test metrics. The sentiment delta is repeated across walk-forward
folds so it isn't a single lucky split.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from .. import utils
from ..features.build import GROUPS
from ..models import prep
from ..models.train import build_model, fit_pipeline, predict_proba
from .metrics import classification_metrics, tune_threshold

log = utils.get_logger("eval.ablation")


def _threshold_obj(cfg: dict) -> str:
    return "bigmove" if cfg["target"]["type"] == "big_move" else "f1"


def evaluate_config(cfg: dict, df: pd.DataFrame, groups: list[str], pooled: bool) -> dict:
    """Fit on train, tune threshold on val, report on the fixed test period."""
    bundle = fit_pipeline(cfg, df, enabled_groups=groups, pooled=pooled)
    split = bundle["split"]
    Xva, yva = prep.xy(split.val, bundle["feature_cols"])
    Xte, yte = prep.xy(split.test, bundle["feature_cols"])
    thr = tune_threshold(yva, predict_proba(bundle, Xva), _threshold_obj(cfg)) if len(yva) else 0.5
    p_te = predict_proba(bundle, Xte)
    pred = (p_te >= thr).astype(int)
    m = classification_metrics(yte, pred, p_te)
    m["threshold"] = thr
    return m


def _fit_eval_fold(cfg, train_df, test_df, groups, pooled) -> float:
    """Fold score = AUC for big-move (stable, threshold-free), F1 for direction."""
    from sklearn.metrics import f1_score, roc_auc_score
    cols = prep.select_features(cfg, groups, pooled=pooled)
    tr = prep.clean(train_df, cols)
    te = prep.clean(test_df, cols)
    if len(tr) < 50 or len(te) < 10 or tr["y"].nunique() < 2 or te["y"].nunique() < 2:
        return float("nan")
    Xtr, ytr = prep.xy(tr, cols)
    Xte, yte = prep.xy(te, cols)
    scaler = StandardScaler().fit(Xtr)
    pos = max(ytr.sum(), 1)
    model = build_model(cfg, float((len(ytr) - pos) / pos))
    model.set_params(early_stopping_rounds=None)
    model.fit(scaler.transform(Xtr), ytr)
    p = model.predict_proba(scaler.transform(Xte))[:, 1]
    if cfg["target"]["type"] == "big_move":
        return float(roc_auc_score(yte, p))
    return float(f1_score(yte, (p >= 0.5).astype(int), zero_division=0))


def walk_forward_sentiment_delta(cfg: dict, df: pd.DataFrame, pooled: bool) -> dict:
    """Mean ± spread of the (market+sentiment − market-only) test-F1 delta across
    expanding walk-forward folds."""
    folds = cfg["split"].get("walk_forward_folds", 5)
    cols_all = prep.select_features(cfg, list(GROUPS.keys()), pooled=pooled)
    clean = prep.clean(df, cols_all)
    dates = np.sort(clean["date"].unique())
    if len(dates) < folds + 2:
        return {"folds": 0, "deltas": [], "mean": float("nan"), "std": float("nan")}

    tscv = TimeSeriesSplit(n_splits=folds)
    deltas, mkt_f1s, both_f1s = [], [], []
    for tr_idx, te_idx in tscv.split(dates):
        tr_dates, te_dates = dates[tr_idx], dates[te_idx]
        tr = clean[clean["date"].isin(tr_dates)]
        te = clean[clean["date"].isin(te_dates)]
        f1_mkt = _fit_eval_fold(cfg, tr, te, ["market"], pooled)
        f1_both = _fit_eval_fold(cfg, tr, te, ["market", "sentiment"], pooled)
        if not (np.isnan(f1_mkt) or np.isnan(f1_both)):
            deltas.append(f1_both - f1_mkt)
            mkt_f1s.append(f1_mkt)
            both_f1s.append(f1_both)
    return {
        "folds": len(deltas),
        "deltas": [round(d, 4) for d in deltas],
        "market_f1_mean": float(np.mean(mkt_f1s)) if mkt_f1s else float("nan"),
        "market_sentiment_f1_mean": float(np.mean(both_f1s)) if both_f1s else float("nan"),
        "mean": float(np.mean(deltas)) if deltas else float("nan"),
        "std": float(np.std(deltas)) if deltas else float("nan"),
    }


def run_ablation(cfg: dict, df: pd.DataFrame, pooled: bool) -> dict:
    # authoritative list of groups that were actually built (mode-dependent)
    available = [g for g in prep.built_groups(cfg)
                 if all(c in df.columns for c in GROUPS[g])]
    log.info("Ablating feature groups: %s", ", ".join(available))

    results = {}
    # headline contrasts
    results["market_only"] = evaluate_config(cfg, df, ["market"], pooled)
    results["market_plus_sentiment"] = evaluate_config(
        cfg, df, ["market", "sentiment"], pooled)
    results["all_groups"] = evaluate_config(cfg, df, available, pooled)

    # per-group: market + each single group, to see incremental value.
    # Scored by the target's PRIMARY metric (AUC for big-move, F1 for direction)
    # so the deltas are stable; key kept as delta_f1_vs_market for compatibility.
    from .metrics import primary_metric
    ttype = cfg["target"]["type"]
    per_group = {}
    base = primary_metric(results["market_only"], ttype)
    for g in available:
        if g == "market":
            continue
        m = evaluate_config(cfg, df, ["market", g], pooled)
        per_group[g] = {**m, "delta_f1_vs_market": primary_metric(m, ttype) - base,
                        "primary_metric": "roc_auc" if ttype == "big_move" else "f1"}
    results["market_plus_each_group"] = per_group

    # robustness: sentiment delta across walk-forward folds
    results["sentiment_walk_forward"] = walk_forward_sentiment_delta(cfg, df, pooled)
    return results
