"""Honest backtest: a simple long/flat strategy vs buy-and-hold, after costs.

Rules are fixed up front (NOT optimised on the test set — that is leakage too).
We go long a name the next session when the model predicts up, otherwise hold
cash for it; an equal-weight daily portfolio across the universe. Costs are
charged on turnover. Reported against equal-weight buy-and-hold over the same
period (references/methodology.md).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _sharpe(rets: np.ndarray) -> float:
    if rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(252))


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float(((equity - peak) / peak).min())


def volatility_eval(test_df: pd.DataFrame, pred_big: np.ndarray) -> dict:
    """Honest economic test for the BIG-MOVE model, done PER STOCK so heterogeneous
    volatility doesn't confound it. 'Big move' is defined relative to each stock's
    own vol, so the straddle premium must also be per-stock: payoff = |return| minus
    that stock's typical move. A flag only wins if the day moves more than that
    stock NORMALLY does. We report the per-stock-normalized lift (move above the
    stock's own baseline) and a straddle P&L of betting only on flagged days.
    """
    df = test_df.copy()
    df["pred_big"] = pred_big
    df["abs_move"] = df["fwd_ret"].abs().fillna(0.0)
    df["premium"] = df.groupby("ticker")["abs_move"].transform("median")  # per-stock
    df["pnl"] = df["abs_move"] - df["premium"]                            # move above own norm

    flagged = df[df["pred_big"] == 1]
    notflag = df[df["pred_big"] == 0]
    dates = np.sort(df["date"].unique())
    strat, allin = [], []
    for d in dates:
        day = df[df["date"] == d]
        f = day[day["pred_big"] == 1]
        strat.append(float(f["pnl"].mean()) if len(f) else 0.0)
        allin.append(float(day["pnl"].mean()))
    s_eq, a_eq = np.cumsum(strat), np.cumsum(allin)
    return {
        "kind": "big_move",
        # raw averages (for display) ...
        "avg_move_flagged": float(flagged["abs_move"].mean()) if len(flagged) else 0.0,
        "avg_move_overall": float(df["abs_move"].mean()),
        "avg_move_not_flagged": float(notflag["abs_move"].mean()) if len(notflag) else 0.0,
        # ... and the honest per-stock-normalized lift (move above each stock's own norm)
        "lift_vs_own_norm_flagged": float(flagged["pnl"].mean()) if len(flagged) else 0.0,
        "lift_vs_own_norm_all": float(df["pnl"].mean()),
        "dates": [str(pd.Timestamp(d).date()) for d in dates],
        "strategy_pnl": s_eq.round(5).tolist(),
        "always_straddle_pnl": a_eq.round(5).tolist(),
        "strategy_total_pnl": float(s_eq[-1]) if len(s_eq) else 0.0,
        "always_total_pnl": float(a_eq[-1]) if len(a_eq) else 0.0,
    }


def backtest_portfolio(test_df: pd.DataFrame, signal: np.ndarray,
                       cost_bps: float, trade_on: str = "next_open") -> dict:
    """Equal-weight long/flat portfolio. `signal` is 1=long, 0=flat per row."""
    df = test_df.copy()
    df["signal"] = signal
    ret_col = "fwd_open_ret" if trade_on == "next_open" and "fwd_open_ret" in df else "fwd_ret"
    df[ret_col] = df[ret_col].fillna(0.0)

    dates = np.sort(df["date"].unique())
    cost = cost_bps / 1e4

    strat_rets, bh_rets = [], []
    prev_held: set = set()
    for d in dates:
        day = df[df["date"] == d]
        held = set(day.loc[day["signal"] == 1, "ticker"])
        n_universe = len(day)
        # strategy: equal weight across held names (cash earns 0)
        if held:
            r = day.loc[day["ticker"].isin(held), ret_col].mean()
        else:
            r = 0.0
        # turnover cost: names entering or leaving the book
        turnover = len(held.symmetric_difference(prev_held)) / max(n_universe, 1)
        r -= turnover * cost
        prev_held = held
        strat_rets.append(r)
        bh_rets.append(day[ret_col].mean())  # equal-weight always-invested

    strat_rets = np.array(strat_rets)
    bh_rets = np.array(bh_rets)
    strat_eq = np.cumprod(1 + strat_rets)
    bh_eq = np.cumprod(1 + bh_rets)

    return {
        "dates": [str(pd.Timestamp(d).date()) for d in dates],
        "strategy_equity": strat_eq.round(5).tolist(),
        "buy_hold_equity": bh_eq.round(5).tolist(),
        "strategy_total_return": float(strat_eq[-1] - 1) if len(strat_eq) else 0.0,
        "buy_hold_total_return": float(bh_eq[-1] - 1) if len(bh_eq) else 0.0,
        "strategy_sharpe": _sharpe(strat_rets),
        "buy_hold_sharpe": _sharpe(bh_rets),
        "strategy_max_drawdown": _max_drawdown(strat_eq) if len(strat_eq) else 0.0,
        "buy_hold_max_drawdown": _max_drawdown(bh_eq) if len(bh_eq) else 0.0,
        "cost_bps": cost_bps,
        "trade_on": trade_on,
    }
