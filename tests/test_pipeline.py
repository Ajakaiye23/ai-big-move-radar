"""Smoke test: the whole thin pipeline runs end-to-end offline and produces a
frozen model + dashboard JSON. Guards the reproducibility claim in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import utils                       # noqa: E402
from src.data import align, pull            # noqa: E402
from src.features import build as feat       # noqa: E402
from src.sentiment import score             # noqa: E402


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    c = utils.load_config()
    c["data"]["mode"] = "offline"
    c["data"]["start"] = "2022-01-01"
    c["data"]["end"] = "2023-12-31"
    # Isolate ALL outputs to a temp dir so tests never clobber deployed artifacts.
    tmp = tmp_path_factory.mktemp("pipe")
    c["paths"] = {k: str(tmp / k) for k in ("raw", "processed", "artifacts", "reports")}
    c["paths"]["site_data"] = str(tmp / "site")
    c["tracker"]["prediction_log"] = str(tmp / "site" / "prediction_log.json")
    c["publish_readme"] = False
    return c


def test_end_to_end(cfg):
    tickers = ["AAPL", "NVDA", "TSLA"]
    pull.run(cfg, tickers)
    align.run(cfg, tickers)
    score.run(cfg, tickers)
    feat.run(cfg, tickers)

    from src.eval.report import run as eval_run
    summary = eval_run(cfg)

    # basic sanity: metrics exist and are in range
    acc = summary["metrics_table"]["model"]["accuracy"]
    assert 0.3 <= acc <= 0.95
    assert "sentiment_delta_f1" in summary["headline_ablation"]
    assert (utils.p(cfg, "artifacts") / "model_bundle.pkl").exists()
    assert (utils.p(cfg, "site_data") / "eval_summary.json").exists()


def test_predict_writes_dashboard_json(cfg):
    from src.predict import run as predict_run
    predict_run(cfg, tickers=["AAPL", "NVDA", "TSLA"])
    for f in ("predictions.json", "prediction_log.json", "portfolio.json",
              "scoreboard.json"):
        assert (utils.p(cfg, "site_data") / f).exists(), f


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
