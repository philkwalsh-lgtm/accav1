#!/usr/bin/env python3
"""Replay last season and ask whether the tool would have made money.

This is the step that decides whether to trust the shortlist. It walks
forward through the season refitting the model on only what was known at the
time, so there is no lookahead.

    python backtest.py
    python backtest.py --season 2526 --legs 6

Note the honest framing: accumulators compound the bookmaker's margin, so a
model merely as good as the market still loses. What we're testing is whether
it is better than the market, not whether it is any good.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from accatool import config, data, model as M


def implied_fair(row):
    """De-vigged home/draw/away probabilities from the closing odds."""
    o = [row.get("odds_h"), row.get("odds_d"), row.get("odds_a")]
    if any(pd.isna(x) or x is None for x in o):
        return None
    raw = [1 / x for x in o]
    total = sum(raw)
    return [r / total for r in raw]


def run(season: str, n_legs: int, min_odds: float, refit_every: int):
    print(f"Backtesting {season}, {n_legs}-fold, min odds {min_odds}\n")

    hist = data.load_results(seasons=config.SEASONS)
    target = hist[hist["date"] >= pd.Timestamp(f"20{season[:2]}-08-01")]
    target = target[target["date"] < pd.Timestamp(f"20{season[2:]}-07-01")]

    if target.empty:
        print(f"No matches found for season {season}.")
        return

    saturdays = sorted({d for d in target["date"].dt.normalize().unique()
                        if pd.Timestamp(d).weekday() == 5})
    print(f"{len(saturdays)} match Saturdays, {len(target):,} matches\n")

    results = {"safest": [], "value": []}
    models, last_fit = {}, None

    for n, sat in enumerate(saturdays):
        sat = pd.Timestamp(sat)

        # Refit periodically on everything before this Saturday. Refitting
        # every week is more correct but slow; every 4 is close enough.
        if last_fit is None or n - last_fit >= refit_every:
            models = M.fit_all(hist, as_of=sat, verbose=False)
            last_fit = n
        if not models:
            continue

        day = target[target["date"].dt.normalize() == sat]
        legs = []

        for _, r in day.iterrows():
            m = models.get(r["div"])
            if m is None or r["home"] not in m.attack or r["away"] not in m.attack:
                continue
            fair = implied_fair(r)
            if fair is None:
                continue

            p = m.probabilities(r["home"], r["away"])
            actual_home = 1 if r["hg"] > r["ag"] else 0
            actual_away = 1 if r["ag"] > r["hg"] else 0

            for market, prob, price, won in (
                ("HOME", p["HOME"], r["odds_h"], actual_home),
                ("AWAY", p["AWAY"], r["odds_a"], actual_away),
            ):
                if price is None or pd.isna(price) or price < min_odds:
                    continue
                f = fair[0] if market == "HOME" else fair[2]
                legs.append({"prob": prob, "odds": float(price), "won": won,
                             "ev": prob * float(price) - 1.0, "edge": prob - f})

        if len(legs) < n_legs:
            continue

        for label, key in (("safest", "prob"), ("value", "ev")):
            picks = sorted(legs, key=lambda x: x[key], reverse=True)[:n_legs]
            odds = float(np.prod([x["odds"] for x in picks]))
            landed = all(x["won"] for x in picks)
            results[label].append({"odds": odds, "landed": landed,
                                   "prob": float(np.prod([x["prob"] for x in picks])),
                                   "legs_won": sum(x["won"] for x in picks)})

    # ------------------------------------------------------------- report
    print(f"{'':10s} {'accas':>6s} {'landed':>7s} {'staked':>9s} "
          f"{'returned':>9s} {'ROI':>8s} {'avg legs':>9s}")
    print("-" * 62)
    for label in ("safest", "value"):
        rows = results[label]
        if not rows:
            print(f"{label:10s} no complete weeks")
            continue
        staked = 10.0 * len(rows)
        returned = sum(10.0 * r["odds"] for r in rows if r["landed"])
        landed = sum(r["landed"] for r in rows)
        avg_legs = np.mean([r["legs_won"] for r in rows])
        roi = (returned - staked) / staked * 100
        print(f"{label:10s} {len(rows):6d} {landed:7d} {staked:9.0f} "
              f"{returned:9.2f} {roi:+7.1f}% {avg_legs:8.2f}/{n_legs}")

    print("\nCalibration check -- predicted vs actual acca strike rate:")
    for label in ("safest", "value"):
        rows = results[label]
        if rows:
            pred = np.mean([r["prob"] for r in rows]) * 100
            act = np.mean([r["landed"] for r in rows]) * 100
            print(f"  {label:8s} predicted {pred:5.2f}%   actual {act:5.2f}%   (n={len(rows)})")

    print("\nA negative ROI here is the expected result, not a bug: six legs means "
          "\nthe bookmaker's margin applied six times. What you're looking for is "
          "\nwhether one column loses meaningfully less than the other, and whether "
          "\nthe predicted strike rate matches the actual one.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2526", help="e.g. 2526")
    ap.add_argument("--legs", type=int, default=6)
    ap.add_argument("--min-odds", type=float, default=config.MIN_ODDS)
    ap.add_argument("--refit-every", type=int, default=4,
                    help="refit the model every N Saturdays")
    a = ap.parse_args()
    run(a.season, a.legs, a.min_odds, a.refit_every)
