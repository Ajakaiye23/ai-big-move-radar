"""Dataset assembly, chronological splitting, and feature-group selection.

Shared by training, evaluation, ablation, and the leakage tests so they all use
EXACTLY the same preprocessing — the reproducibility guarantee that the app and
any rerun behave identically (references/reproducibility.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import utils
from ..features.build import GROUPS, POOLED_COLS

log = utils.get_logger("models.prep")


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame
    feature_cols: list[str]


def load_pooled(cfg: dict) -> pd.DataFrame:
    path = utils.p(cfg, "processed") / "features" / "_pooled.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values(["date", "ticker"]).reset_index(drop=True)


def load_ticker(cfg: dict, ticker: str) -> pd.DataFrame:
    path = utils.p(cfg, "processed") / "features" / f"{ticker}.csv"
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def built_groups(cfg: dict) -> list[str]:
    """Groups that were actually built (mode-dependent — live drops synthetic
    stubs). Falls back to all groups if the feature manifest is missing."""
    fg = utils.read_json(
        utils.p(cfg, "processed") / "features" / "feature_groups.json", {}) or {}
    active = fg.get("_active_groups")
    if active:
        return [g for g in active if g in GROUPS]
    return list(GROUPS.keys())


def select_features(cfg: dict, enabled_groups: list[str] | None = None,
                    pooled: bool = True) -> list[str]:
    """Resolve the ordered feature column list for the enabled groups. When no
    groups are named, use exactly the groups that were built for this mode."""
    if enabled_groups is None:
        enabled_groups = built_groups(cfg)
    cols: list[str] = []
    for g in enabled_groups:
        cols += GROUPS[g]
    if pooled:
        cols += POOLED_COLS
    return cols


def clean(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Drop unlabeled tail and indicator-warmup rows with missing features."""
    df = df[df["y"].notna()].copy()
    df["y"] = df["y"].astype(int)
    present = [c for c in feature_cols if c in df.columns]
    df = df.dropna(subset=present)
    return df.reset_index(drop=True)


def chronological_split(df: pd.DataFrame, cfg: dict,
                        feature_cols: list[str]) -> Split:
    """Oldest -> train, middle -> validation, newest -> test. The test period is
    the fixed evaluation window, untouched until the very end (methodology.md)."""
    df = clean(df, feature_cols)
    dates = np.sort(df["date"].unique())
    n = len(dates)
    test_f = cfg["split"]["test_fraction"]
    val_f = cfg["split"]["val_fraction"]
    test_start = dates[int(n * (1 - test_f))]
    val_start = dates[int(n * (1 - test_f - val_f))]

    train = df[df["date"] < val_start]
    val = df[(df["date"] >= val_start) & (df["date"] < test_start)]
    test = df[df["date"] >= test_start]

    # Optionally drop earnings outliers from TRAIN only (keep flagged in test).
    if cfg["model"].get("exclude_earnings_days") and "earnings_day" in train:
        before = len(train)
        train = train[train["earnings_day"] == 0]
        log.info("Excluded %d earnings-day rows from training", before - len(train))

    return Split(train.reset_index(drop=True), val.reset_index(drop=True),
                 test.reset_index(drop=True), feature_cols)


def xy(split_df: pd.DataFrame, feature_cols: list[str]):
    X = split_df[feature_cols].to_numpy(dtype=float)
    y = split_df["y"].to_numpy(dtype=int)
    return X, y
