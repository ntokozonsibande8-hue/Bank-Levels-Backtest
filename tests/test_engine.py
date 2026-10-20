import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import simulate_day  # noqa: E402


def make_day(hour8_close=92):
    idx = pd.date_range("2025-01-06", periods=24, freq="h")
    rows = [(105, 110, 100, 105)] + [(105, 108, 102, 105)] * 6      # AS: L=100, H=110, R=10
    rows += [(104, 105, 95, 96), (96, 97, 91, hour8_close), (92, 111, 91, 110)]
    rows += [(110, 110, 110, 110)] * 14
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def test_buy_entry_at_75_hits_tp():
    t = simulate_day(make_day(), "AS", 0.75, False)
    assert t["side"] == "buy" and t["reason"] == "TP"
    assert abs(t["entry"] - 92.5) < 1e-9 and abs(t["sl"] - 85) < 1e-9
    assert abs(t["r"] - 17.5 / 7.5) < 1e-9


def test_buy_entry_at_mid():
    t = simulate_day(make_day(), "AS", 0.875, False)
    assert abs(t["entry"] - 91.25) < 1e-9 and abs(t["r"] - 3.0) < 1e-9


def test_entry_100_never_filled_no_trade():
    assert simulate_day(make_day(), "AS", 1.0, False) is None


def test_invalidation_exit():
    day = make_day(hour8_close=89)                      # closes below the 100% level (90)
    assert simulate_day(day, "AS", 0.75, False)["reason"] == "TP"
    t = simulate_day(day, "AS", 0.75, True)
    assert t["reason"] == "INVALIDATED" and abs(t["r"] - (-3.5 / 7.5)) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
