"""Turn fixtures + odds + model into two ranked shortlists.

Safest : highest model probability of landing.
Value  : highest expected value against the de-vigged market price.

The tool ranks and stops. It does not assemble the acca -- that's your call.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config

MARKET_LABEL = {
    "HOME": "{home} to win",
    "AWAY": "{away} to win",
    "BTTS": "Both teams to score",
}


@dataclass
class Leg:
    div: str
    league: str          # full name, e.g. "Premier League"
    home: str
    away: str
    market: str
    odds: float
    prob: float           # our model's probability
    fair_prob: float      # market's probability, margin removed
    edge: float           # prob - fair_prob
    ev: float             # prob * odds - 1
    xg_home: float
    xg_away: float
    thin: str = ""          # team(s) the model barely knows, if any
    kickoff: object = None  # UK local datetime; shown when not all 3pm Saturday

    @property
    def label(self) -> str:
        return MARKET_LABEL[self.market].format(home=self.home, away=self.away)

    @property
    def fixture(self) -> str:
        return f"{self.home} v {self.away}"

    @property
    def is_3pm_sat(self) -> bool:
        """The main slot, worth marking when a run spans several."""
        k = self.kickoff
        return bool(k and (k.weekday(), k.hour, k.minute)
                    == (config.KICKOFF_WEEKDAY, config.KICKOFF_HOUR,
                        config.KICKOFF_MINUTE))

    @property
    def when(self) -> str:
        """'Sat 15:00' -- only worth showing when the page spans several days."""
        return f"{self.kickoff:%a %H:%M}" if self.kickoff else ""

    @property
    def has_thin(self) -> bool:
        return bool(self.thin)

    @property
    def league_short(self) -> str:
        """PL / CH / L1 / L2 / SPL -- the page is tight on horizontal space."""
        return config.LEAGUES.get(self.div, {}).get("short", self.league)


def _devig_1x2(odds_h, odds_d, odds_a):
    """Strip the bookmaker's margin from a 1X2 market.

    Implied probabilities from odds sum to more than 1; the excess is the
    bookmaker's cut. Normalising by the total gives the market's actual view,
    which is the only fair thing to compare a model against.
    """
    if not all((odds_h, odds_d, odds_a)):
        return None
    raw = [1 / odds_h, 1 / odds_d, 1 / odds_a]
    total = sum(raw)
    return [r / total for r in raw], total - 1.0


def _devig_binary(odds_yes, odds_no):
    if not all((odds_yes, odds_no)):
        return None
    raw = [1 / odds_yes, 1 / odds_no]
    total = sum(raw)
    return [r / total for r in raw], total - 1.0


def build_legs(fixtures, models) -> tuple[list[Leg], list[str]]:
    """Every leg that satisfies the rules, scored both ways."""
    legs, rejected = [], []

    for f in fixtures:
        model = models.get(f.div)
        if model is None:
            continue

        try:
            p = model.probabilities(f.model_home, f.model_away)
        except KeyError as exc:
            rejected.append(f"{f.home} v {f.away}: {exc}")
            continue

        # Which side(s) of this fixture is the model guessing about? A team
        # promoted this summer, or one that has played twice, gets a rating
        # from almost nothing -- worth saying out loud next to a confident
        # looking percentage.
        thin_teams = [t for t in (f.model_home, f.model_away) if model.is_thin(t)]
        thin = ", ".join(thin_teams)

        odds = f.odds or {}
        # When the source gives both a best-available price and a market
        # average, EV is computed from the price you'd actually be paid while
        # the edge is measured against the average, which is the more stable
        # consensus (a Max quote is the most extreme of six firms, so on any
        # one outcome it may be a single bookmaker's error). See the note in
        # fixtures_csv.py -- the effect is small but systematic.
        fair_odds = getattr(f, "fair_odds", None) or odds

        for market in config.MARKETS:
            price = odds.get(market)
            if price is None:
                continue
            if price < config.MIN_ODDS:
                continue                     # your floor, applied here

            prob = p[market]

            # De-vig. If we only have one side of the market we can't remove
            # the margin properly, so fall back to a flat 5% haircut on the
            # raw implied probability -- crude, but honest about direction.
            fair = None
            if market in ("HOME", "AWAY") and fair_odds.get("DRAW"):
                res = _devig_1x2(fair_odds.get("HOME"), fair_odds.get("DRAW"),
                                 fair_odds.get("AWAY"))
                if res:
                    fair = res[0][0 if market == "HOME" else 2]
            elif market == "BTTS" and odds.get("BTTS_NO"):
                res = _devig_binary(odds["BTTS"], odds["BTTS_NO"])
                if res:
                    fair = res[0][0]
            if fair is None:
                fair = (1 / price) * 0.95

            legs.append(Leg(
                div=f.div, league=f.league, home=f.home, away=f.away,
                market=market, odds=price, prob=prob, fair_prob=fair,
                edge=prob - fair, ev=prob * price - 1.0,
                xg_home=p["xg_home"], xg_away=p["xg_away"], thin=thin,
                kickoff=getattr(f, "kickoff_uk", None),
            ))

    return legs, rejected


def shortlists(legs: list[Leg], size: int | None = None):
    """The two columns, plus the legs that appear in both.

    Best value excludes legs resting on a team the model barely knows. See the
    note on EXCLUDE_THIN_FROM_* in config -- thin ratings don't just add noise
    to this list, they systematically win it.
    """
    size = size or config.SHORTLIST_SIZE

    safest_pool = ([l for l in legs if not l.has_thin]
                   if config.EXCLUDE_THIN_FROM_SAFEST else legs)
    value_pool = ([l for l in legs if not l.has_thin]
                  if config.EXCLUDE_THIN_FROM_VALUE else legs)

    safest = sorted(safest_pool, key=lambda l: l.prob, reverse=True)[:size]
    value = sorted(value_pool, key=lambda l: l.ev, reverse=True)[:size]

    key = lambda l: (l.home, l.away, l.market)
    both = {key(l) for l in safest} & {key(l) for l in value}

    return safest, value, both


def held_back(legs: list[Leg]) -> list[Leg]:
    """Legs kept out of the ranked lists because the model barely knows a team.

    Returned so the page can say how many were withheld and why, rather than
    quietly shrinking the lists.
    """
    if not (config.EXCLUDE_THIN_FROM_SWEET or config.EXCLUDE_THIN_FROM_VALUE):
        return []
    return [l for l in legs if l.has_thin]


def sweet_spot(legs: list[Leg], min_prob=None, min_edge=None, size=None) -> list[Leg]:
    """The crossover: likely to land AND priced generously.

    Note this is an absolute filter, not an intersection of the two top-N
    columns. Intersecting the columns makes the section's contents depend on
    how long the columns happen to be, which is arbitrary -- a leg would drop
    out simply because two others were added above it. Thresholds mean a leg
    qualifies on its own merits, and the section is honestly allowed to be
    empty in a week when nothing clears the bar.
    """
    min_prob = config.SWEET_SPOT_MIN_PROB if min_prob is None else min_prob
    min_edge = config.SWEET_SPOT_MIN_EDGE if min_edge is None else min_edge
    size = size or config.SWEET_SPOT_SIZE

    pool = ([l for l in legs if not l.has_thin]
            if config.EXCLUDE_THIN_FROM_SWEET else legs)
    qualifying = [l for l in pool if l.prob >= min_prob and l.edge >= min_edge]
    # Rank by EV: it's what determines return per pound staked. Probability
    # has already done its job as a gate.
    return sorted(qualifying, key=lambda l: l.ev, reverse=True)[:size]


def acca_summary(legs: list[Leg]) -> dict:
    """What a given set of legs actually amounts to.

    Legs are treated as independent, which is close enough for separate
    matches (it is badly wrong for same-game multis, but that's not this).
    """
    if not legs:
        return {"n": 0, "odds": 0.0, "prob": 0.0, "ev": 0.0, "returns_on_10": 0.0}

    combined_odds = 1.0
    combined_prob = 1.0
    for l in legs:
        combined_odds *= l.odds
        combined_prob *= l.prob

    return {
        "n": len(legs),
        "odds": combined_odds,
        "prob": combined_prob,
        "ev": combined_prob * combined_odds - 1.0,
        "returns_on_10": 10.0 * combined_odds,
    }
