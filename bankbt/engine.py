"""Bank levels engine: H1 candles in SAST, one trade per day per market at most.

Levels (R = window high - window low):
  buy : 0% = window low,  zone = low - 0.75R .. low - 1.0R,  stop = low - 1.5R,  target = window high
  sell: 0% = window high, zone = high + 0.75R .. high + 1.0R, stop = high + 1.5R, target = window low
Entry is a limit order at a chosen level inside the zone (75%, mid, 100%).

Intrabar conventions (H1 candles hide the order of highs and lows, so these are conservative):
  * the target is not credited on the candle that filled the entry
  * if stop and target are both inside one later candle, the stop is assumed hit first
  * a candle that reaches the target before the entry fills kills that direction for the day
  * a candle that reaches both the entry and the target is skipped (order unknown)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pandas as pd


@dataclass
class Settings:
    zone: tuple = (0.75, 1.0)       # bank level zone, as fractions of R
    stop: float = 1.5               # stop loss level, fraction of R
    close_hour: int = 23            # trade is closed at the close of the candle opening at this hour
    min_bars_frac: float = 1.0      # fraction of the window's H1 candles that must exist
    on_invalidation: str = "exit"   # "exit": close beyond the 100% level ends the trade; "hold": stop only


def window_levels(day: pd.DataFrame, start: int, end: int, need: int):
    h = day.index.hour
    w = day[(h >= start) & (h < end)]
    if len(w) < need:
        return None
    hi, lo = float(w["high"].max()), float(w["low"].min())
    return (hi, lo) if hi > lo else None


def build_levels(direction: str, hi: float, lo: float, entry_frac: float, zone, stop: float) -> dict:
    r = hi - lo
    base, sign = (lo, -1.0) if direction == "buy" else (hi, 1.0)

    def lvl(f):
        return base + sign * f * r

    return {
        "near": lvl(zone[0]), "far": lvl(zone[1]), "entry": lvl(entry_frac),
        "sl": lvl(stop), "tp": hi if direction == "buy" else lo,
    }


def _exit_check(pos, o, h, l, c, ts, st: Settings, entry_bar: bool):
    lv, d = pos["lv"], pos["direction"]
    if d == "buy":
        sl_hit, tp_hit, beyond = l <= lv["sl"], h >= lv["tp"], c < lv["far"]
        sl_px = lv["sl"] if entry_bar else min(o, lv["sl"])
    else:
        sl_hit, tp_hit, beyond = h >= lv["sl"], l <= lv["tp"], c > lv["far"]
        sl_px = lv["sl"] if entry_bar else max(o, lv["sl"])
    if sl_hit:
        return sl_px, "stop"
    if tp_hit and not entry_bar:
        return lv["tp"], "target"
    if st.on_invalidation == "exit" and beyond:
        return c, "invalidated"
    if ts.hour >= st.close_hour:
        return c, "time"
    return None


def _finish(pos, px, ts, reason, cost):
    d, entry, sl = pos["direction"], pos["entry"], pos["lv"]["sl"]
    risk = abs(entry - sl)
    pnl = (px - entry if d == "buy" else entry - px) - cost
    return {
        "direction": d, "entry_time": pos["entry_time"], "entry": entry, "sl": sl, "tp": pos["lv"]["tp"],
        "exit_time": ts, "exit": px, "reason": reason, "risk": risk, "pnl": pnl, "r": pnl / risk,
    }


def simulate_day(bars: pd.DataFrame, levels: dict, entry_end: int, st: Settings, cost: float):
    """bars: that day's candles from the window end onward. Returns (trade or None, note)."""
    alive = {"buy": True, "sell": True}
    why = None
    pos = None
    last_ts, last_c = None, None
    for ts, row in bars.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        last_ts, last_c = ts, c
        if pos is None:
            if ts.hour >= entry_end:
                return None, why or "no_touch"
            touched = []
            for d in ("buy", "sell"):
                if not alive[d]:
                    continue
                lv = levels[d]
                if d == "buy":
                    hit, tp_hit = l <= lv["entry"], h >= lv["tp"]
                else:
                    hit, tp_hit = h >= lv["entry"], l <= lv["tp"]
                if tp_hit:
                    alive[d] = False
                    why = why or ("ambiguous_bar" if hit else "target_before_entry")
                elif hit:
                    touched.append((d, lv))
            if len(touched) == 2:
                return None, "ambiguous_bar"
            if len(touched) == 1:
                d, lv = touched[0]
                fill = min(o, lv["entry"]) if d == "buy" else max(o, lv["entry"])
                if (d == "buy" and fill <= lv["sl"]) or (d == "sell" and fill >= lv["sl"]):
                    return None, "gap_through_stop"
                pos = {"direction": d, "lv": lv, "entry": fill, "entry_time": ts}
                res = _exit_check(pos, o, h, l, c, ts, st, entry_bar=True)
                if res:
                    return _finish(pos, res[0], ts, res[1], cost), "trade"
        else:
            res = _exit_check(pos, o, h, l, c, ts, st, entry_bar=False)
            if res:
                return _finish(pos, res[0], ts, res[1], cost), "trade"
    if pos is not None:
        return _finish(pos, last_c, last_ts, "time", cost), "trade"
    return None, why or "no_touch"


def run_market(df, market, session, entry_mode, entry_frac, st: Settings, cost=0.0, date_ok=None):
    """Run one market/session/entry-mode over every day in df. Returns (trades list, Counter of day outcomes)."""
    trades, notes = [], Counter()
    need = int((session["end"] - session["start"]) * st.min_bars_frac)
    for date, day in df.groupby(df.index.date):
        if date_ok is not None and not date_ok(date):
            notes["filtered_by_news"] += 1
            continue
        wl = window_levels(day, session["start"], session["end"], need)
        if wl is None:
            notes["incomplete_window"] += 1
            continue
        hi, lo = wl
        levels = {d: build_levels(d, hi, lo, entry_frac, st.zone, st.stop) for d in ("buy", "sell")}
        after = day[day.index.hour >= session["end"]]
        if after.empty:
            notes["no_bars_after_window"] += 1
            continue
        trade, note = simulate_day(after, levels, session["entry_end"], st, cost)
        notes[note] += 1
        if trade:
            trade.update(market=market, date=date, window=session["name"], entry_mode=entry_mode,
                         window_high=hi, window_low=lo)
            trades.append(trade)
    return trades, notes
