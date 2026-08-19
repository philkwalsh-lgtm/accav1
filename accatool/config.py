"""Configuration for the 3pm acca shortlist tool.

Everything you might want to change lives here.
"""

from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- your rules

UK = ZoneInfo("Europe/London")

# Which kick-off slots count. Each entry is (weekday, hour, minute), in UK
# local time, with Monday = 0. Add a line to widen it -- nothing else needs
# changing.
#
#   SLOTS = [(5, 15, 0)]                       Saturday 3pm only  <- current
#   SLOTS = [(5, 15, 0), (6, 14, 0)]           + Sunday 2pm
#   SLOTS = [(5, 15, 0), (1, 19, 45), (2, 19, 45)]   + Tuesday and Wednesday nights
#
# Or ignore slots entirely for a run with:  python run.py --days 8
SLOTS = [(5, 15, 0)]

# Kept as the single source of truth for the "main ritual" slot, which is the
# one highlighted on the page when several are in play.
KICKOFF_WEEKDAY, KICKOFF_HOUR, KICKOFF_MINUTE = SLOTS[0]
MIN_ODDS = 1.50            # price floor per leg
SHORTLIST_SIZE = 12        # legs shown in each of the two columns

# --------------------------------------------------------------- sweet spot
# The crossover section: legs that are BOTH likely to land AND priced
# generously. Raise MIN_PROB for a shorter, safer list; raise MIN_EDGE to
# demand a bigger disagreement with the market.
#
# Worth understanding what this filter does and doesn't do. It does NOT raise
# expected ROI -- a 25% shot at +8% edge returns the same per pound as an 80%
# shot at +8% edge. What it does is two other things that matter more for an
# acca:
#   1. Cuts variance. Every leg must land, so six 70% legs beat six 35% legs
#      with the same edge by a mile (11.8% vs 0.2% chance of landing).
#   2. Filters model error. A +200% edge on a 12.0 shot is almost never free
#      money -- it's the model being wrong about a team it barely knows.
#      Demanding decent probability throws out most of those artefacts.
SWEET_SPOT_MIN_PROB = 0.55   # must land at least this often
SWEET_SPOT_MIN_EDGE = 0.03   # must beat the fair price by 3+ percentage points
SWEET_SPOT_SIZE = 10

# Markets we will consider. BTTS "No" is deliberately excluded --
# your rule is "win or BTTS", and BTTS-No is neither.
MARKETS = ("HOME", "AWAY", "BTTS")


# ------------------------------------------------------------------ leagues
# football-data.co.uk division code  ->  API-Football league id
#
# The API-Football ids below are the standard ones, but verify them once on
# your account with:  python run.py verify
# (it calls /leagues and prints what your key actually sees).

LEAGUES = {
    "E0":  {"name": "Premier League",       "short": "PL",  "api_football_id": 39},
    "E1":  {"name": "Championship",         "short": "CH",  "api_football_id": 40},
    "E2":  {"name": "League One",           "short": "L1",  "api_football_id": 41},
    "E3":  {"name": "League Two",           "short": "L2",  "api_football_id": 42},
    "SC0": {"name": "Scottish Premiership", "short": "SPL", "api_football_id": 179},
}

# Seasons of history to fit the model on. More is not better -- squads turn
# over. Two full seasons plus the current one is the sweet spot.
SEASONS = ("2425", "2526", "2627")

FOOTBALL_DATA_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"


# -------------------------------------------------------------------- model

# Time-decay half-life in days. A result 6 months ago carries half the weight
# of one played yesterday. Dixon-Coles originally used ~0.0065/day; this is
# the same idea expressed in units you can reason about.
HALF_LIFE_DAYS = 180

MAX_GOALS = 10             # score matrix truncation; P(>10 goals) is ~0


# ------------------------------------------------------------- API-Football

API_FOOTBALL_HOST = "https://v3.football.api-sports.io"

# Bet type ids used by the /odds endpoint.
BET_MATCH_WINNER = 1       # "Match Winner"  -> Home / Draw / Away
BET_BTTS = 8               # "Both Teams Score" -> Yes / No

# If your group all bets with one firm, put its API-Football bookmaker name
# here (e.g. "Bet365") and prices will be taken from it alone. Leave as None
# to use the median price across all bookmakers, which is a fair proxy for
# "what you'll actually get" and avoids chasing a price nobody can take.
PREFERRED_BOOKMAKER = None

REQUESTS_PER_DAY = 100     # free tier ceiling, used for the budget warning
