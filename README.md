# AI Big-Move Radar (sentiment + market data)

**The honest story:** we first tested whether AI can call next-session **direction** (up/down)
from sentiment + price. On real data it's a **coin flip (~50%)** — that's market efficiency, not
a bug, and chasing it invites leakage/overfitting. So we pivoted to what genuinely *is*
predictable: **volatility**. Big moves cluster, so the live question becomes —

**Research question:** *Does sentiment help predict whether a stock will make an **outsized move**
next session (either direction), beyond what price/volume already say?* The radar flags
**which stocks are about to move**, not which way. (Set `target.type: binary` in `config.yaml`
to switch back to the direction experiment.)

> Experimental research project. **Not financial advice.** The radar predicts *magnitude, not
> direction* — it is never a "buy" signal.

This repo is built in two layers, per the [methodology](reports/):
1. **The engine** — a leakage-free model validated by an honest **feature-group ablation** (does
   sentiment help?), **baselines it must beat**, AUC, and a per-stock "straddle" economic test.
2. **The tracker** — a static [GitHub Pages dashboard](docs/index.html) that applies the
   frozen model across a ~41-stock universe daily, logs every prediction *before* the outcome,
   and shows precision-on-flags vs the big-move base rate.

## Headline result
<!-- AUTO-RESULTS:START -->
- **Data mode:** `live` (live); test window ['2026-05-19', '2026-06-17']
- **Model vs baselines (test accuracy):** model 0.405 | persistence 0.724 | majority 0.820
- **With vs without sentiment (test F1):** 0.313 vs 0.308 (Δ +0.0051; walk-forward +0.0097 ± 0.0158)
- **Economic test:** Flagged days move **+0.76%** above each stock's own typical move (vs +0.58% across all days); Straddle P&L (per-stock premium): betting only on flags **+0.151** vs betting every day +0.121
- **Aggregate test hit-rate:** 0.405
- **Verdict:** ranks big-move days at AUC 0.578 (>0.5 = real signal); sentiment changed AUC by +0.0051; flagged days move +0.76pp above each stock's own norm
<!-- AUTO-RESULTS:END -->

> **Data mode matters.** Out of the box the pipeline runs in `offline` mode on a
> deterministic **synthetic** dataset so it is fully reproducible with no API keys or
> network — this demonstrates the *machinery and discipline*, not a real market finding.
> Set `data.mode: live` in `config.yaml` (and provide API keys) for real markets.

## Guardrails enforced (the whole point)
1. **Direction, not price** — binary up/down classification; chance ≈ 50%, so any edge is honest.
2. **Beat baselines** — persistence, majority-class, and buy-and-hold are reported alongside the model.
3. **No leakage** — chronological/walk-forward splits, scalers fit on train only, causal features,
   after-hours text lagged to the next session. Enforced by `tests/test_leakage.py` in CI.
4. **Realistic eval** — accuracy/precision/recall/F1/ROC-AUC + a cost-aware backtest vs buy-and-hold.
5. **Prove narrow, deploy wide** — validate on `core_study`, then roll out to the `universe`.
6. **Tracker not advice** — every prediction carries its hit-rate; lead with the *aggregate*.

## Reproduce
```bash
pip install -r requirements.txt
python -m src.data.pull       --config config.yaml      # raw prices + text  (offline: synthetic)
python -m src.data.align      --config config.yaml      # target + calendar alignment (lag rule)
python -m src.sentiment.score --config config.yaml      # FinBERT / lexicon -> daily sentiment
python -m src.features.build  --config config.yaml      # causal, grouped features
python -m src.models.train    --config config.yaml      # XGBoost + calibration -> frozen artifacts
python -m src.eval.report     --config config.yaml      # metrics, ablation, backtest, SHAP, figures
python -m src.predict         --config config.yaml --universe   # daily refresh -> docs/data/*.json
pytest -q                                               # leakage + smoke tests
```
A single end-to-end run (offline, core tickers): `python -m run_pipeline` (see `run_pipeline.py`).

## Universe rollout
The model is **pooled** (one model, ticker/sector as features) per `config.yaml` `tracker.model_scope`.
`src.data.pull --universe` and the dashboard expand from the 4 `core_study` tickers to the ~22-name
`universe`. Test hit-rate is reported **per ticker AND aggregate**; the aggregate is the honest headline
(beware the multiple-comparisons trap — see `reports/model_card.md`).

## Deploy
Static [`docs/`](docs/) site served by GitHub Pages; `.github/workflows/daily-update.yml` runs the
**frozen** model on fresh data after each US close, reconciles past predictions, and commits refreshed
JSON. The site reads JSON and never runs the model. Put API keys in repo Actions secrets.

## Layout
```
config.yaml              # single source of truth (tickers, horizon, splits, costs, seed)
src/data/                # acquisition (sources.py) + target/alignment (align.py)
src/sentiment/score.py   # FinBERT (or lexicon fallback) -> daily per-ticker features
src/features/build.py    # causal, group-tagged features (market/sentiment/regime/...)
src/models/              # prep (splits), baselines, train (XGBoost + calibration)
src/eval/                # metrics, ablation, backtest, report (figures + JSON + model card)
src/predict.py           # daily reconcile + predict + publish dashboard JSON
tests/                   # leakage guards + end-to-end smoke test
docs/                    # GitHub Pages dashboard (index.html + assets + data/*.json)
reports/model_card.md    # intended use, metrics, ablation, limitations (auto-filled)
```

## Limitations & ethics
Not financial advice; research/education only. Backtest ≠ live (no slippage/latency/borrow beyond a
simple bps cost). Curated liquid universe → selection bias. Sentiment has coverage gaps and platform
biases. The model is frozen and decays as markets shift (see the retrain trigger in `config.yaml`).
Stating these plainly is a credibility multiplier — a modest honest edge (or an honest null) beats a
suspicious 90%.
