"""Phase 6 — modeling.

    python -m src.models.train --config config.yaml [--universe]

Trains the primary XGBoost classifier on the headline feature set (all enabled
groups), with class-imbalance handling, validation-based early stopping, and
probability calibration so displayed confidence is meaningful. Persists a single
self-contained bundle (model + scaler + calibrator + ordered feature list +
provenance) that eval, the daily refresh, and any rerun load identically.

`fit_pipeline` / `predict_proba` are reused by the ablation so every variant
shares identical preprocessing — only the feature groups differ.
"""
from __future__ import annotations

import argparse
import pickle
from datetime import date

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from .. import utils
from . import prep
from .calibrator import Calibrator

log = utils.get_logger("models.train")


def build_model(cfg: dict, scale_pos_weight: float, params: dict | None = None):
    from xgboost import XGBClassifier

    x = {**cfg["model"]["xgb"], **(params or {})}
    return XGBClassifier(
        n_estimators=x["n_estimators"],
        max_depth=x["max_depth"],
        learning_rate=x["learning_rate"],
        subsample=x["subsample"],
        colsample_bytree=x["colsample_bytree"],
        min_child_weight=x["min_child_weight"],
        scale_pos_weight=scale_pos_weight if cfg["model"].get("class_weighting") else 1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        early_stopping_rounds=x.get("early_stopping_rounds", 40),
        random_state=cfg["project"]["seed"],
        n_jobs=4,
        tree_method="hist",
    )


# Hyperparameter search space (sampled randomly, evaluated on walk-forward folds).
_TUNE_SPACE = {
    "max_depth": [3, 4, 5, 6],
    "learning_rate": [0.01, 0.02, 0.03, 0.05, 0.1],
    "n_estimators": [200, 300, 400, 600],
    "subsample": [0.7, 0.8, 0.9],
    "colsample_bytree": [0.7, 0.8, 0.9],
    "min_child_weight": [1, 3, 5, 10],
}


def tune_params(cfg: dict, Xtr: np.ndarray, ytr: np.ndarray, spw: float) -> dict:
    """Random search over XGBoost params, scored by mean F1 across walk-forward
    folds on the TRAINING set only (never validation/test). Returns best params."""
    from sklearn.metrics import f1_score
    from sklearn.model_selection import TimeSeriesSplit

    if len(np.unique(ytr)) < 2 or len(ytr) < 120:
        return {}                              # too little data to tune reliably
    rng = np.random.default_rng(cfg["project"]["seed"])
    n_iter = int(cfg["model"].get("tune_iters", 12))
    tscv = TimeSeriesSplit(n_splits=3)
    best, best_score = {}, -1.0
    for _ in range(n_iter):
        cand = {k: rng.choice(v).item() for k, v in _TUNE_SPACE.items()}
        scores = []
        for tr, te in tscv.split(Xtr):
            if len(np.unique(ytr[tr])) < 2:
                continue
            m = build_model(cfg, spw, cand)
            m.set_params(early_stopping_rounds=None)
            m.fit(Xtr[tr], ytr[tr])
            scores.append(f1_score(ytr[te], m.predict(Xtr[te]), zero_division=0))
        s = float(np.mean(scores)) if scores else -1.0
        if s > best_score:
            best_score, best = s, cand
    log.info("Tuned params (walk-forward F1=%.3f): %s", best_score, best)
    return best


