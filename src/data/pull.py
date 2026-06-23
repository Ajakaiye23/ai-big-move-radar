"""Phase 1 — data acquisition.

    python -m src.data.pull --config config.yaml            # core_study tickers
    python -m src.data.pull --config config.yaml --universe  # full tracker universe
    python -m src.data.pull --tickers AAPL                    # explicit subset

Pulls prices + text for each ticker, persists immutable raw stores with
provenance sidecars. Incremental by design in live mode (only what's new), full
in offline mode (deterministic, so re-pulling is free and identical).
"""
from __future__ import annotations

import argparse

from .. import utils
from . import sources

log = utils.get_logger("data.pull")


def resolve_tickers(cfg: dict, args) -> list[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",")]
    return cfg["universe"] if args.universe else cfg["core_study"]


def run(cfg: dict, tickers: list[str]) -> None:
    utils.set_seed(cfg["project"]["seed"])
    log.info("Pulling %d ticker(s) in '%s' mode: %s",
             len(tickers), cfg["data"]["mode"], ", ".join(tickers))
    ok = 0
    for t in tickers:
        try:
            prices, pmeta = sources.get_prices(t, cfg)
            sources.save_raw(cfg, "prices", t, prices, pmeta)
            text, tmeta = sources.get_text(t, prices, cfg,
                                           prices_are_synthetic=(pmeta["source"] == "synthetic"))
            sources.save_raw(cfg, "text", t, text, tmeta)
            log.info("  %-6s prices=%d (%s)  text=%d (%s)",
                     t, len(prices), pmeta["source"], len(text), tmeta["source"])
            ok += 1
        except Exception as e:  # noqa: BLE001 — isolate per-ticker failures across a big universe
            log.warning("  %-6s SKIPPED (%s)", t, e)
    log.info("Raw data written to %s (%d/%d tickers)", utils.p(cfg, "raw"), ok, len(tickers))


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull raw prices + text")
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", action="store_true", help="pull the full tracker universe")
    ap.add_argument("--tickers", default=None, help="comma-separated explicit ticker list")
    args = ap.parse_args()
    cfg = utils.load_config(args.config)
    run(cfg, resolve_tickers(cfg, args))


if __name__ == "__main__":
    main()
