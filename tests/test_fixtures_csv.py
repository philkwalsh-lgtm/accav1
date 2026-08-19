"""Test the key-free fixtures.csv path against a stubbed file.

The sandbox this was built in has no network, so we feed the parser a CSV with
the real column layout instead of downloading one.
"""

import sys
import pathlib
import datetime as dt

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from accatool import config, fixtures_csv, rank, model
from accatool.odds import Fixture

# Real header from https://www.football-data.co.uk/fixtures.csv
HEADER = ("Div,Date,Time,HomeTeam,AwayTeam,Referee,"
          "B365H,B365D,B365A,BFDH,BFDD,BFDA,BVH,BVD,BVA,BWH,BWD,BWA,"
          "PPH,PPD,PPA,SKBH,SKBD,SKBA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA")

ROWS = [
    # 3pm Saturday, should be kept
    "E0,22/08/2026,15:00,Arsenal,Everton,M Oliver,"
    "1.50,4.20,6.50,1.48,4.30,6.40,1.52,4.10,6.60,1.49,4.25,6.45,"
    "1.51,4.15,6.55,1.50,4.20,6.50,1.55,4.40,6.80,1.50,4.20,6.50",
    # 12:30 kick-off, must be excluded
    "E0,22/08/2026,12:30,Brighton,Fulham,A Taylor,"
    "2.00,3.50,3.80,1.98,3.55,3.75,2.02,3.45,3.85,1.99,3.52,3.78,"
    "2.01,3.48,3.82,2.00,3.50,3.80,2.05,3.60,3.90,2.00,3.50,3.80",
    # 3pm Saturday, League Two
    "E3,22/08/2026,15:00,Bradford,Walsall,J Smith,"
    "2.20,3.30,3.20,2.18,3.35,3.15,2.22,3.25,3.25,2.19,3.32,3.18,"
    "2.21,3.28,3.22,2.20,3.30,3.20,2.30,3.40,3.35,2.20,3.30,3.20",
    # 3pm Saturday, Scottish Premiership
    "SC0,22/08/2026,15:00,Celtic,St Johnstone,W Collum,"
    "1.25,6.00,11.0,1.24,6.10,10.5,1.26,5.90,11.5,1.25,6.05,10.8,"
    "1.25,5.95,11.2,1.25,6.00,11.0,1.28,6.20,12.0,1.25,6.00,11.0",
    # Different day, must be excluded
    "E1,23/08/2026,15:00,Leeds,Millwall,S Attwell,"
    "1.80,3.60,4.50,1.78,3.65,4.45,1.82,3.55,4.55,1.79,3.62,4.48,"
    "1.81,3.58,4.52,1.80,3.60,4.50,1.85,3.70,4.60,1.80,3.60,4.50",
    # A league we don't bet, must be excluded
    "SP1,22/08/2026,15:00,Ath Madrid,Malaga,X Estrada,"
    "1.40,4.80,7.50,1.38,4.90,7.40,1.42,4.70,7.60,1.39,4.85,7.45,"
    "1.41,4.75,7.55,1.40,4.80,7.50,1.45,5.00,7.80,1.40,4.80,7.50",
]

STUB = HEADER + "\n" + "\n".join(ROWS) + "\n"


def test_parsing(monkeypatch_target=None):
    import io
    fixtures_csv.fetch = lambda url=None: pd.read_csv(io.StringIO(STUB))

    target = dt.date(2026, 8, 22)
    fixtures = fixtures_csv.load_fixtures(target)

    print(f"  parsed {len(fixtures)} fixtures for {target}")
    for f in fixtures:
        print(f"    {f.div:4s} {f.kickoff_uk:%H:%M} {f.home} v {f.away}  "
              f"H={f.odds.get('HOME')} D={f.odds.get('DRAW')} A={f.odds.get('AWAY')}")

    # On 22/08 in our five leagues: Arsenal 15:00, Brighton 12:30,
    # Bradford 15:00, Celtic 15:00. SP1 excluded (wrong league),
    # Leeds excluded (23/08, wrong day).
    assert len(fixtures) == 4, f"expected 4 fixtures on the date, got {len(fixtures)}"
    assert {f.div for f in fixtures} == {"E0", "E3", "SC0"}
    assert not any(f.div == "SP1" for f in fixtures), "foreign league leaked in"
    assert not any(f.home == "Leeds" for f in fixtures), "wrong date leaked in"

    three_pm = [f for f in fixtures if f.is_3pm_saturday()]
    assert len(three_pm) == 3, f"3pm filter wrong: {len(three_pm)}"
    assert all(f.kickoff_uk.hour == 15 for f in three_pm)
    assert not any(f.home == "Brighton" for f in three_pm), "12:30 fixture leaked in"
    print(f"  3pm filter kept {len(three_pm)} of {len(fixtures)}")
    print("  PASS parsing and filtering")


