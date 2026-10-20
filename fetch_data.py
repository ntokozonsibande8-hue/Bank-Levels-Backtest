"""Download Dukascopy 1-minute BID candles and build H1 candles in SAST (GMT+2).

Usage: python fetch_data.py --config config.yaml
Writes data/<SYMBOL>.csv with columns: time_sast,open,high,low,close

NOTE: untested against the live server by the author (no internet where this was written).
Run `python fetch_data.py --config config.yaml --start 2025-01-06 --end 2025-01-10` first
and compare a few H1 candles with your broker/TradingView chart before trusting it.
"""
import argparse
import lzma
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
SAST = "Africa/Johannesburg"  # fixed GMT+2, no DST


def point(sym):
    # price scale of the integers in the file; check the printed first/last close
    return 1000 if sym.endswith("JPY") or "IDX" in sym else 100000


def get_day(sym, day, raw_dir):
    cache = raw_dir / sym / f"{day}.bi5"
    if cache.exists():
        return cache.read_bytes()
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day)  # month is 0-based in the URL
    for attempt in range(4):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if r.status_code == 404:
                data = b""
            else:
                r.raise_for_status()
                data = r.content
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            return data
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    print(f"  failed: {sym} {day}")
    return b""


def parse_day(data, day, sym):
    if not data:
        return []
    raw = lzma.decompress(data)
    scale = point(sym)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rows = []
    # record: seconds, open, close, low, high (ints), volume (float)
    for t, o, c, l, h, _v in struct.iter_unpack(">IIIIIf", raw):
        rows.append((start + timedelta(seconds=t), o / scale, h / scale, l / scale, c / scale))
    return rows


def fetch_symbol(sym, start, end, raw_dir):
    days = [start + timedelta(days=i) for i in range(-1, (end - start).days + 1)]
    days = [d for d in days if d.weekday() != 5]  # no Saturday files
    with ThreadPoolExecutor(max_workers=2) as ex:
        blobs = list(ex.map(lambda d: get_day(sym, d, raw_dir), days))
    rows = []
    for d, b in zip(days, blobs):
        rows += parse_day(b, d, sym)
    if not rows:
        print(f"{sym}: no data")
        return
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close"]).set_index("t").sort_index()
    df.index = df.index.tz_convert(SAST).tz_localize(None)
    h1 = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    h1.index.name = "time_sast"
    out = Path("data") / f"{sym}.csv"
    h1.to_csv(out)
    print(f"{sym}: {len(h1)} H1 candles, first close {h1.close.iloc[0]}, last close {h1.close.iloc[-1]} -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    start = date.fromisoformat(a.start or cfg["start"])
    end = date.fromisoformat(a.end or cfg["end"])
    raw_dir = Path("data/raw")
    syms = sorted({s for m in cfg["markets"].values() for s in m["symbols"]})
    for s in syms:
        fetch_symbol(s, start, end, raw_dir)


if __name__ == "__main__":
    main()
