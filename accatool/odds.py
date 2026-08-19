"""Fixtures and odds from API-Football, plus a mock mode.

One request per fixture returns every bookmaker and every bet type, so a full
Saturday round costs roughly 45 requests against a 100/day free allowance.
We deliberately do NOT filter by bet id server-side -- that would cost a
request per market instead of per fixture.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass

import numpy as np
import requests

from . import config


@dataclass
class Fixture:
    fixture_id: int
    div: str
    league: str
    kickoff_utc: dt.datetime
    home: str
    away: str
    odds: dict = None          # {"HOME": 2.1, "AWAY": 3.4, "BTTS": 1.8}

    @property
    def kickoff_uk(self) -> dt.datetime:
        return self.kickoff_utc.astimezone(config.UK)

    def in_slot(self) -> bool:
        """Does this fixture fall in one of the slots we bet?

        Compared in UK local time, always. Doing it in UTC silently drops
        every fixture during BST, when 3pm local is 14:00 UTC -- roughly half
        the season.
        """
        k = self.kickoff_uk
        return (k.weekday(), k.hour, k.minute) in config.SLOTS

    # Old name, kept so existing callers and tests keep working.
    is_3pm_saturday = in_slot


class ApiFootball:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY")
        if not self.api_key:
            raise RuntimeError(
                "No API key. Set API_FOOTBALL_KEY in your environment, or run "
                "with --mock to see the tool work on simulated fixtures."
            )
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.api_key})
        self.requests_used = 0

    def _get(self, path: str, **params):
        url = f"{config.API_FOOTBALL_HOST}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        self.requests_used += 1
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football error on {path}: {payload['errors']}")
        return payload.get("response", [])

    # ------------------------------------------------------------- discovery

    def verify_leagues(self):
        """Print the league ids your key actually sees, so you can confirm
        the ids in config.py before trusting them."""
        print("Checking league ids against your account...\n")
        for div, meta in config.LEAGUES.items():
            try:
                res = self._get("/leagues", id=meta["api_football_id"])
            except Exception as exc:
                print(f"  {div:4s} id={meta['api_football_id']:<4} ERROR {exc}")
                continue
            if not res:
                print(f"  {div:4s} id={meta['api_football_id']:<4} NOT FOUND")
                continue
            info = res[0]["league"]
            country = res[0]["country"]["name"]
            match = "ok" if meta["name"].lower() in info["name"].lower() else "CHECK THIS"
            print(f"  {div:4s} id={meta['api_football_id']:<4} -> "
                  f"{info['name']} ({country})  [{match}]")
        print(f"\n{self.requests_used} requests used.")

    # -------------------------------------------------------------- fixtures

    def fixtures_for_date(self, date: dt.date, season: int,
                          until: dt.date | None = None) -> list[Fixture]:
        """Every fixture in our five leagues on a date, or across a range.

        One request per league covers the whole window, so widening from a
        single Saturday to a full week costs nothing extra here -- the per
        fixture odds calls are what use the quota.
        """
        end = until or date
        out = []
        for div, meta in config.LEAGUES.items():
            res = self._get("/fixtures", league=meta["api_football_id"],
                            season=season, **{"from": date.isoformat(),
                                              "to": end.isoformat()})
            for item in res:
                ko = dt.datetime.fromisoformat(
                    item["fixture"]["date"].replace("Z", "+00:00"))
                out.append(Fixture(
                    fixture_id=item["fixture"]["id"],
                    div=div,
                    league=meta["name"],
                    kickoff_utc=ko,
                    home=item["teams"]["home"]["name"],
                    away=item["teams"]["away"]["name"],
                ))
        return out

    # ------------------------------------------------------------------ odds

    def odds_for_fixture(self, fixture: Fixture) -> dict:
        """Match-winner and BTTS prices in a single request."""
        res = self._get("/odds", fixture=fixture.fixture_id)
        if not res:
            return {}

        # We collect the draw and BTTS-No prices too. We never bet them, but
        # without the other side of the market you cannot strip the
        # bookmaker's margin out, and the value column depends on that.
        buckets = {"HOME": [], "DRAW": [], "AWAY": [], "BTTS": [], "BTTS_NO": []}

        for book in res[0].get("bookmakers", []):
            if (config.PREFERRED_BOOKMAKER
                    and book.get("name") != config.PREFERRED_BOOKMAKER):
                continue
            for bet in book.get("bets", []):
                if bet.get("id") == config.BET_MATCH_WINNER:
                    for v in bet.get("values", []):
                        val, odd = str(v.get("value", "")).lower(), v.get("odd")
                        if odd is None:
                            continue
                        if val in ("home", "1"):
                            buckets["HOME"].append(float(odd))
                        elif val in ("draw", "x"):
                            buckets["DRAW"].append(float(odd))
                        elif val in ("away", "2"):
                            buckets["AWAY"].append(float(odd))
                elif bet.get("id") == config.BET_BTTS:
                    for v in bet.get("values", []):
                        val, odd = str(v.get("value", "")).lower(), v.get("odd")
                        if odd is None:
                            continue
                        if val == "yes":
                            buckets["BTTS"].append(float(odd))
                        elif val == "no":
                            buckets["BTTS_NO"].append(float(odd))

        def pick(prices):
            # Median across bookmakers: a fair proxy for the price you'll
            # actually get, and immune to one outlier bookmaker.
            return float(np.median(prices)) if prices else None

        return {k: p for k, v in buckets.items() if (p := pick(v)) is not None}

    def enrich_with_odds(self, fixtures: list[Fixture], pause: float = 0.2):
        for i, f in enumerate(fixtures, 1):
            try:
                f.odds = self.odds_for_fixture(f)
            except Exception as exc:
                print(f"  ! odds failed for {f.home} v {f.away}: {exc}")
                f.odds = {}
            print(f"  [{i}/{len(fixtures)}] {f.home} v {f.away}: "
                  f"{f.odds or 'no odds'}")
            time.sleep(pause)
        return fixtures


# ------------------------------------------------------------------ mock mode

def _mock_prices(rng, margin: float = 0.06) -> dict:
    """Plausible bookmaker prices, built the way a bookmaker builds them:
    pick true probabilities, then shade them by a margin."""
    # 1X2
    p = rng.dirichlet([4.0, 2.6, 3.2])
    over = 1.0 + margin
    h, d, a = (float(x) for x in p)
    # BTTS
    py = float(rng.uniform(0.42, 0.68))

    return {
        "HOME": round(1.0 / (h * over), 2),
        "DRAW": round(1.0 / (d * over), 2),
        "AWAY": round(1.0 / (a * over), 2),
        "BTTS": round(1.0 / (py * over), 2),
        "BTTS_NO": round(1.0 / ((1 - py) * over), 2),
    }


def mock_fixtures(seed: int = 0) -> list[Fixture]:
    """A plausible Saturday, so the pipeline can be exercised without a key.

    Team names deliberately match football-data.co.uk's spellings so the
    end-to-end run works; real API-Football names differ and are handled by
    the matcher in names.py.
    """
    rng = np.random.default_rng(seed)

    rounds = {
        "E0": [("Arsenal", "Everton"), ("Brighton", "Fulham"), ("Newcastle", "Wolves"),
               ("Nott'm Forest", "Brentford"), ("Crystal Palace", "West Ham")],
        "E1": [("Leeds", "Millwall"), ("Norwich", "Coventry"), ("Watford", "Preston"),
               ("Bristol City", "Swansea"), ("Hull", "Blackburn"), ("Stoke", "Cardiff")],
        "E2": [("Bolton", "Barnsley"), ("Wigan", "Reading"), ("Charlton", "Lincoln"),
               ("Peterboro", "Blackpool"), ("Exeter", "Burton"), ("Wycombe", "Shrewsbury")],
        "E3": [("Bradford", "Walsall"), ("Notts County", "Chesterfield"),
               ("Crewe", "Grimsby"), ("Salford", "Colchester"), ("Swindon", "Barrow")],
        "SC0": [("Celtic", "St Johnstone"), ("Rangers", "Motherwell"),
                ("Hearts", "Dundee"), ("Hibernian", "Kilmarnock")],
    }

    # Next Saturday at 3pm UK.
    today = dt.datetime.now(config.UK).date()
    days_ahead = (config.KICKOFF_WEEKDAY - today.weekday()) % 7 or 7
    sat = today + dt.timedelta(days=days_ahead)
    ko_uk = dt.datetime(sat.year, sat.month, sat.day, 15, 0, tzinfo=config.UK)
    ko_utc = ko_uk.astimezone(dt.timezone.utc)

    fixtures, fid = [], 1000
    for div, pairs in rounds.items():
        for home, away in pairs:
            fid += 1
            fixtures.append(Fixture(
                fixture_id=fid, div=div, league=config.LEAGUES[div]["name"],
                kickoff_utc=ko_utc, home=home, away=away,
                odds=_mock_prices(rng),
            ))
    return fixtures
