"""Shared code: API providers, time conversion, name matching, CSV output."""
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

SAST = timezone(timedelta(hours=2))          # South Africa has no daylight saving
IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}
CSV_COLUMNS = ["date", "time", "currency", "event", "impact", "raw_event"]

COUNTRY_CCY = {
    "US": "USD", "USA": "USD", "United States": "USD", "EU": "EUR", "EMU": "EUR", "Euro Area": "EUR",
    "Eurozone": "EUR", "DE": "EUR", "Germany": "EUR", "FR": "EUR", "France": "EUR", "IT": "EUR", "Italy": "EUR",
    "ES": "EUR", "Spain": "EUR", "GB": "GBP", "UK": "GBP", "United Kingdom": "GBP", "JP": "JPY", "Japan": "JPY",
    "AU": "AUD", "Australia": "AUD", "NZ": "NZD", "New Zealand": "NZD", "CA": "CAD", "Canada": "CAD",
    "CH": "CHF", "Switzerland": "CHF", "CN": "CNY", "China": "CNY",
}

_CCY_NORM = {re.sub(r"[^a-z]", "", k.lower()): v for k, v in COUNTRY_CCY.items()}


def ccy_from_country(country):
    return _CCY_NORM.get(re.sub(r"[^a-z]", "", str(country or "").lower()), "")


# ---------- time and names ----------
def parse_dt(value, assume_tz=timezone.utc):
    """Parse '2025-01-08 13:30:00', '2025-01-08T13:30:00Z' or with an offset. Naive values use assume_tz."""
    s = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s.replace(" ", "T", 1)) if "T" not in s else datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=assume_tz)


def to_sast(dt):
    return dt.astimezone(SAST)


NATIONAL_PREFIX = {"de": "German", "germany": "German", "fr": "French", "france": "French",
                   "it": "Italian", "italy": "Italian", "es": "Spanish", "spain": "Spanish"}


def national_prefix(country, currency):
    if currency.upper() != "EUR":
        return ""
    return NATIONAL_PREFIX.get(re.sub(r"[^a-z]", "", str(country or "").lower()), "")


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def load_aliases(path):
    p = Path(path)
    return yaml.safe_load(p.read_text()) if p.exists() else []


def canonical_name(currency, event, aliases):
    for a in aliases:
        if a["currency"].upper() != currency.upper():
            continue
        if any(re.search(p, event, re.I) for p in a["patterns"]):
            return a["name"]
    return None


def event_text_for_rules(currency, event, aliases):
    """Returns the text to put in the CSV 'event' column so '<CUR> <event>' starts with the rules.yaml wording."""
    name = canonical_name(currency, event, aliases)
    if name:
        return name[len(currency):].strip() if name.upper().startswith(currency.upper() + " ") else name
    return event


# ---------- providers ----------
def month_ranges(start, end):
    """Full calendar months that cover start..end, as (first_day, last_day)."""
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield cur, nxt - timedelta(days=1)
        cur = nxt


def http_json(url, params, what):
    """GET with retries. Never prints the URL, so an API key cannot leak into logs."""
    last = ""
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException as e:
            last = type(e).__name__
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (401, 402, 403):
            raise SystemExit(f"{what}: HTTP {r.status_code}. Check the API key, and that your plan includes the "
                             f"economic calendar and this date range. Response: {r.text[:200]!r}")
        if r.status_code == 429 or r.status_code >= 500:
            last = f"HTTP {r.status_code}"
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise SystemExit(f"{what}: gave up after 5 tries ({last})")


def fetch_fmp(first, last, key):
    data = http_json("https://financialmodelingprep.com/stable/economic-calendar",
                     {"from": first.isoformat(), "to": last.isoformat(), "apikey": key}, "FMP")
    return data if isinstance(data, list) else []


def norm_fmp(r):
    cur = (r.get("currency") or ccy_from_country(r.get("country"))).upper()
    impact = str(r.get("impact") or "").lower()
    return dict(dt=parse_dt(r["date"]), currency=cur, event=clean(r.get("event")),
                impact=impact if impact in IMPACT_RANK else "low", country=r.get("country", ""))


def fetch_tradingeconomics(first, last, key):
    data = http_json(f"https://api.tradingeconomics.com/calendar/country/all/{first}/{last}",
                     {"c": key, "f": "json"}, "TradingEconomics")
    return data if isinstance(data, list) else []


def norm_tradingeconomics(r):
    cur = (r.get("Currency") or ccy_from_country(r.get("Country"))).upper()
    impact = {1: "low", 2: "medium", 3: "high"}.get(int(r.get("Importance") or 1), "low")
    return dict(dt=parse_dt(r["Date"]), currency=cur, event=clean(r.get("Event") or r.get("Category")),
                impact=impact, country=r.get("Country", ""))


def make_jsonfile_normaliser(fields):
    tz = timezone.utc if str(fields.get("datetime_tz", "UTC")).upper() == "UTC" else SAST

    def norm(r):
        cur = str(r.get(fields["currency"]) or ccy_from_country(r.get(fields.get("country", "country")))).upper()
        impact = str(r.get(fields.get("impact", "impact")) or "").lower()
        return dict(dt=parse_dt(r[fields["datetime"]], tz), currency=cur, event=clean(r.get(fields["event"])),
                    impact=impact if impact in IMPACT_RANK else "low", country="")
    return norm


