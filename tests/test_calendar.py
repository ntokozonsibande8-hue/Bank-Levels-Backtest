import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import econlib as E  # noqa: E402

ALIASES = E.load_aliases(Path(__file__).resolve().parents[1] / "aliases.yaml")


def fmp(dt, event, cur="USD", impact="Medium"):
    return {"date": dt, "event": event, "currency": cur, "country": "US", "impact": impact}


def rows_from(raw, norm=E.norm_fmp, start=date(2025, 1, 1), end=date(2025, 12, 31), **kw):
    return E.build_rows(raw, norm, start, end, ALIASES, **kw)[0]


def test_utc_to_sast_crosses_midnight():
    r = rows_from([fmp("2025-03-04 22:30:00", "PPI (MoM)")])[0]
    assert (r["date"], r["time"]) == ("2025-03-05", "00:30")


def test_utc_to_sast_same_day():
    r = rows_from([fmp("2025-03-04 13:30:00", "PPI (MoM)")])[0]
    assert (r["date"], r["time"]) == ("2025-03-04", "15:30")


def test_range_uses_sast_date():
    raw = [fmp("2025-03-04 22:30:00", "PPI (MoM)")]                    # 5 March in SAST
    assert rows_from(raw, start=date(2025, 3, 4), end=date(2025, 3, 4)) == []
    assert len(rows_from(raw, start=date(2025, 3, 5), end=date(2025, 3, 5))) == 1


def test_alias_makes_rules_match():
    r = rows_from([fmp("2025-03-05 13:15:00", "ADP Nonfarm Employment Change")])[0]
    assert f"{r['currency']} {r['event']}".lower().startswith("usd adp nonfarm employment")
    assert r["raw_event"] == "ADP Nonfarm Employment Change"


def test_alias_respects_currency():
    eur = rows_from([fmp("2025-03-05 10:00:00", "CPI (YoY)", cur="EUR")])[0]
    gbp = rows_from([fmp("2025-03-05 07:00:00", "CPI (YoY)", cur="GBP")])[0]
    assert f"EUR {eur['event']}".startswith("EUR CPI") and f"GBP {gbp['event']}".startswith("GBP CPI")
    usd = rows_from([fmp("2025-03-05 13:30:00", "CPI (YoY)", cur="USD")])[0]
    assert usd["event"] == "CPI (YoY)"                                   # no USD alias: left as the provider wrote it


def test_ppi_does_not_match_core_ppi():
    assert E.canonical_name("USD", "PPI (MoM)", ALIASES) == "USD PPI"
    assert E.canonical_name("USD", "Core PPI (MoM)", ALIASES) is None


def test_unmatched_event_kept_as_is():
    assert rows_from([fmp("2025-03-05 13:30:00", "Some New Release")])[0]["event"] == "Some New Release"


def test_impact_filter():
    raw = [fmp("2025-03-05 13:30:00", "A", impact="Low"), fmp("2025-03-05 14:30:00", "B", impact="High")]
    assert len(rows_from(raw, min_impact="low")) == 2
    assert [r["event"] for r in rows_from(raw, min_impact="medium")] == ["B"]


def test_currency_filter_and_dedupe():
    raw = [fmp("2025-03-05 13:30:00", "A"), fmp("2025-03-05 13:30:00", "A"), fmp("2025-03-05 13:30:00", "A", cur="JPY")]
    assert len(rows_from(raw)) == 2
    assert len(rows_from(raw, currencies=["USD"])) == 1


def test_tradingeconomics_normaliser():
    raw = [{"Date": "2025-03-04T13:30:00", "Country": "United States", "Event": "Initial Jobless Claims",
            "Importance": 2, "Currency": "USD"}]
    r = rows_from(raw, norm=E.norm_tradingeconomics)[0]
    assert (r["date"], r["time"], r["impact"], r["event"]) == ("2025-03-04", "15:30", "medium", "Initial Jobless Claims")


def test_country_fallback_for_currency():
    raw = [{"Date": "2025-03-04T09:00:00", "Country": "Euro Area", "Event": "Inflation Rate YoY", "Importance": 3}]
    assert rows_from(raw, norm=E.norm_tradingeconomics)[0]["currency"] == "EUR"


def test_bad_rows_are_skipped_not_fatal():
    out, skipped = E.build_rows([{"nope": 1}, fmp("2025-03-05 13:30:00", "A")], E.norm_fmp,
                                date(2025, 1, 1), date(2025, 12, 31), ALIASES)
    assert len(out) == 1 and skipped == 1


def test_jsonfile_normaliser_with_sast_input():
    norm = E.make_jsonfile_normaliser({"datetime": "when", "datetime_tz": "SAST", "currency": "ccy", "event": "name", "impact": "imp"})
    r = rows_from([{"when": "2025-03-05 15:30", "ccy": "usd", "name": "PPI", "imp": "High"}], norm=norm)[0]
    assert (r["date"], r["time"], r["currency"]) == ("2025-03-05", "15:30", "USD")


