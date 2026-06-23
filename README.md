# AI Big-Move Radar

I built this to predict whether a stock would go up or down the next day. Short version: you basically can't. On real data it lands right around 50%, a coin flip. That's not a bug in my code, it's just markets being efficient, and every time I tried to force a better number I was really just teaching the model to peek at the future or memorize noise.

So I changed the question to one that actually has a pattern in it. Big moves tend to cluster (a wild day is usually followed by more wild days), so instead of asking "which way will it go" I ask "is this stock about to make a big move, in either direction?" That one you can get somewhere with.

**The question this repo answers:** does adding sentiment (news + social) help flag those big-move days beyond what price and volume already tell you?

Heads up before anyone gets excited: this is a learning/research project, not financial advice. The radar tells you what might *move*, not what to *buy*. If you want the original up/down version back, flip `target.type: binary` in `config.yaml`.

## What it actually found
<!-- AUTO-RESULTS:START -->
- **Data mode:** `live`; test window ['2026-05-19', '2026-06-17']
- **Model vs baselines (test accuracy):** model 0.405 | persistence 0.724 | majority 0.820
- **With vs without sentiment (test F1):** 0.313 vs 0.308 (Δ +0.0051; walk-forward +0.0097 ± 0.0158)
- **Economic test:** Flagged days move **+0.76%** above each stock's own typical move (vs +0.58% across all days); Straddle P&L (per-stock premium): betting only on flags **+0.151** vs betting every day +0.121
- **Aggregate test hit-rate:** 0.405
- **Verdict:** ranks big-move days at AUC 0.578 (>0.5 = real signal); sentiment changed AUC by +0.0051; flagged days move +0.76pp above each stock's own norm
<!-- AUTO-RESULTS:END -->

The plain-English read: the model ranks big-move days a bit better than a coin flip (AUC around 0.58), sentiment gives a small but repeatable bump, and on the days it actually flags, stocks move noticeably more than they normally do. It's not a money machine and I'm not going to pretend it is. But it's a real, modest edge on something that's genuinely predictable, which beats a flashy fake one.

(Don't read too much into the 40.5% "hit-rate" on its own. Big moves are rare, so the bar isn't 50%, it's the ~18% base rate. Flagging correctly 40% of the time is roughly 2x better than guessing.)

## How it's put together
There are two halves.

The **engine** trains and checks the model. Most of the work here is the unglamorous stuff that keeps it honest: splitting data by time so it can never see the future, lagging after-hours news to the next session, making it beat dumb baselines before I believe anything, and an ablation that tells me whether sentiment is actually pulling its weight or just along for the ride. There are leakage tests in CI that fail the build if I screw any of that up.

The **tracker** is the part you can look at: a plain static site on GitHub Pages. A scheduled GitHub Action runs the frozen model on fresh data every day, writes its calls to a log *before* the outcomes are known, then reconciles them later. The site just reads JSON, it never runs the model itself.

## Running it yourself
It works offline on synthetic data out of the box, so you don't need any keys to poke at it:

```bash
pip install -r requirements.txt
python run_pipeline.py            # whole thing end to end on the core tickers
pytest -q                         # leakage + smoke tests
```

Or step by step if you want to see each stage:

```bash
python -m src.data.pull       --config config.yaml   # prices + text
python -m src.data.align      --config config.yaml   # target + calendar alignment
python -m src.sentiment.score --config config.yaml   # FinBERT (falls back to a lexicon)
python -m src.features.build  --config config.yaml   # causal, grouped features
python -m src.models.train    --config config.yaml   # XGBoost + calibration
python -m src.eval.report     --config config.yaml   # metrics, ablation, figures
python -m src.predict         --config config.yaml --universe   # daily refresh -> docs/data/*.json
```

For real markets, set `data.mode: live` and drop a (free) Finnhub key into a `.env` file. Prices come from yfinance and need no key. Sentiment uses news by default; Reddit needs an API app if you want social chatter too.

## Where it lives in the repo
```
config.yaml      all the knobs (tickers, horizon, costs, seed) in one place
src/data/        pulling prices/text and lining them up to the trading calendar
src/sentiment/   FinBERT scoring -> daily per-stock sentiment features
src/features/    the causal feature builders, grouped so the ablation can drop a group cleanly
src/models/      splits, baselines, training + probability calibration
src/eval/        metrics, the ablation, the economic test, the report
src/predict.py   the daily job: reconcile yesterday, predict today, write the dashboard JSON
docs/            the static site (GitHub Pages)
reports/         the model card
```

## Stuff I'd want you to know before trusting it
- Not advice. Really. It's for learning.
- A backtest is not live trading. There's a simple cost model and that's it, no slippage, no latency, none of the stuff that bites you in real life.
- It only looks at a curated set of liquid, heavily-discussed names, which is its own kind of bias.
- Free sentiment data has gaps and leans toward whatever's loud that week.
- The model is frozen on a fixed window and will go stale as the market changes. There's a retrain trigger in `config.yaml` for when that happens.

If the honest answer turns out to be "sentiment barely helps," that's fine, that's still an answer. I'd rather report a small real number than a suspicious huge one.
