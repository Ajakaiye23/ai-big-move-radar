"""The baselines you must beat (references/methodology.md).

A model "works" only relative to these. They are implemented as first-class
predictors and reported in the same table as the real model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def persistence(test_df: pd.DataFrame, target_type: str = "binary") -> np.ndarray:
    """Predict next label = last observed label.

    - direction: predict next direction = last direction (sign of ret_1).
    - big_move:  predict 'big' if the last realized move was 'big' (y shifted) —
      volatility clusters, so this is a genuinely hard baseline to beat.
    Both use only causal information.
    """
    if target_type == "big_move":
        return test_df["y"].shift(1).fillna(0).astype(int).to_numpy()
    last_dir = (test_df["ret_1"].fillna(0) > 0).astype(int)
    return last_dir.to_numpy()


def majority_class(train_y: np.ndarray, n: int) -> np.ndarray:
    """Always predict the most common class in the TRAINING set."""
    maj = int(round(train_y.mean())) if len(train_y) else 1
    return np.full(n, maj, dtype=int)


def buy_and_hold_returns(test_df: pd.DataFrame) -> np.ndarray:
    """Per-row realized forward return for the always-long economic baseline."""
    return test_df["fwd_ret"].fillna(0).to_numpy()
