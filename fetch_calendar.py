"""Download the economic calendar and write data/news_events.csv (date,time,currency,event + extras), in SAST.

Usage:
  export CALENDAR_API_KEY=...        (in GitHub: repo Settings > Secrets > Actions > CALENDAR_API_KEY)
  python fetch_calendar.py --start 2024-07-01 --end 2026-10-20 [--provider openbb|fmp|tradingeconomics|jsonfile]
"""
import argparse
import os
from datetime import date

import yaml

import econlib as E


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="calendar_config.yaml")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--provider")
    ap.add_argument("--min-impact")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    provider = a.provider or cfg["provider"]
    key = os.environ.get("CALENDAR_API_KEY", "")
    needs_key = provider not in ("jsonfile",) and not (provider == "openbb" and cfg.get("openbb", {}).get("provider") == "nasdaq")
    if needs_key and not key:
        raise SystemExit("CALENDAR_API_KEY is not set. Add it as a repository secret (never paste it in a file).")
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    print(f"provider={provider} {start} -> {end} (SAST dates)")
    raw, norm = E.raw_events(provider, start, end, key, cfg["raw_dir"], cfg)
    rows, skipped = E.build_rows(raw, norm, start, end, E.load_aliases(cfg["aliases_file"]),
                                 a.min_impact or cfg["min_impact"], cfg.get("currencies") or [])
    if not rows:
        raise SystemExit("No events came back for that range. Check the dates, your plan and the provider.")
    E.write_csv(rows, cfg["output"])
    days = len({r["date"] for r in rows})
    print(f"wrote {len(rows)} events on {days} days -> {cfg['output']}  (unparseable rows skipped: {skipped})")
    print(f"first {rows[0]['date']} {rows[0]['time']}  last {rows[-1]['date']} {rows[-1]['time']}")


if __name__ == "__main__":
    main()
