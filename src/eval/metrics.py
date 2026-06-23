"""Classification metrics that mean something (references/methodology.md).

Always reported against baselines, never in isolation.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)


def classification_metrics(y_true, y_pred, p_pos=None) -> dict:
    m = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "n": int(len(y_true)),
        "up_rate": float(np.mean(y_true)),
    }
    if p_pos is not None and len(np.unique(y_true)) > 1:
        m["roc_auc"] = float(roc_auc_score(y_true, p_pos))
    else:
        m["roc_auc"] = float("nan")
    return m


def confusion(y_true, y_pred) -> list[list[int]]:
    return confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist()


def tune_threshold(y_true, p_pos, objective: str = "f1") -> float:
    """Pick the decision threshold on a VALIDATION set (never test).

    - 'f1'     : maximise F1 (good for balanced direction labels).
    - 'youden' : maximise TPR - FPR.
    - 'bigmove': flag the top ~2x-base-rate fraction by probability — a focused,
                 high-precision operating point for a 'most likely to move' radar
                 (F1-max collapses to near-zero recall; Youden over-flags).
    """
    y_true = np.asarray(y_true)
    if objective == "bigmove":
        base = float(np.mean(y_true)) if len(y_true) else 0.2
        frac = min(max(2.0 * base, 0.10), 0.5)        # flag this fraction of days
        return float(np.quantile(p_pos, 1.0 - frac))
    best_t, best_s = 0.5, -1.0
    lo, hi = (0.1, 0.9) if objective == "youden" else (0.3, 0.7)
    for t in np.linspace(lo, hi, 81):
        pred = (p_pos >= t).astype(int)
        if objective == "youden":
            tp = ((pred == 1) & (y_true == 1)).sum(); fn = ((pred == 0) & (y_true == 1)).sum()
            fp = ((pred == 1) & (y_true == 0)).sum(); tn = ((pred == 0) & (y_true == 0)).sum()
            tpr = tp / max(tp + fn, 1); fpr = fp / max(fp + tn, 1)
            s = tpr - fpr
        else:
            s = f1_score(y_true, pred, zero_division=0)
        if s > best_s:
            best_s, best_t = s, float(t)
    return best_t


def primary_metric(m: dict, target_type: str) -> float:
    """Headline metric per target: AUC for big-move (rare-event ranking quality),
    F1 for direction."""
    return m["roc_auc"] if target_type == "big_move" else m["f1"]
