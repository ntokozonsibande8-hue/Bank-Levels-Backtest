# Economic calendar fetcher

Pulls economic calendar events from an API and writes `data/news_events.csv` (`date,time,currency,event,impact,raw_event`),
with dates and times in SAST (GMT+2). That file is exactly what the bank levels backtest reads for your DayTrade news rules.
It can be dropped into the Bank-Levels-Backtest repo (no file names clash) or used on its own.

## Setup (once)
1. Default provider is `openbb` (`pip install openbb`), which wraps `fmp`, `nasdaq` and `tradingeconomics`; choose the one under
   `openbb:` in `calendar_config.yaml`. `nasdaq` needs no key; `fmp` and `tradingeconomics` do. Direct `fmp` / `tradingeconomics`
   calls are also built in. Check that your plan includes the economic calendar AND history back to your start date.
2. In the GitHub repo: Settings > Secrets and variables > Actions > New repository secret.
   Name `CALENDAR_API_KEY`, value = your key. Never paste the key into a file or a chat.

## Run
Actions > Fetch economic calendar > Run workflow. Choose start, end and provider.
Result: `news_events.csv` and `coverage_report.txt` in the run's `calendar` artifact; the CSV is also committed to `data/`.
Finished months are cached, so reruns only fetch what is new. The current month is never cached.

Locally: `pip install -r requirements.txt`, `export CALENDAR_API_KEY=...`,
`python fetch_calendar.py --start 2024-07-01 --end 2026-10-20`, then `python coverage.py`.

## Matching your rules (important)
Providers word releases differently from forex.com ("ADP Nonfarm Employment Change" vs "ADP Nonfarm Employment").
`aliases.yaml` rewrites provider names to the wording in `rules.yaml`; the original goes in `raw_event`.
Run `coverage.py` after every fetch: any rule showing **0 days** needs a new pattern in `aliases.yaml`,
and the "most common unmatched events" list shows the provider's wording. Fix these before trusting a news-filtered backtest.

## Your own data (provider `jsonfile`)
If you already download calendar JSON (e.g. in DayTrade), put it in `data/manual/calendar.json`, set the field names under
`jsonfile:` in `calendar_config.yaml`, and run with `--provider jsonfile`.

## Notes
- OpenBB's column names and time zone are assumed (date, country, event, importance, currency; times in UTC). Verify on a few
  known releases (e.g. a US PPI should land at 15:30 SAST) and set `openbb.tz` if the times are off.
- The API providers were written from their public documentation without network access and are UNTESTED against
  the live services. Everything else (time zones, name matching, CSV format, coverage) is covered by `tests/test_calendar.py`.
  Run a one-month fetch first and check the coverage report.
- Impact filter: `min_impact: low` keeps everything, matching your DayTrade setting.
- Error messages never print the request URL, so the key is not leaked into logs.
