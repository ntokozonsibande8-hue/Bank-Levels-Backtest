"""Bank levels backtest on H1 candles (SAST).

Usage: python backtest.py --config config.yaml [--no-news-filter]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

WINDOWS = {"AS": (0, 7), "AR": (0, 10)}        # start hour, end hour (SAST, end exclusive)
ENTRY_MODES = {"75": 0.75, "mid": 0.875, "100": 1.0}
SL_MULT = 1.5                                   # stop at the 150% level


def load_candles(path):
    df = pd.read_csv(path, parse_dates=["time_sast"])
    return df.sort_values("time_sast").set_index("time_sast")[["open", "high", "low", "close"]]


def allowed_days(market_rules, news):
    """Days where a 'trade' rule fires and no 'don't trade' rule fires."""
    labels = {}
    dates = pd.to_datetime(news["date"]).dt.date
    for d, cur, ev in zip(dates, news["currency"], news["event"]):
        labels.setdefault(d, []).append(f"{cur} {ev}".lower().strip())

    def hit(rules, ls):
        return any(all(any(l.startswith(e.lower()) for l in ls) for e in rule) for rule in rules)

    return {d for d, ls in labels.items()
            if hit(market_rules.get("trade", []), ls) and not hit(market_rules.get("dont", []), ls)}


def _result(side, t_in, fill, t_out, px, reason, sl):
    risk = abs(fill - sl)
    r = (px - fill) / risk if side == "buy" else (fill - px) / risk
    hold_h = (t_out - t_in).total_seconds() / 3600
    return dict(side=side, entry_time=t_in, entry=fill, exit_time=t_out, exit=px, reason=reason, sl=sl, r=r,
                hold_h=hold_h)


def run_side(side, H, L, R, entry_candles, df, f, inv_exit):
    """Look for the entry on the setup day only; once filled, hold across days until SL / TP
    (or the optional invalidation exit). If the data ends first, close at the last close."""
    buy = side == "buy"
    base, d = (L, -1) if buy else (H, 1)
    lvl = lambda x: base + d * x * R
    entry, z100, sl, tp = lvl(f), lvl(1.0), lvl(SL_MULT), (H if buy else L)
    fill = t_in = None
    for ts, c in entry_candles.iterrows():
        touched = c.low <= entry if buy else c.high >= entry
        if not touched:
            if (c.high >= tp) if buy else (c.low <= tp):
                return None                           # target reached without a manipulation entry
            continue
        px = min(c.open, entry) if buy else max(c.open, entry)
        if (px <= sl) if buy else (px >= sl):
            return None                               # gapped through the stop
        fill, t_in = px, ts
        break
    if fill is None:
        return None
    c = entry_candles.loc[t_in]
    # fill candle: order of events unknown, so only the stop is checked (pessimistic)
    if (c.low <= sl) if buy else (c.high >= sl):
        return _result(side, t_in, fill, t_in, sl, "SL", sl)
    if inv_exit and ((c.close < z100) if buy else (c.close > z100)):
        return _result(side, t_in, fill, t_in, c.close, "INVALIDATED", sl)
    later = df.loc[t_in:].iloc[1:]                    # every following candle, across days and weekends
    for ts, c in later.iterrows():
        if (c.low <= sl) if buy else (c.high >= sl):
            return _result(side, t_in, fill, ts, sl, "SL", sl)
        if (c.high >= tp) if buy else (c.low <= tp):
            return _result(side, t_in, fill, ts, tp, "TP", sl)
        if inv_exit and ((c.close < z100) if buy else (c.close > z100)):
            return _result(side, t_in, fill, ts, c.close, "INVALIDATED", sl)
    last_ts = later.index[-1] if len(later) else t_in
    last_close = later.close.iloc[-1] if len(later) else entry_candles.loc[t_in].close
    return _result(side, t_in, fill, last_ts, last_close, "OPEN_AT_DATA_END", sl)


