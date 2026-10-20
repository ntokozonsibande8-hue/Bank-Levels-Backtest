"""Run the bank levels backtest.

    python run_backtest.py                       # uses config.yaml
    python run_backtest.py --news-filter off     # baseline without the planner filter
    python run_backtest.py --coverage            # check planner rule names against your calendar
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from bankbt.data import load_csv
from bankbt.engine import Settings, run_market
from bankbt.metrics import summarize, stats
from bankbt.rules import coverage, date_filter, load_calendar


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--news-filter", choices=["trade_only", "skip_no_trade", "off"])
    ap.add_argument("--source-tz", default="UTC", help="timezone of naive timestamps in candle CSVs")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="results")
    ap.add_argument("--coverage", action="store_true")
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config))
    mode = a.news_filter or cfg["news_filter"]
    tz = cfg["local_tz"]

    cal = None
    cal_path = Path(cfg["calendar"])
    if cal_path.exists():
        cal = load_calendar(str(cal_path), cfg["calendar_tz"], tz)
        if a.coverage:
            miss = coverage(cal)
            print("Planner releases never seen in the calendar:" if miss else "All planner releases appear in the calendar.")
            for m in miss:
                print("  -", m)
            return
    elif mode != "off":
        raise SystemExit(f"News filter is '{mode}' but {cal_path} was not found. Add it or use --news-filter off.")

    st = Settings(zone=tuple(cfg["zone"]), stop=cfg["stop"], close_hour=cfg["close_hour"],
                  on_invalidation=cfg["on_invalidation"])
    start, end = pd.Timestamp(cfg["start"], tz=tz), pd.Timestamp(cfg["end"], tz=tz)

    all_trades, day_notes = [], []
    for name, m in cfg["markets"].items():
        path = Path(a.data_dir) / f"{name}_H1.csv"
        if not path.exists():
            print(f"skip {name}: {path} not found")
            continue
        df = load_csv(str(path), a.source_tz, tz)
        df = df[(df.index >= start) & (df.index < end)]
        ok = date_filter(cal, m["group"], mode)
        session = {**cfg["sessions"][m["window"]], "name": m["window"]}
        for em, frac in cfg["entry_modes"].items():
            trades, notes = run_market(df, name, session, em, frac, st, m.get("cost", 0.0), ok)
            all_trades += trades
            day_notes.append({"market": name, "entry_mode": em, **notes})
        print(f"done {name}: {len(df)} candles")

    if not all_trades:
        raise SystemExit("No trades. Check the data files, date range, and news filter (try --news-filter off).")

    out = Path(a.out)
    out.mkdir(exist_ok=True)
    tr = pd.DataFrame(all_trades).sort_values(["market", "entry_mode", "entry_time"])
    tr.to_csv(out / "trades.csv", index=False)
    pd.DataFrame(day_notes).fillna(0).to_csv(out / "day_outcomes.csv", index=False)

    by_market = summarize(tr, ["market", "entry_mode"])
    by_mode = pd.DataFrame([{"entry_mode": k, **stats(g)} for k, g in tr.groupby("entry_mode")])
    by_dir = summarize(tr, ["entry_mode", "direction"])
    by_market.to_csv(out / "summary_by_market.csv", index=False)
    by_mode.to_csv(out / "summary_by_entry_mode.csv", index=False)

    pd.set_option("display.width", 200)
    print(f"\nNews filter: {mode} | stop {cfg['stop']*100:.0f}% | invalidation: {cfg['on_invalidation']}")
    print("\n== All markets, by entry mode ==\n", by_mode.to_string(index=False))
    print("\n== By direction ==\n", by_dir.to_string(index=False))
    print("\n== By market ==\n", by_market.to_string(index=False))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.5))
        for em, g in tr.groupby("entry_mode"):
            g = g.sort_values("entry_time")
            ax.plot(pd.to_datetime(g["entry_time"], utc=True), g["r"].cumsum(), label=em)
        ax.set_title("Cumulative R by entry mode (all markets)")
        ax.set_ylabel("R")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "equity_curve.png", dpi=130)
    except Exception as e:
        print(f"(equity curve skipped: {e})")
    print(f"\nFiles written to {out}/")


if __name__ == "__main__":
    main()
