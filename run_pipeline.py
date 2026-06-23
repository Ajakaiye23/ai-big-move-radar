"""One-command end-to-end run: pull -> align -> sentiment -> features -> train
-> evaluate -> daily predict. Offline + deterministic by default.

    python run_pipeline.py                 # core_study tickers (prove the engine)
    python run_pipeline.py --universe      # full tracker universe (Phase 7.5 rollout)
    python run_pipeline.py --tickers AAPL  # explicit subset
"""
from __future__ import annotations

import argparse

from src import utils
from src.data import align, pull
from src.eval.report import run as eval_run
from src.features import build as feat
from src.models.train import run as train_run
from src.predict import run as predict_run
from src.sentiment import score

log = utils.get_logger("run_pipeline")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the whole pipeline end-to-end")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--tickers", default=None)
    ap.add_argument("--backfill", type=int, default=60)
    args = ap.parse_args()

    cfg = utils.load_config(args.config)
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = cfg["universe"] if args.universe else cfg["core_study"]

    log.info("=== Phase 1: pull ===");      pull.run(cfg, tickers)
    log.info("=== Phase 2: align ===");     align.run(cfg, tickers)
    log.info("=== Phase 3: sentiment ==="); score.run(cfg, tickers)
    log.info("=== Phase 4: features ===");  feat.run(cfg, tickers)
    log.info("=== Phase 6: train ===");     train_run(cfg, pooled=(cfg["tracker"]["model_scope"] == "pooled"))
    log.info("=== Phase 7: evaluate ===");  eval_run(cfg)
    log.info("=== Phase 8: daily predict ==="); predict_run(cfg, tickers, args.backfill)
    log.info("Done. Open docs/index.html (serve docs/ for the live tracker).")


if __name__ == "__main__":
    main()
