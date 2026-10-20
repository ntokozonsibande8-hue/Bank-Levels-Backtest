"""Load H1 candle CSVs and convert them to SAST (Africa/Johannesburg)."""
from __future__ import annotations

import pandas as pd

LOCAL_TZ = "Africa/Johannesburg"


def load_csv(path: str, source_tz: str = "UTC", local_tz: str = LOCAL_TZ) -> pd.DataFrame:
    """Read a CSV with time, open, high, low, close columns.

    The time column may be called timestamp/time/datetime/date. It can hold ISO strings
    (with or without a UTC offset) or Unix epoch seconds. Naive timestamps are assumed
    to be in `source_tz`. The result is indexed by candle OPEN time in `local_tz`.
    """
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    tcol = next((c for c in ("timestamp", "time", "datetime", "date") if c in df.columns), None)
    if tcol is None:
        raise ValueError(f"{path}: no time column (expected timestamp/time/datetime/date)")
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            raise ValueError(f"{path}: missing column '{c}'")

    raw = df[tcol]
    if pd.api.types.is_numeric_dtype(raw):
        ts = pd.to_datetime(raw, unit="s", utc=True)
    else:
        ts = pd.to_datetime(raw)
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize(source_tz)
    ts = ts.dt.tz_convert(local_tz)

    out = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    out.index = pd.DatetimeIndex(ts, name="time")
    out = out.dropna().sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out