def test_month_ranges():
    assert list(E.month_ranges(date(2024, 12, 20), date(2025, 2, 3))) == [
        (date(2024, 12, 1), date(2024, 12, 31)), (date(2025, 1, 1), date(2025, 1, 31)), (date(2025, 2, 1), date(2025, 2, 28))]


def test_csv_works_with_backtest_matching(tmp_path=None):
    import pandas as pd, tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import coverage as C
    raw = [fmp("2025-03-04 13:30:00", "Building Permits (MoM)"), fmp("2025-03-04 15:00:00", "Crude Oil Inventories")]
    rows = rows_from(raw)
    p = Path(tempfile.mkdtemp()) / "n.csv"
    E.write_csv(rows, p)
    news = pd.read_csv(p)
    assert list(news.columns)[:4] == ["date", "time", "currency", "event"]
    labels = C.day_labels(news)
    assert len(C.rule_hits(["USD Building Permits"], labels)) == 1 and len(C.rule_hits(["USD Crude Oil Inventories"], labels)) == 1
    assert len(C.rule_hits(["USD Building Permits", "USD Initial Jobless Claims"], labels)) == 0   # "+" needs both


def test_openbb_normaliser_handles_snake_case_country_and_date_only():
    norm = E.make_openbb_normaliser("UTC")
    r = rows_from([{"date": "2025-03-04T13:30:00.000", "country": "united_states", "event": "PPI MoM", "importance": "high", "currency": None}], norm=norm)[0]
    assert (r["date"], r["time"], r["currency"], r["event"], r["impact"]) == ("2025-03-04", "15:30", "USD", "PPI", "high")
    d = rows_from([{"date": "2025-03-04", "country": "euro_area", "event": "CPI YoY", "importance": None}], norm=norm)[0]
    assert (d["date"], d["currency"], d["impact"]) == ("2025-03-04", "EUR", "low")
    z = rows_from([{"date": "2025-03-04T13:30:00+00:00", "country": "US", "event": "x", "importance": 2}], norm=norm)[0]
    assert z["impact"] == "medium" and z["time"] == "15:30"


def test_fetch_openbb_with_a_stand_in_for_openbb():
    import types, pandas as pd
    calls = {}

    class Cal:
        def to_df(self):
            return pd.DataFrame({"date": pd.to_datetime(["2025-03-04 13:30:00"]), "country": ["united_states"],
                                 "event": ["PPI MoM"], "importance": ["high"]})

    class Eco:
        def calendar(self, **kw):
            calls.update(kw)
            return Cal()

    obb = types.SimpleNamespace(economy=Eco(), user=types.SimpleNamespace(credentials=types.SimpleNamespace()))
    sys.modules["openbb"] = types.SimpleNamespace(obb=obb)
    try:
        recs = E.fetch_openbb(date(2025, 3, 1), date(2025, 3, 31), "SECRET", "fmp")
    finally:
        del sys.modules["openbb"]
    assert calls == {"start_date": "2025-03-01", "end_date": "2025-03-31", "provider": "fmp"}
    assert obb.user.credentials.fmp_api_key == "SECRET" and recs[0]["event"] == "PPI MoM"
    r = rows_from(recs, norm=E.make_openbb_normaliser())[0]
    assert (r["date"], r["currency"]) == ("2025-03-04", "USD")


def test_national_euro_events_get_country_prefix():
    raw = [{"date": "2025-03-04 09:00:00", "country": "Germany", "event": "CPI YoY", "importance": "high", "currency": "EUR"},
           {"date": "2025-03-04 10:00:00", "country": "Euro Zone", "event": "CPI YoY", "importance": "high", "currency": "EUR"}]
    rows = rows_from(raw, norm=E.make_openbb_normaliser())
    texts = sorted(f"{r['currency']} {r['event']}" for r in rows)
    assert texts == ["EUR CPI", "EUR German CPI YoY"]          # only the euro-area one matches the rule "EUR CPI"


def test_openbb_weekly_fallback_when_month_has_no_record():
    import types, pandas as pd
    class Cal:
        def __init__(self, df): self.df = df
        def to_df(self): return self.df
    class Eco:
        def calendar(self, start_date, end_date, provider):
            if (start_date, end_date) == ("2025-08-01", "2025-08-31"):
                raise RuntimeError("[Error] -> Nasdaq Error -> Economic Events Calendar: No record found.")
            if start_date == "2025-08-08":
                raise RuntimeError("No record found.")
            return Cal(pd.DataFrame({"date": [start_date + " 13:30:00"], "country": ["united_states"], "event": ["PPI"], "importance": ["low"]}))
    obb = types.SimpleNamespace(economy=Eco(), user=types.SimpleNamespace(credentials=types.SimpleNamespace()))
    sys.modules["openbb"] = types.SimpleNamespace(obb=obb)
    try:
        recs = E.fetch_openbb(date(2025, 8, 1), date(2025, 8, 31), "", "nasdaq")
    finally:
        del sys.modules["openbb"]
    assert [r["date"][:10] for r in recs] == ["2025-08-01", "2025-08-15", "2025-08-22", "2025-08-29"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
