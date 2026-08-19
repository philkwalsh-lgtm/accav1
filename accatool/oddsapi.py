"""Fixtures and odds from The Odds API — including BTTS, on the free tier.

Why this exists: API-Football's free plan is capped at seasons 2022-2024, so
it cannot see the current season at all. Their marketing says "all plans
include all endpoints, all data types, no paywalled features", which is true
of endpoints and false of seasons. Current-season access starts at $19/month.

The Odds API has no season restriction — it serves upcoming and live events by
definition — and its free tier explicitly covers all betting markets, BTTS
included. 500 credits a month.

Credit arithmetic, which is the whole design constraint:

    h2h for one league   = 1 credit, and returns EVERY upcoming fixture
    btts for one fixture = 1 credit, per fixture, from the event endpoint

So we pull h2h for all five leagues (5 credits), throw away everything that
isn't in a betting slot, and only then spend a credit per surviving fixture on
BTTS. A Saturday 3pm round is ~40 fixtures, so ~45 credits per run. Twice a
week is ~390/month, inside the free 500 with room to spare.

Fetching BTTS for every fixture first would cost ~130 a run and blow the
allowance in a fortnight.
"""

from __future__ import annotations

import datetime as dt
import os
import time

import numpy as np
import requests

from . import config
from .odds import Fixture

HOST = "https://api.the-odds-api.com/v4"

# football-data.co.uk division code -> The Odds API sport key
SPORT_KEYS = {
    "E0":  "soccer_epl",
    "E1":  "soccer_efl_champ",
    "E2":  "soccer_england_league1",
    "E3":  "soccer_england_league2",
    "SC0": "soccer_spl",
}

REGION = "uk"


class OddsApi:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "No key. Set ODDS_API_KEY in your environment. Free key from "
                "https://the-odds-api.com/ — 500 credits/month, no card.")
        self.session = requests.Session()
        self.credits_used = 0
        self.credits_left = None

    def _get(self, path: str, **params):
        params["apiKey"] = self.api_key
        resp = self.session.get(f"{HOST}{path}", params=params, timeout=30)

        # The API reports the running total in response headers, which is more
        # trustworthy than counting calls ourselves.
        used = resp.headers.get("x-requests-used")
        left = resp.headers.get("x-requests-remaining")
        if used is not None:
            self.credits_used = int(used)
        if left is not None:
            self.credits_left = int(left)

        if resp.status_code == 401:
            raise RuntimeError("The Odds API rejected the key (401). Check ODDS_API_KEY.")
        if resp.status_code == 429:
            raise RuntimeError(
                f"Out of credits (429). Used {self.credits_used} this month.")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------- stage 1: h2h

    def fixtures_with_h2h(self) -> list[Fixture]:
        """Every upcoming fixture in the five leagues, with match-result odds.

        One credit per league regardless of how many fixtures come back.
        """
        out = []
        for div, sport in SPORT_KEYS.items():
            try:
                events = self._get(f"/sports/{sport}/odds",
                                   regions=REGION, markets="h2h",
                                   oddsFormat="decimal")
            except requests.HTTPError as exc:
                # An out-of-season league 404s; that is not fatal.
                print(f"  ! {div} ({sport}): {exc}")
                continue

            for ev in events:
                ko = dt.datetime.fromisoformat(
                    ev["commence_time"].replace("Z", "+00:00"))
                f = Fixture(
                    fixture_id=ev["id"],
                    div=div,
                    league=config.LEAGUES[div]["name"],
                    kickoff_utc=ko,
                    home=ev["home_team"],
                    away=ev["away_team"],
                    odds=_h2h_prices(ev),
                )
                f.sport_key = sport
                out.append(f)
        return out

    # ------------------------------------------------------ stage 2: btts

    def add_btts(self, fixtures: list[Fixture], pause: float = 0.15):
        """One credit per fixture. Only ever called on the shortlist."""
        for i, f in enumerate(fixtures, 1):
            try:
                ev = self._get(
                    f"/sports/{f.sport_key}/events/{f.fixture_id}/odds",
                    regions=REGION, markets="btts", oddsFormat="decimal")
                got = _btts_prices(ev)
                f.odds.update(got)
                status = f"btts {got.get('BTTS', '—')}"
            except Exception as exc:
                status = f"no btts ({exc})"
            print(f"  [{i}/{len(fixtures)}] {f.home} v {f.away}: {status}")
            time.sleep(pause)
        return fixtures


# ------------------------------------------------------------------ parsing

def _median(prices):
    return float(np.median(prices)) if prices else None


def _h2h_prices(event: dict) -> dict:
    """Median home/draw/away across the bookmakers quoting this event."""
    home, draw, away = [], [], []
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for o in market.get("outcomes", []):
                name, price = o.get("name"), o.get("price")
                if price is None:
                    continue
                if name == event.get("home_team"):
                    home.append(float(price))
                elif name == event.get("away_team"):
                    away.append(float(price))
                elif str(name).lower() == "draw":
                    draw.append(float(price))

    return {k: v for k, v in (("HOME", _median(home)),
                              ("DRAW", _median(draw)),
                              ("AWAY", _median(away))) if v is not None}


def _btts_prices(event: dict) -> dict:
    """Yes and No. We never bet No, but without it the margin can't be
    stripped out, and the value column depends on that."""
    yes, no = [], []
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "btts":
                continue
            for o in market.get("outcomes", []):
                name = str(o.get("name", "")).lower()
                price = o.get("price")
                if price is None:
                    continue
                if name == "yes":
                    yes.append(float(price))
                elif name == "no":
                    no.append(float(price))

    return {k: v for k, v in (("BTTS", _median(yes)),
                              ("BTTS_NO", _median(no))) if v is not None}
