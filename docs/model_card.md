# Model Card — AI Big-Move Radar

**Intended use:** experimental **volatility / big-move radar** — flags stocks likely to make an outsized move (either direction). It does NOT predict direction (that's ~a coin flip) and is not a buy signal. For research/education. **Not financial advice.**
**Not for:** real trading decisions, illiquid/small-cap names outside the universe.

- **Universe:** see `config.yaml` `universe`
- **Core study tickers:** AAPL, TSLA, NVDA, AMD
- **Target:** next-session BIG MOVE — |return| > 1.5 x trailing-60d vol (magnitude, not direction) (H=1), `big_move`
- **Model scope:** pooled (one model, ticker/sector as features)
- **Data mode:** `live`  (live sources)
- **Sentiment scorer:** finbert
- **Training window:** ['2025-12-02', '2026-04-20']  (n_train=3895)
- **Frozen test window:** ['2026-05-19', '2026-06-17']  (n_test=861)
- **Frozen date:** 2026-06-23  |  config `d6defb28894e`

## Headline metrics vs baselines (untouched test period)
| Predictor | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|---|
| **Model** | 0.405 | 0.203 | 0.787 | 0.323 | 0.578 |
| Persistence | 0.724 | 0.232 | 0.232 | 0.232 | – |
| Majority class | 0.820 | 0.000 | 0.000 | 0.000 | – |

Aggregate test hit-rate: **0.405** (vs ~0.50 chance).

## Feature-group ablation deltas (test F1 vs market-only)
- market-only F1: 0.308
- market + sentiment F1: 0.313  (**Δ +0.0051**)
- walk-forward sentiment Δf1: **+0.0097 ± 0.0158** over 5 folds
- incremental value of each group (market + group):
  - sentiment: F1 0.313 (Δ +0.0051)
  - sentiment_news: F1 0.275 (Δ -0.0161)
  - sentiment_social: F1 0.310 (Δ -0.0380)
  - regime: F1 0.302 (Δ -0.0507)

## Economic test
- Flagged days move **+0.76%** above each stock's own typical move (vs +0.58% across all days)
- Straddle P&L (per-stock premium): betting only on flags **+0.151** vs betting every day +0.121

## Explainability
Feature attribution via **xgb_gain** (top features in `docs/assets/importances.png`).

## Verdict (honest)
ranks big-move days at AUC 0.578 (>0.5 = real signal); sentiment changed AUC by +0.0051; flagged days move +0.76pp above each stock's own norm.

## Known limitations & failure modes
- Selection bias (curated liquid/popular universe), fixed historical window.
- Sentiment coverage gaps and platform biases; after-hours text lagged to next session.
- Simple transaction-cost model; no slippage/latency/borrow costs.
- Multiple-comparisons risk across the universe — lead with the aggregate hit-rate, not per-ticker bests.
- Model decays as markets shift; retrain trigger: live hit-rate < 0.5 over 60 days.
