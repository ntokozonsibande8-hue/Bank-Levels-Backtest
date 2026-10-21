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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
