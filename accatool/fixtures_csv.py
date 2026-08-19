"""Upcoming fixtures and odds from football-data.co.uk — no API key, no signup.

football-data.co.uk publishes `fixtures.csv`: every upcoming fixture across its
leagues with match-result odds from six UK bookmakers, collected Friday
afternoons for the weekend. Same source as the historical CSVs, which means
**the team names match exactly** — the whole name-matching problem disappears.

    Div,Date,Time,HomeTeam,AwayTeam,Referee,
    B365H,B365D,B365A,   Bet365
    BFDH,BFDD,BFDA,      Betfair Sportsbook
    BVH,BVD,BVA,         BetVictor
    BWH,BWD,BWA,         Bet&Win
    PPH,PPD,PPA,         Paddy Power
    SKBH,SKBD,SKBA,      Sky Bet
    MaxH,MaxD,MaxA,      best price available anywhere
    AvgH,AvgD,AvgA       market average

The one thing it does NOT carry is a both-teams-to-score market. If you want
BTTS legs you need the API-Football key; win-only works with nothing at all.
"""

from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import requests

from . import config
from .odds import Fixture

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

# Which bookmaker columns to read as the price you'd actually take.
#   "Max" — best price available anywhere, if you're willing to shop around
#   "Avg" — market average, what you'll get without trying
#   "B365", "SKB", "PP", "BV", "BW", "BFD" — one specific firm
PRICE_SOURCE = "Max"

# The margin is measured against the market AVERAGE, while the price you're
# credited with is the best available. Two different jobs:
#
#   Max -> what you'd actually be paid, so it drives EV. Take the best price;
#          there's no virtue in a worse one.
#   Avg -> the market's consensus view, so it drives the edge. It's the more
#          stable estimator: a Max price is by construction the most extreme
#          quote across six firms, so on any given outcome it can be one
#          bookmaker's error rather than a signal.
#
# Worth being precise about what this does and doesn't fix. De-vigged
# probabilities always sum to 1 either way, so using Max doesn't inflate every
# edge -- it RESHAPES them, because bookmakers don't spread their margin evenly
# across outcomes. Measured on real-shaped prices the difference is a few
# tenths of a point per leg, sometimes up, sometimes down. Small, but it's a
# systematic choice rather than an accident, so it's made explicitly here.
FAIR_SOURCE = "Avg"


def _cols(prefix):
    return f"{prefix}H", f"{prefix}D", f"{prefix}A"


def fetch(url: str = FIXTURES_URL) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.BytesIO(resp.content), encoding="latin-1",
                       on_bad_lines="skip")


def load_fixtures(target: dt.date, price_source: str | None = None,
                  fair_source: str | None = None,
                  until: dt.date | None = None) -> list[Fixture]:
    """Fixtures in our five leagues, with odds attached.

    One date by default. Pass `until` for an inclusive range -- the file holds
    midweek fixtures too (it is refreshed Tuesday afternoons for those), so a
    range picks up Sunday afternoon and Tuesday night games as well.
    """
    price_source = price_source or PRICE_SOURCE
    fair_source = fair_source or FAIR_SOURCE

    df = fetch()
    df = df[df["Div"].isin(config.LEAGUES.keys())].copy()

    df["_date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dt.date
    if until is None:
        df = df[df["_date"] == target]
    else:
        df = df[(df["_date"] >= target) & (df["_date"] <= until)]

    ph, pd_, pa = _cols(price_source)
    fh, fd, fa = _cols(fair_source)

    missing = [c for c in (ph, pd_, pa) if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"fixtures.csv has no {price_source} columns (missing {missing}). "
            f"Set PRICE_SOURCE in fixtures_csv.py to one of: "
            f"Max, Avg, B365, SKB, PP, BV, BW, BFD")

    out = []
    for _, r in df.iterrows():
        # The Time column is already UK local time, which is what we filter on.
        day = r["_date"]
        try:
            hh, mm = str(r["Time"]).strip().split(":")[:2]
            ko_uk = dt.datetime(day.year, day.month, day.day,
                                int(hh), int(mm), tzinfo=config.UK)
        except (ValueError, AttributeError, TypeError):
            continue

        def num(col):
            v = r.get(col)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None
            return v if v > 1.0 else None

        odds = {}
        for market, pcol in (("HOME", ph), ("DRAW", pd_), ("AWAY", pa)):
            v = num(pcol)
            if v is not None:
                odds[market] = v

        # Carry the average prices separately so the de-vig can use them.
        fair_odds = {}
        for market, fcol in (("HOME", fh), ("DRAW", fd), ("AWAY", fa)):
            v = num(fcol)
            if v is not None:
                fair_odds[market] = v

        f = Fixture(
            fixture_id=0,
            div=r["Div"],
            league=config.LEAGUES[r["Div"]]["name"],
            kickoff_utc=ko_uk.astimezone(dt.timezone.utc),
            home=str(r["HomeTeam"]).strip(),
            away=str(r["AwayTeam"]).strip(),
            odds=odds,
        )
        f.fair_odds = fair_odds or None
        out.append(f)

    return out


def available_dates() -> list[dt.date]:
    """What the current fixtures.csv actually covers -- useful for a sanity check."""
    df = fetch()
    df = df[df["Div"].isin(config.LEAGUES.keys())]
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dt.date
    return sorted(d for d in dates.dropna().unique())
