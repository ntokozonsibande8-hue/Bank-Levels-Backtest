"""DayTrade planner news rules -> which days each market may be traded.

Each rule is a list of releases that must ALL land on the same day ("+" in the planner).
Rule names are matched (case-insensitive, whitespace-normalised) against "<CURRENCY> <event>"
built from the calendar CSV. Run with --coverage to see rules that never matched anything,
which usually means the calendar spells the event differently.
"""
from __future__ import annotations

import pandas as pd

LOCAL_TZ = "Africa/Johannesburg"


def _u(*names):  # one rule: every release listed must land on the same day
    return list(names)


RULES = {
    "Currencies": {
        "trade": [_u("USD Crude Oil Inventories"), _u("USD ISM Manufacturing PMI"), _u("USD Fed's Balance Sheet")],
        "no_trade": [
            _u("USD ADP Nonfarm Employment"), _u("USD Fed Interest Rate Decision"),
            _u("USD Core PCE Price Index"), _u("USD FOMC Meeting Minutes"), _u("USD Building Permits"),
            _u("USD FOMC Member Speaks"), _u("USD Manufacturing PMI (P)"), _u("USD PPI"),
        ],
    },
    "Nasdaq": {
        "trade": [
            _u("USD Crude Oil Inventories"), _u("USD EIA Short-Term Energy Outlook"),
            _u("USD Fed's Balance Sheet"), _u("USD Industrial Production"),
        ],
        "no_trade": [
            _u("USD ADP Nonfarm Employment"), _u("USD FOMC Member Speaks"), _u("USD Fed Interest Rate Decision"),
            _u("USD Core PCE Price Index"), _u("USD FOMC Meeting Minutes"), _u("USD Building Permits"),
            _u("USD Manufacturing PMI (P)"), _u("USD PPI"),
        ],
    },
    "US30": {
        "trade": [_u("USD Building Permits"), _u("USD PPI")],
        "no_trade": [
            _u("USD ADP Nonfarm Employment"), _u("USD FOMC Member Speaks"), _u("USD Fed Interest Rate Decision"),
            _u("USD Core PCE Price Index"), _u("USD FOMC Meeting Minutes"),
        ],
    },
    "GER40": {
        "trade": [_u("EUR ECB President Lagarde Speaks"), _u("EUR CPI"), _u("USD Core CPI")],
        "no_trade": [
            _u("GBP CPI"), _u("GBP GDP"),
            _u("USD Philadelphia Fed", "USD Initial Jobless Claims"),
            _u("USD GDP", "USD Initial Jobless Claims"),
            _u("USD Pending Home Sales", "USD Initial Jobless Claims"),
        ],
    },
    "UK100": {
        "trade": [
            _u("GBP Manufacturing PMI"), _u("GBP Services PMI"), _u("GBP Composite PMI"),
            _u("GBP Manufacturing Production", "GBP GDP"),
        ],
        "no_trade": [
            _u("EUR ECB Interest Rate Decision"), _u("GBP CPI"), _u("GBP GDP"),
            _u("USD Philadelphia Fed", "USD Initial Jobless Claims"),
            _u("USD GDP", "USD Initial Jobless Claims"),
            _u("USD Pending Home Sales", "USD Initial Jobless Claims"),
        ],
    },
}


def norm(s: str) -> str:
    return " ".join(str(s).lower().replace("\u2019", "'").split())


def load_calendar(path: str, source_tz: str = LOCAL_TZ, local_tz: str = LOCAL_TZ) -> pd.DataFrame:
    """CSV columns: datetime, currency, event (impact optional). Returns date + key columns."""
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for c in ("datetime", "currency", "event"):
        if c not in df.columns:
            raise ValueError(f"{path}: missing column '{c}' (need datetime, currency, event)")
    ts = pd.to_datetime(df["datetime"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(source_tz)
    ts = ts.dt.tz_convert(local_tz)
    cur = df["currency"].astype(str).str.strip().str.upper()
    ev = df["event"].astype(str).str.strip()
    # tolerate calendars whose event text already starts with the currency
    ev = [e[len(c):].strip() if e.upper().startswith(c + " ") else e for e, c in zip(ev, cur)]
    return pd.DataFrame({"date": ts.dt.date, "key": [norm(f"{c} {e}") for c, e in zip(cur, ev)]})


def _events_by_date(cal: pd.DataFrame) -> dict:
    return cal.groupby("date")["key"].apply(set).to_dict()


def _hit(rule, keys) -> bool:
    return all(norm(x) in keys for x in rule)


def day_verdicts(cal: pd.DataFrame, group: str) -> dict:
    """date -> 'trade' | 'no_trade'. 'No trade' beats 'trade' on the same day. Quiet days are absent."""
    rules, out = RULES[group], {}
    for date, keys in _events_by_date(cal).items():
        if any(_hit(r, keys) for r in rules["no_trade"]):
            out[date] = "no_trade"
        elif any(_hit(r, keys) for r in rules["trade"]):
            out[date] = "trade"
    return out


def date_filter(cal, group: str, mode: str):
    """Return a function date -> bool (may we trade that day?), or None for no filtering.

    trade_only    : only days the planner marks 'trade'
    skip_no_trade : every day except 'don't trade' days (quiet days allowed)
    off           : no news filter
    """
    if mode == "off" or cal is None:
        return None
    v = day_verdicts(cal, group)
    if mode == "trade_only":
        return lambda d: v.get(d) == "trade"
    if mode == "skip_no_trade":
        return lambda d: v.get(d) != "no_trade"
    raise ValueError(f"unknown news_filter '{mode}'")


def coverage(cal: pd.DataFrame) -> list[str]:
    """Rule releases that never appear in the calendar (likely naming mismatches)."""
    seen = set().union(*_events_by_date(cal).values()) if len(cal) else set()
    missing = set()
    for r in RULES.values():
        for kind in ("trade", "no_trade"):
            for rule in r[kind]:
                missing.update(n for n in rule if norm(n) not in seen)
    return sorted(missing)
