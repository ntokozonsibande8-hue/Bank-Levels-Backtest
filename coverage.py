"""Check how well the calendar matches your DayTrade rules.

Usage: python coverage.py [--csv data/news_events.csv] [--rules rules.yaml]
Prints, for every rule, how many days it fired. A rule at 0 days usually means the provider words the
release differently: add a pattern to aliases.yaml. Also lists the most common unmatched events.
"""
import argparse
from collections import Counter

import pandas as pd
import yaml


def day_labels(news):
    labels = {}
    for d, cur, ev in zip(pd.to_datetime(news["date"]).dt.date, news["currency"], news["event"]):
        labels.setdefault(d, []).append(f"{cur} {ev}".lower().strip())
    return labels


def rule_hits(rule, labels):
    return {d for d, ls in labels.items() if all(any(l.startswith(e.lower()) for l in ls) for e in rule)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/news_events.csv")
    ap.add_argument("--rules", default="rules.yaml")
    a = ap.parse_args()
    news = pd.read_csv(a.csv)
    news.columns = news.columns.str.strip().str.lower()
    rules = yaml.safe_load(open(a.rules))
    labels = day_labels(news)
    span = f"{news['date'].min()} to {news['date'].max()}"
    print(f"{len(news)} events on {len(labels)} days ({span})\n")
    used_prefixes, zero = [], []
    for market, m in rules.items():
        print(f"== {market}")
        for kind in ("trade", "dont"):
            for rule in m.get(kind, []):
                used_prefixes += [e.lower() for e in rule]
                n = len(rule_hits(rule, labels))
                flag = "   <-- 0 days, check aliases.yaml" if n == 0 else ""
                if n == 0:
                    zero.append(f"{market}/{kind}: {' + '.join(rule)}")
                print(f"  {kind:5} {n:4} days  {' + '.join(rule)}{flag}")
        td = set().union(*[rule_hits(r, labels) for r in m.get("trade", [])] or [set()])
        dd = set().union(*[rule_hits(r, labels) for r in m.get("dont", [])] or [set()])
        print(f"  -> tradable days (trade and no don't-trade): {len(td - dd)} | blocked by don't-trade: {len(td & dd)}\n")
    cur_in_rules = {p.split()[0] for p in used_prefixes}
    cnt = Counter()
    for cur, ev in zip(news["currency"], news["event"]):
        text = f"{cur} {ev}".lower()
        if cur.lower() in cur_in_rules and not any(text.startswith(p) for p in used_prefixes):
            cnt[f"{cur} {ev}"] += 1
    print("Most common events NOT used by any rule (for finding missing aliases):")
    for name, n in cnt.most_common(30):
        print(f"  {n:4}  {name}")
    if zero:
        print(f"\n{len(zero)} rule(s) never fired. If they should have, fix aliases.yaml before backtesting.")


if __name__ == "__main__":
    main()