def _openbb_range(obb, sub, first, last):
    df = obb.economy.calendar(start_date=first.isoformat(), end_date=last.isoformat(), provider=sub).to_df()
    return json.loads(df.reset_index().to_json(orient="records", date_format="iso"))


def fetch_openbb(first, last, key, sub):
    """One month via obb.economy.calendar. If the provider says 'No record found' for the whole month,
    retry week by week and keep whatever comes back. (pip install openbb openbb-economy ...)"""
    try:
        from openbb import obb
    except ImportError:
        raise SystemExit("OpenBB is not installed. Run: pip install openbb")
    if key:
        setattr(obb.user.credentials, f"{sub}_api_key", key)

    def scrub(e):                                           # never echo the key
        msg = f"{type(e).__name__}: {e}"
        return msg.replace(key, "***") if key else msg

    try:
        return _openbb_range(obb, sub, first, last)
    except Exception as e:
        if "No record found" not in str(e):
            raise SystemExit(f"OpenBB ({sub}): {scrub(e)[:300]}")
    rows, empty, cur = [], 0, first
    while cur <= last:
        stop = min(cur + timedelta(days=6), last)
        try:
            rows += _openbb_range(obb, sub, cur, stop)
        except Exception as e:
            if "No record found" not in str(e):
                raise SystemExit(f"OpenBB ({sub}): {scrub(e)[:300]}")
            empty += 1
        cur = stop + timedelta(days=1)
    print(f"  WARNING {first:%Y-%m}: whole-month request had no records; weekly retry got {len(rows)} rows "
          f"({empty} empty weeks). Check this month.")
    return rows


def make_openbb_normaliser(tz_name="UTC"):
    tz = timezone.utc if str(tz_name).upper() == "UTC" else SAST

    def pick(r, *names):
        for n in names:
            if r.get(n) not in (None, ""):
                return r[n]
        return None

    def norm(r):
        raw_dt = str(pick(r, "date", "datetime", "time"))
        cur = str(pick(r, "currency") or ccy_from_country(pick(r, "country"))).upper()
        imp = str(pick(r, "importance", "impact") or "").lower()
        imp = {"1": "low", "2": "medium", "3": "high"}.get(imp, imp)
        return dict(dt=parse_dt(raw_dt[:19] if len(raw_dt) > 10 and "+" not in raw_dt and "Z" not in raw_dt else raw_dt, tz),
                    currency=cur, event=clean(pick(r, "event", "category")),
                    impact=imp if imp in IMPACT_RANK else "low", country=str(pick(r, "country") or ""))
    return norm


FETCHERS = {"fmp": (fetch_fmp, norm_fmp), "tradingeconomics": (fetch_tradingeconomics, norm_tradingeconomics)}


def raw_events(provider, start, end, key, raw_dir, cfg):
    """Raw API rows for every month touching start..end. Finished months are cached on disk."""
    if provider == "jsonfile":
        j = cfg["jsonfile"]
        rows = json.loads(Path(j["path"]).read_text())
        return rows, make_jsonfile_normaliser(j["fields"])
    if provider == "openbb":
        o = cfg.get("openbb", {})
        sub = o.get("provider", "fmp")
        fetch = lambda f, l, k: fetch_openbb(f, l, k, sub)
        norm = make_openbb_normaliser(o.get("tz", "UTC"))
        provider = f"openbb_{sub}"                               # cache folder name
    else:
        fetch, norm = FETCHERS[provider]
    rows = []
    for first, last in month_ranges(start, end):
        cache = Path(raw_dir) / provider / f"{first:%Y-%m}.json"
        if cache.exists() and last < date.today():
            rows += json.loads(cache.read_text())
            continue
        data = fetch(first, last, key)
        print(f"  {first:%Y-%m}: {len(data)} rows")
        if last < date.today() and data:             # the current month still changes; empty months are retried
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
        rows += data
    return rows, norm


def build_rows(raw, norm, start, end, aliases, min_impact="low", currencies=()):
    out, seen, skipped = [], set(), 0
    wanted = {c.upper() for c in currencies}
    for r in raw:
        try:
            e = norm(r)
        except (KeyError, ValueError, TypeError):
            skipped += 1
            continue
        local = to_sast(e["dt"])
        if not (start <= local.date() <= end) or not e["currency"] or not e["event"]:
            continue
        if IMPACT_RANK[e["impact"]] < IMPACT_RANK[min_impact] or (wanted and e["currency"] not in wanted):
            continue
        pre = national_prefix(e.get("country"), e["currency"])
        shown = f"{pre} {e['event']}" if pre and not e["event"].lower().startswith(pre.lower()) else e["event"]
        row = dict(date=local.strftime("%Y-%m-%d"), time=local.strftime("%H:%M"), currency=e["currency"],
                   event=shown if pre else event_text_for_rules(e["currency"], e["event"], aliases),
                   impact=e["impact"], raw_event=e["event"])
        key = (row["date"], row["time"], row["currency"], row["raw_event"], pre)
        if key not in seen:
            seen.add(key)
            out.append(row)
    out.sort(key=lambda x: (x["date"], x["time"], x["currency"], x["event"]))
    return out, skipped


def write_csv(rows, path):
    import csv
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
