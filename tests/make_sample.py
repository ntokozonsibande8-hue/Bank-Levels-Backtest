"""Write SYNTHETIC random-walk candles + calendar into data/ to smoke-test the pipeline.
Results from this data mean nothing; it only proves the plumbing runs.   python tests/make_sample.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
out = Path("data")
out.mkdir(exist_ok=True)
idx = pd.date_range("2024-01-01", "2025-12-31 23:00", freq="h", tz="UTC")
idx = idx[idx.dayofweek < 5]
for name, start, vol in (("EURUSD", 1.10, 0.0012), ("US30", 38000, 40.0), ("GER40", 17000, 18.0)):
    steps = rng.normal(0, vol, len(idx))
    close = start + np.cumsum(steps)
    open_ = np.r_[start, close[:-1]]
    hi = np.maximum(open_, close) + np.abs(rng.normal(0, vol / 2, len(idx)))
    lo = np.minimum(open_, close) - np.abs(rng.normal(0, vol / 2, len(idx)))
    pd.DataFrame({"timestamp": idx, "open": open_, "high": hi, "low": lo, "close": close}).to_csv(
        out / f"{name}_H1.csv", index=False)

events = ["USD Crude Oil Inventories", "USD PPI", "USD Building Permits", "USD Fed Interest Rate Decision",
          "EUR CPI", "GBP CPI", "USD ISM Manufacturing PMI"]
days = pd.bdate_range("2024-01-01", "2025-12-31")
rows = []
for d in days:
    for ev in rng.choice(events, size=rng.integers(0, 3), replace=False):
        rows.append({"datetime": f"{d.date()} 15:30", "currency": ev[:3], "event": ev[4:]})
pd.DataFrame(rows).to_csv(out / "calendar.csv", index=False)
print("sample data written to data/")