def fit_pipeline(cfg: dict, df: pd.DataFrame, enabled_groups: list[str] | None = None,
                 pooled: bool = True, tune: bool = False) -> dict:
    """Fit scaler -> model -> calibrator on a chronological split. Returns a
    bundle plus the held-out split so the caller can evaluate on test."""
    feature_cols = prep.select_features(cfg, enabled_groups, pooled=pooled)
    split = prep.chronological_split(df, cfg, feature_cols)

    Xtr, ytr = prep.xy(split.train, feature_cols)
    Xva, yva = prep.xy(split.val, feature_cols)

    scaler = StandardScaler().fit(Xtr)            # FIT ON TRAIN ONLY (leakage guard)
    Xtr_s, Xva_s = scaler.transform(Xtr), scaler.transform(Xva)

    pos = max(ytr.sum(), 1)
    spw = float((len(ytr) - pos) / pos)
    tuned = tune_params(cfg, Xtr_s, ytr, spw) if (tune and cfg["model"].get("tune")) else {}
    model = build_model(cfg, spw, tuned)
    if len(Xva_s) >= 20 and len(np.unique(yva)) > 1:
        model.fit(Xtr_s, ytr, eval_set=[(Xva_s, yva)], verbose=False)
    else:
        model.set_params(early_stopping_rounds=None)
        model.fit(Xtr_s, ytr)

    cal = Calibrator()
    if len(Xva_s):
        cal.fit(model.predict_proba(Xva_s)[:, 1], yva)

    return {
        "model": model,
        "scaler": scaler,
        "calibrator": cal,
        "feature_cols": feature_cols,
        "enabled_groups": enabled_groups or "all",
        "pooled": pooled,
        "target_type": cfg["target"]["type"],
        "split": split,
    }


def predict_proba(bundle: dict, X: np.ndarray) -> np.ndarray:
    """Calibrated P(up) for a raw feature matrix."""
    Xs = bundle["scaler"].transform(X)
    raw = bundle["model"].predict_proba(Xs)[:, 1]
    return bundle["calibrator"].transform(raw)


# --------------------------------------------------------------------------- #
# Train + freeze the headline model
# --------------------------------------------------------------------------- #
def run(cfg: dict, pooled: bool = True) -> dict:
    utils.set_seed(cfg["project"]["seed"])
    df = prep.load_pooled(cfg)
    bundle = fit_pipeline(cfg, df, enabled_groups=None, pooled=pooled, tune=True)
    split = bundle["split"]

    art = utils.p(cfg, "artifacts")
    # persist the full bundle (model + scaler + calibrator + feature list)
    persist = {k: bundle[k] for k in
               ("model", "scaler", "calibrator", "feature_cols",
                "enabled_groups", "pooled", "target_type")}
    with open(art / "model_bundle.pkl", "wb") as fh:
        pickle.dump(persist, fh)

    meta = {
        "frozen_date": str(date.today()),
        "config_hash": utils.config_hash(cfg),
        "data_mode": cfg["data"]["mode"],
        "target_type": cfg["target"]["type"],
        "horizon_days": cfg["target"]["horizon_days"],
        "model_scope": cfg["tracker"]["model_scope"],
        "feature_cols": bundle["feature_cols"],
        "n_train": int(len(split.train)),
        "n_val": int(len(split.val)),
        "n_test": int(len(split.test)),
        "train_window": [str(split.train["date"].min().date()),
                         str(split.train["date"].max().date())],
        "test_window": [str(split.test["date"].min().date()),
                        str(split.test["date"].max().date())],
        "scorer": (utils.read_json(utils.p(cfg, "processed") / "sentiment" / "_scorer.json",
                                   {}) or {}).get("scorer", "unknown"),
    }
    utils.write_json(art / "meta.json", meta)
    utils.write_json(art / "feature_list.json", bundle["feature_cols"])

    log.info("Trained headline model: n_train=%d n_val=%d n_test=%d",
             meta["n_train"], meta["n_val"], meta["n_test"])
    log.info("Frozen artifacts -> %s (config %s)", art, meta["config_hash"])
    return bundle


def load_bundle(cfg: dict) -> dict:
    art = utils.p(cfg, "artifacts")
    with open(art / "model_bundle.pkl", "rb") as fh:
        return pickle.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser(description="Train + freeze the XGBoost model")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true",
                    help="(informational) the pooled model already trains on all built tickers")
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    run(cfg, pooled=(cfg["tracker"]["model_scope"] == "pooled"))


if __name__ == "__main__":
    main()
