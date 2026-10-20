from __future__ import annotations

import pandas as pd

COLS = ["trades", "win_rate", "avg_r", "total_r", "profit_factor", "max_dd_r", "avg_win_r", "avg_loss_r"]


def stats(g: pd.DataFrame) -> dict:
    g = g.sort_values("entry_time")
    r = g["r"]
    wins, losses = r[r > 0], r[r <= 0]
    curve = pd.concat([pd.Series([0.0]), r.cumsum().reset_index(drop=True)], ignore_index=True)
    dd = float((curve.cummax() - curve).max())
    loss_sum = abs(losses.sum())
    return {
        "trades": len(r),
        "win_rate": round(len(wins) / len(r) * 100, 1),
        "avg_r": round(r.mean(), 3),
        "total_r": round(r.sum(), 2),
        "profit_factor": round(wins.sum() / loss_sum, 2) if loss_sum > 0 else float("inf"),
        "max_dd_r": round(dd, 2),
        "avg_win_r": round(wins.mean(), 2) if len(wins) else 0.0,
        "avg_loss_r": round(losses.mean(), 2) if len(losses) else 0.0,
    }


def summarize(trades: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=by + COLS)
    rows = []
    for key, g in trades.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), **stats(g)})
    return pd.DataFrame(rows)