def test_price_vs_fair_source():
    """Price comes from Max, the margin is measured against Avg."""
    import io
    fixtures_csv.fetch = lambda url=None: pd.read_csv(io.StringIO(STUB))

    f = [x for x in fixtures_csv.load_fixtures(dt.date(2026, 8, 22))
         if x.home == "Arsenal"][0]

    # Row has Max 1.55/4.40/6.80 and Avg 1.50/4.20/6.50.
    assert f.odds["HOME"] == 1.55, f"price should come from Max, got {f.odds['HOME']}"
    assert f.fair_odds["HOME"] == 1.50, f"fair should come from Avg, got {f.fair_odds['HOME']}"

    max_margin = sum(1 / f.odds[k] for k in ("HOME", "DRAW", "AWAY")) - 1
    avg_margin = sum(1 / f.fair_odds[k] for k in ("HOME", "DRAW", "AWAY")) - 1
    print(f"  Max prices imply {max_margin*100:+.2f}% margin")
    print(f"  Avg prices imply {avg_margin*100:+.2f}% margin")
    assert avg_margin > max_margin, "best-available should show less margin than average"
    print("  PASS: Max is a shopping-around price (margin largely competed "
          "away),\n        Avg is the market consensus -- different jobs, "
          "used for different things")


def test_devig_source_changes_edge():
    """De-vigging Max instead of Avg changes the edge -- so the choice must be
    deliberate.

    Note what this does NOT show. De-vigged probabilities sum to 1 either way,
    so switching source doesn't uniformly inflate edges; it reshapes them,
    because bookmakers spread their margin unevenly across outcomes. On
    real-shaped prices the difference is a few tenths of a point per leg and
    the sign varies. We assert only that it MATTERS, which is the honest
    claim, and that EV correctly uses the best-available price.
    """
    fake = Fixture(0, "E0", "Premier League",
                   dt.datetime(2026, 8, 22, 14, 0, tzinfo=dt.timezone.utc),
                   "Arsenal", "Everton",
                   odds={"HOME": 1.55, "DRAW": 4.40, "AWAY": 6.80})
    fake.model_home, fake.model_away = "Arsenal", "Everton"

    m = model.DivisionModel(div="E0", teams=["Arsenal", "Everton"],
                            attack={"Arsenal": 0.35, "Everton": -0.10},
                            defence={"Arsenal": -0.25, "Everton": 0.10},
                            home_adv=0.26, rho=-0.05)

    # With Avg as the fair source.
    fake.fair_odds = {"HOME": 1.50, "DRAW": 4.20, "AWAY": 6.50}
    legs_avg, _ = rank.build_legs([fake], {"E0": m})
    # With Max as the fair source (the mistake).
    fake.fair_odds = None
    legs_max, _ = rank.build_legs([fake], {"E0": m})

    ea = [l for l in legs_avg if l.market == "HOME"][0]
    em = [l for l in legs_max if l.market == "HOME"][0]
    print(f"  edge de-vigged against Avg: {ea.edge*100:+.3f}pt   (what we use)")
    print(f"  edge de-vigged against Max: {em.edge*100:+.3f}pt")
    print(f"  difference: {abs(em.edge - ea.edge)*100:.3f} percentage points")

    assert abs(em.edge - ea.edge) > 1e-6, "fair source should change the edge"
    # EV must always be computed from the price you'd actually be paid.
    assert abs(ea.odds - 1.55) < 1e-9, "EV should use the best-available price"
    assert abs(ea.ev - (ea.prob * 1.55 - 1)) < 1e-12
    print("  EV uses the best-available price (1.55), edge uses the average")
    print("  PASS")


def test_slots_are_configurable():
    """Editing config.SLOTS must be all it takes to widen the net.

    Today the group only plays Saturday 3pm, but the whole point of putting
    slots in config is that adding Sunday or a midweek night later is one
    line, not a rewrite. This proves that.
    """
    import io
    import pandas as pd
    fixtures_csv.fetch = lambda url=None: pd.read_csv(io.StringIO(STUB))

    fixtures = fixtures_csv.load_fixtures(dt.date(2026, 8, 22))
    original = config.SLOTS

    try:
        # Saturday 3pm only -- the current setting.
        config.SLOTS = [(5, 15, 0)]
        sat = [f for f in fixtures if f.in_slot()]
        print(f"  Saturday 3pm only        -> {len(sat)} fixture(s)")
        assert len(sat) == 3, f"expected 3, got {len(sat)}"
        assert all(f.kickoff_uk.hour == 15 for f in sat)

        # Add the 12:30 Saturday slot; the same file now yields one more.
        config.SLOTS = [(5, 15, 0), (5, 12, 30)]
        wider = [f for f in fixtures if f.in_slot()]
        print(f"  + Saturday 12:30         -> {len(wider)} fixture(s)")
        assert len(wider) == 4, f"expected 4, got {len(wider)}"
        assert any(f.home == "Brighton" for f in wider), "12:30 game not picked up"

        # A slot nothing falls in yields nothing, rather than erroring.
        config.SLOTS = [(2, 19, 45)]
        none = [f for f in fixtures if f.in_slot()]
        print(f"  Wednesday 19:45 only     -> {len(none)} fixture(s)")
        assert none == []
    finally:
        config.SLOTS = original

    print("  PASS slots are configurable")


if __name__ == "__main__":
    print("test_parsing");                 test_parsing()
    print("test_price_vs_fair_source");    test_price_vs_fair_source()
    print("test_devig_source_changes_edge"); test_devig_source_changes_edge()
    print("test_slots_are_configurable"); test_slots_are_configurable()
    print("\nAll fixtures.csv tests passed.")
