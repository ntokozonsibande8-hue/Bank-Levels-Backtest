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


def make_two_days(day2_hour0=(99, 111, 98, 110)):
    d1 = make_day()
    d1.iloc[9] = (92, 100, 91, 99)                     # no target on day 1
    d1.iloc[10:] = [(99, 99, 99, 99)] * 14
    idx2 = pd.date_range("2025-01-07", periods=24, freq="h")
    rows2 = [day2_hour0] + [(110, 110, 110, 110)] * 23
    d2 = pd.DataFrame(rows2, index=idx2, columns=["open", "high", "low", "close"])
    return d1, pd.concat([d1, d2])


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


def test_trade_carries_into_next_day_and_hits_tp():
    d1, full = make_two_days()
    t = simulate_day(d1, "AS", 0.75, False, full)
    assert t["reason"] == "TP" and t["exit_time"] == pd.Timestamp("2025-01-07 00:00")
    assert abs(t["r"] - 17.5 / 7.5) < 1e-9 and t["hold_h"] > 12


def test_trade_carries_into_next_day_and_hits_sl():
    d1, full = make_two_days(day2_hour0=(99, 99, 84, 90))   # next day trades through the 150% stop (85)
    t = simulate_day(d1, "AS", 0.75, False, full)
    assert t["reason"] == "SL" and abs(t["r"] + 1) < 1e-9


def test_no_entry_before_previous_trade_closed():
    d1, full = make_two_days()
    assert simulate_day(d1, "AS", 0.75, False, full, not_before=pd.Timestamp("2025-01-06 12:00")) is None


def test_open_at_data_end():
    d1, _ = make_two_days()
    t = simulate_day(d1, "AS", 0.75, False, d1)
    assert t["reason"] == "OPEN_AT_DATA_END"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
