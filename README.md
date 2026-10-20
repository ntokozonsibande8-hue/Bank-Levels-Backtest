# Bank levels backtest (H1, SAST)

Backtests the AS / AR "bank levels" strategy on H1 candles, only on days your DayTrade news rules say "trade".

## Quick start
```
pip install -r requirements.txt
python tests/test_engine.py                      # engine sanity checks
python fetch_data.py --config config.yaml --start 2025-01-06 --end 2025-01-10   # small test first
python fetch_data.py --config config.yaml        # full download into data/
# put your calendar in data/news_events.csv (date,time,currency,event; dates in SAST)
python backtest.py --config config.yaml          # results/summary.csv, trade logs, equity PNGs
python backtest.py --config config.yaml --no-news-filter   # same, every day, no news rules
```
No Dukascopy? Export H1 candles from TradingView / your broker as `data/<SYMBOL>.csv` with columns
`time_sast,open,high,low,close` (convert times to SAST first).

## Rules implemented
- AS = 00:00-07:00 (H1 candles 00-06), AR = 00:00-10:00 (candles 00-09), high/low include wicks.
- Currencies, GER40, UK100 use AS. US30 and Nasdaq use AR (edit `config.yaml` to change).
- Range R = high - low. Buy levels below the low (0% = low), sell levels above the high (0% = high).
- Entry: limit order in the 75%-100% zone. Tested at the 75% level, the midpoint and the 100% level.
- Stop: 150% level. Target: AS/AR high for buys, low for sells.
- Results are in R multiples (1R = entry-to-stop distance). No spread, commission or slippage.

## Assumptions I made (change them in backtest.py if wrong)
1. Entries are limit orders filled at the level (or the open if price gaps past it).
2. One trade per day per symbol; if both sides trigger, the earlier entry is taken.
3. If price reaches the target before the entry level is touched, no trade.
4. When SL and TP are hit in the same H1 candle, SL counts first. On the entry candle only the stop is checked.
5. Trades still open at the end of the day close at the 23:00 candle close (`EOD`).
6. "No H1 close beyond 100%": with limit entries inside the zone, price always touches the entry before it can close beyond 100%, so this rule never blocks an entry. I therefore test it as an option: `invalidation exit on` closes the trade at the first H1 close beyond 100%; `off` just keeps the 150% stop.
7. News: a day is tradable only if a "trade" rule fires and no "don't trade" rule fires. "+" rules need both releases that day. Event names match by prefix, so check your calendar's wording against `rules.yaml`.

## Caveats
- `fetch_data.py` was written without internet access and is untested against the live server. Compare a few candles with your chart first and check the printed prices (the price scale for indices may need adjusting in `point()`).
- Backtests don't include execution costs. Past results don't guarantee future performance.