def simulate_day(day, window, f, inv_exit, df=None, not_before=None):
    """df = the full candle history (needed so a trade can run past midnight).
    not_before = exit time of the previous trade; no new entry is taken until it has closed."""
    df = day if df is None else df
    start, end = WINDOWS[window]
    ref = day[(day.index.hour >= start) & (day.index.hour < end)]
    if len(ref) < end - start:
        return None                                   # incomplete session (holiday / missing data)
    H, L = ref.high.max(), ref.low.min()
    R = H - L
    if R <= 0:
        return None
    after = day[day.index.hour >= end]
    if not_before is not None:
        after = after[after.index > not_before]
    if after.empty:
        return None
    trades = [t for t in (run_side(s, H, L, R, after, df, f, inv_exit) for s in ("buy", "sell")) if t]
    if not trades:
        return None
    trades.sort(key=lambda t: t["entry_time"])
    if len(trades) == 2 and trades[0]["entry_time"] == trades[1]["entry_time"]:
        return None
    t = trades[0]
    t.update(window=window, asia_high=H, asia_low=L)
    return t


def stats(tr):
    if tr.empty:
        return dict(trades=0, win_rate=np.nan, avg_R=np.nan, profit_factor=np.nan, total_R=0.0, max_dd_R=0.0, avg_hold_h=np.nan)
    r = tr["r"]
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    eq = pd.concat([pd.Series([0.0]), r.cumsum().reset_index(drop=True)])
    return dict(trades=len(r), win_rate=round((r > 0).mean() * 100, 1), avg_R=round(r.mean(), 3),
                profit_factor=round(gains / losses, 2) if losses else np.inf,
                total_R=round(r.sum(), 2), max_dd_R=round((eq.cummax() - eq).max(), 2),
                avg_hold_h=round(tr["hold_h"].mean(), 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-news-filter", action="store_true", help="trade every day, ignore the planner rules")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    rules = yaml.safe_load(open(cfg["rules_file"]))
    news = None
    if not a.no_news_filter:
        news = pd.read_csv(cfg["news_file"])
    out = Path("results")
    out.mkdir(exist_ok=True)
    summary = []
    for mname, m in cfg["markets"].items():
        ok_days = None if news is None else allowed_days(rules[m["rules"]], news)
        for sym in m["symbols"]:
            path = Path("data") / f"{sym}.csv"
            if not path.exists():
                print(f"skip {sym}: {path} not found")
                continue
            df = load_candles(path).loc[cfg["start"]:cfg["end"]]
            fig, ax = plt.subplots(figsize=(9, 4))
            for mode, f in ENTRY_MODES.items():
                for inv in (False, True):
                    rows = []
                    busy_until = None                 # one open trade at a time per symbol
                    for d, day in df.groupby(df.index.date):
                        if ok_days is not None and d not in ok_days:
                            continue
                        t = simulate_day(day, m["window"], f, inv, df, busy_until)
                        if t:
                            busy_until = t["exit_time"]
                            rows.append(dict(date=d, market=mname, symbol=sym, entry_mode=mode, inv_exit=inv, **t))
                    tr = pd.DataFrame(rows)
                    label = f"entry {mode} / invalidation exit {'on' if inv else 'off'}"
                    summary.append(dict(market=mname, symbol=sym, window=m["window"], variant=label, **stats(tr)))
                    if not tr.empty:
                        tr.to_csv(out / f"{sym}_{mode}_inv{int(inv)}_trades.csv", index=False)
                        ax.plot(tr["r"].cumsum().values, label=label, lw=1, ls="--" if inv else "-")
            ax.set(title=f"{sym} ({m['window']}) cumulative R", xlabel="trade #", ylabel="R")
            ax.legend(fontsize=6)
            fig.tight_layout()
            fig.savefig(out / f"{sym}_equity.png", dpi=130)
            plt.close(fig)
    s = pd.DataFrame(summary)
    s.to_csv(out / "summary.csv", index=False)
    print(s.to_string(index=False))


if __name__ == "__main__":
    main()
