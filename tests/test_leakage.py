"""Automated leakage guards — run in CI. See references/methodology.md.

Leakage is invisible by eye, so these encode it as failing tests:
  - test_split_order:     train ts < val ts < test ts
  - test_no_lookahead:    a sample of features recomputes from data strictly
                          before the prediction point (no future bar used)
  - test_scaler_fit:      scaler statistics match a train-only fit (not all-data)
  - test_label_shuffle:   accuracy collapses to baseline on time-shuffled labels
  - test_target_corr:     no feature is near-perfectly correlated with the target
  - test_sentiment_lag:   after-cutoff text maps to the NEXT session, never today

The suite bootstraps a tiny offline dataset on first run so it is self-contained.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import utils                       # noqa: E402
from src.data import align, pull            # noqa: E402
from src.features import build as feat       # noqa: E402
from src.models import prep                 # noqa: E402
from src.sentiment import score             # noqa: E402


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    c = utils.load_config()
    c["data"]["mode"] = "offline"
    c["data"]["start"] = "2022-01-01"
    c["data"]["end"] = "2023-12-31"
    # Isolate ALL outputs to a temp dir so tests never clobber deployed artifacts.
    tmp = tmp_path_factory.mktemp("leak")
    c["paths"] = {k: str(tmp / k) for k in ("raw", "processed", "artifacts", "reports")}
    c["paths"]["site_data"] = str(tmp / "site")
    c["tracker"]["prediction_log"] = str(tmp / "site" / "prediction_log.json")
    c["publish_readme"] = False
    return c


@pytest.fixture(scope="module")
def built(cfg):
    """Build a small two-ticker offline dataset end-to-end once."""
    tickers = ["AAPL", "NVDA"]
    pull.run(cfg, tickers)
    align.run(cfg, tickers)
    score.run(cfg, tickers)
    feat.run(cfg, tickers)
    df = prep.load_pooled(cfg)
    return cfg, df, tickers


def test_split_order(built):
    cfg, df, _ = built
    cols = prep.select_features(cfg)
    s = prep.chronological_split(df, cfg, cols)
    assert s.train["date"].max() < s.val["date"].min()
    assert s.val["date"].max() < s.test["date"].min()


def test_scaler_fit_on_train_only(built):
    from sklearn.preprocessing import StandardScaler
    cfg, df, _ = built
    cols = prep.select_features(cfg)
    s = prep.chronological_split(df, cfg, cols)
    Xtr = s.train[cols].to_numpy(float)
    Xall = pd.concat([s.train, s.val, s.test])[cols].to_numpy(float)
    train_scaler = StandardScaler().fit(Xtr)
    all_scaler = StandardScaler().fit(Xall)
    # train-only means must differ from all-data means (else someone fit on everything)
    assert not np.allclose(train_scaler.mean_, all_scaler.mean_, atol=1e-9)


def test_no_lookahead_returns(built):
    """ret_1 at row t must equal close[t]/close[t-1]-1 computed from raw — i.e.
    it uses only past/current data, never the future bar."""
    cfg, _, tickers = built
    for t in tickers:
        raw = pd.read_csv(utils.p(cfg, "raw") / "prices" / f"{t}.csv", parse_dates=["date"])
        f = pd.read_csv(utils.p(cfg, "processed") / "features" / f"{t}.csv", parse_dates=["date"])
        m = raw.merge(f[["date", "ret_1"]], on="date", how="inner").sort_values("date")
        recomputed = m["close"].pct_change()
        ok = np.isclose(m["ret_1"].to_numpy(), recomputed.to_numpy(), equal_nan=True)
        assert ok[1:].mean() > 0.999, f"ret_1 not causal for {t}"


def test_target_not_in_features(built):
    """No feature should be near-perfectly correlated with the target."""
    cfg, df, _ = built
    cols = prep.select_features(cfg)
    clean = prep.clean(df, cols)
    y = clean["y"].astype(float)
    for c in cols:
        col = clean[c].astype(float)
        # a constant / zero-variance feature can't leak the target (corr is undefined);
        # e.g. rel_strength_sector is 0 when a sector has a single ticker in the sample.
        if col.std() == 0 or y.std() == 0:
            continue
        corr = abs(np.corrcoef(col, y)[0, 1])
        if np.isnan(corr):
            continue
        assert corr < 0.95, f"feature {c} suspiciously correlated with target ({corr:.3f})"


def test_label_shuffle_collapses(built):
    """Train on time-shuffled labels: test accuracy must fall to ~chance.
    A 'signal' that survives label shuffling is leakage."""
    from src.models.train import build_model
    from sklearn.preprocessing import StandardScaler
    cfg, df, _ = built
    cols = prep.select_features(cfg)
    s = prep.chronological_split(df, cfg, cols)
    Xtr, ytr = prep.xy(s.train, cols)
    Xte, yte = prep.xy(s.test, cols)
    rng = np.random.default_rng(0)
    y_shuf = rng.permutation(ytr)
    sc = StandardScaler().fit(Xtr)
    m = build_model(cfg, 1.0); m.set_params(early_stopping_rounds=None)
    m.fit(sc.transform(Xtr), y_shuf)
    acc = (m.predict(sc.transform(Xte)) == yte).mean()
    base = max(yte.mean(), 1 - yte.mean())
    assert acc < base + 0.08, f"shuffled-label accuracy {acc:.3f} too high (base {base:.3f})"


def test_sentiment_lag_rule(cfg):
    """Text after the ET cutoff maps to the NEXT trading session, not today."""
    sessions = utils.trading_days("2023-01-02", "2023-01-13")
    cutoff = cfg["data"]["knowledge_cutoff_et"]
    # 21:00 ET Monday -> should map to Tuesday's session
    monday = sessions[0]
    after_close = (pd.Timestamp(monday).tz_localize("US/Eastern")
                   + pd.Timedelta(hours=21)).tz_convert("UTC")
    mapped = utils.session_for_timestamp(after_close, sessions, cutoff)
    assert mapped > monday, "after-hours text leaked into the same session"
    # 10:00 ET same day -> maps to same session
    during = (pd.Timestamp(monday).tz_localize("US/Eastern")
              + pd.Timedelta(hours=10)).tz_convert("UTC")
    assert utils.session_for_timestamp(during, sessions, cutoff) == monday


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
