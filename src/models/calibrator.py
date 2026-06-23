"""Probability calibrator — kept in its own module so its pickle path is stable.

If this lived in train.py, running `python -m src.models.train` would pickle it
as `__main__.Calibrator`, and loading the bundle from another entry point (eval,
predict, the daily Action) would fail. A dedicated module always pickles as
`src.models.calibrator.Calibrator`, loadable everywhere.
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression


class Calibrator:
    """Isotonic probability calibration, fit on the VALIDATION fold (never test).

    Makes a displayed "70%" actually mean ~70%, and clips away literal 0/100%
    so confidence never looks like certainty.
    """

    def __init__(self):
        self.iso: IsotonicRegression | None = None

    def fit(self, p_pos: np.ndarray, y: np.ndarray) -> "Calibrator":
        if len(np.unique(y)) < 2 or len(y) < 30:
            self.iso = None  # too little / degenerate -> identity
            return self
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.iso.fit(p_pos, y)
        return self

    def transform(self, p_pos: np.ndarray) -> np.ndarray:
        out = p_pos if self.iso is None else self.iso.predict(p_pos)
        return np.clip(out, 0.02, 0.98)
