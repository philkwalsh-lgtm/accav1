"""End-to-end test of the whole pipeline on simulated history.

The sandbox this was built in cannot reach football-data.co.uk, so this test
generates a synthetic history for exactly the teams in mock_fixtures and runs
every stage: fit -> fixtures -> 3pm filter -> name match -> rank -> HTML.

On your machine the real run.py downloads the real CSVs instead; everything
downstream of that is what this test exercises.
"""

import sys
import pathlib
import datetime as dt

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from accatool import config, model, names, odds as odds_mod, rank, report


def synthetic_history(seed=42, seasons=2):
    """Two seasons of results for the teams used in mock_fixtures."""
    rng = np.random.default_rng(seed)
    fixtures = odds_mod.mock_fixtures()

    by_div = {}
    for f in fixtures:
        by_div.setdefault(f.div, set()).update([f.home, f.away])

    rows = []
    for div, teams in by_div.items():
        teams = sorted(teams)
        # Each division gets its own scoring environment, as in real life.
        base = {"E0": 0.10, "E1": 0.02, "E2": -0.02, "E3": -0.08, "SC0": 0.0}[div]
        attack = rng.normal(base, 0.30, len(teams))
        attack -= attack.mean() - base
        defence = rng.normal(0, 0.25, len(teams))

        date = pd.Timestamp("2024-08-01")
        for _ in range(seasons):
            for i, h in enumerate(teams):
                for j, a in enumerate(teams):
                    if i == j:
                        continue
                    lam = np.exp(attack[i] + defence[j] + 0.26)
                    mu = np.exp(attack[j] + defence[i])
                    rows.append({"date": date, "div": div, "home": h, "away": a,
                                 "hg": rng.poisson(lam), "ag": rng.poisson(mu)})
                    date += pd.Timedelta(hours=8)

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def test_pipeline():
    print("  generating synthetic history...")
    matches = synthetic_history()
    print(f"    {len(matches):,} matches across {matches['div'].nunique()} divisions")

    print("  fitting models...")
    models = model.fit_all(matches, verbose=True)
    assert len(models) == 5, f"expected 5 divisions, fitted {len(models)}"

    print("  building fixtures...")
    fixtures = odds_mod.mock_fixtures()
    print(f"    {len(fixtures)} fixtures")

    print("  applying 3pm Saturday filter...")
    three_pm = [f for f in fixtures if f.is_3pm_saturday()]
    print(f"    {len(three_pm)} at 3pm UK")
    assert len(three_pm) == len(fixtures), "3pm filter dropped fixtures it shouldn't"

    print("  resolving team names...")
    resolved, unmatched = names.resolve_fixtures(three_pm, models)
    for u in unmatched:
        print(f"    ! {u}")
    assert not unmatched, f"{len(unmatched)} teams unmatched"
    print(f"    all {len(resolved)} fixtures matched")

    print("  ranking legs...")
    legs, rejected = rank.build_legs(resolved, models)
    print(f"    {len(legs)} legs clear the rules")
    assert legs, "no legs produced"

    # Every leg must obey every rule.
    for l in legs:
        assert l.odds >= config.MIN_ODDS, f"leg below odds floor: {l.odds}"
        assert l.market in config.MARKETS, f"illegal market: {l.market}"
        assert 0.0 < l.prob < 1.0, f"impossible probability: {l.prob}"
        assert l.div in config.LEAGUES, f"illegal league: {l.div}"
    print("    all legs obey the four rules")

    safest, value, both = rank.shortlists(legs)
    assert len(safest) == config.SHORTLIST_SIZE
    assert len(value) == config.SHORTLIST_SIZE

    # Safest must be sorted by probability, value by EV.
    assert all(safest[i].prob >= safest[i + 1].prob for i in range(len(safest) - 1))
    assert all(value[i].ev >= value[i + 1].ev for i in range(len(value) - 1))
    print(f"    columns correctly ordered; {len(both)} leg(s) in both")

    print("\n  SAFEST (top 5)")
    for l in safest[:5]:
        print(f"    {l.prob*100:5.1f}%  {l.odds:5.2f}  {l.label:34s} {l.league}")
    print("  VALUE (top 5)")
    for l in value[:5]:
        print(f"    {l.ev*100:+5.1f}%  {l.odds:5.2f}  {l.label:34s} {l.league}")

    print("\n  checking acca maths...")
    six = rank.acca_summary(safest[:6])
    manual_odds = np.prod([l.odds for l in safest[:6]])
    manual_prob = np.prod([l.prob for l in safest[:6]])
    assert abs(six["odds"] - manual_odds) < 1e-9
    assert abs(six["prob"] - manual_prob) < 1e-9
    print(f"    six-fold: {six['odds']:.2f} at {six['prob']*100:.1f}% "
          f"-- £10 returns £{six['returns_on_10']:.2f}")

    # Sanity: a six-fold of legs each above the 1.50 floor must pay > 11x.
    assert six["odds"] > 1.5 ** 6, "six-fold odds below the floor implies a bug"

    print("\n  checking sweet spot gate...")
    sweet = rank.sweet_spot(legs)
    print(f"    {len(sweet)} legs clear both bars "
          f"(>={config.SWEET_SPOT_MIN_PROB*100:.0f}% and "
          f">=+{config.SWEET_SPOT_MIN_EDGE*100:.0f}pt)")
    for l in sweet:
        assert l.prob >= config.SWEET_SPOT_MIN_PROB, f"prob gate leaked: {l.prob}"
        assert l.edge >= config.SWEET_SPOT_MIN_EDGE, f"edge gate leaked: {l.edge}"
    assert all(sweet[i].ev >= sweet[i + 1].ev for i in range(len(sweet) - 1)), \
        "sweet spot not ordered by EV"
    # Every sweet-spot leg must also be in the full leg list, and no leg that
    # clears both bars may be missing from it.
    should_qualify = [l for l in legs
                      if l.prob >= config.SWEET_SPOT_MIN_PROB
                      and l.edge >= config.SWEET_SPOT_MIN_EDGE]
    assert len(sweet) == min(len(should_qualify), config.SWEET_SPOT_SIZE), \
        "sweet spot dropped legs that should qualify"
    for l in sweet[:5]:
        print(f"    {l.prob*100:5.1f}%  {l.odds:5.2f}  edge {l.edge*100:+5.1f}pt  "
              f"{l.label:32s} {l.league}")
    print("    gate holds")

    # An impossible bar must produce an empty section, not a crash.
    assert rank.sweet_spot(legs, min_prob=0.999, min_edge=0.5) == []
    print("    empty case handled")

    sweet_summary = rank.acca_summary(sweet[:6])

    print("  rendering HTML...")
    html_out = report.render(safest, value, both, legs, {
        "date": "22 August 2026", "n_fixtures": len(resolved),
        "n_matches": len(matches), "mode": "simulated data (test)",
    }, sweet=sweet, sweet_summary=sweet_summary)
    out = pathlib.Path(__file__).resolve().parent.parent / "sample-shortlist.html"
    out.write_text(html_out, encoding="utf-8")
    assert "<table" in html_out and len(html_out) > 4000
    print(f"    wrote {out.name} ({len(html_out):,} bytes)")

    print("\n  PASS full pipeline")


def test_bst_timezone_trap():
    """The bug that would silently delete half a season."""
    # 22 Aug 2026 is a Saturday in BST: 3pm UK == 14:00 UTC.
    summer = odds_mod.Fixture(
        1, "E0", "Premier League",
        dt.datetime(2026, 8, 22, 14, 0, tzinfo=dt.timezone.utc), "A", "B")
    # 12 Dec 2026 is a Saturday in GMT: 3pm UK == 15:00 UTC.
    winter = odds_mod.Fixture(
        2, "E0", "Premier League",
        dt.datetime(2026, 12, 12, 15, 0, tzinfo=dt.timezone.utc), "A", "B")
    # A 15:00 UTC kick-off in August is 4pm UK -- must NOT qualify.
    decoy = odds_mod.Fixture(
        3, "E0", "Premier League",
        dt.datetime(2026, 8, 22, 15, 0, tzinfo=dt.timezone.utc), "A", "B")

    assert summer.is_3pm_saturday(), "BST fixture wrongly excluded"
    assert winter.is_3pm_saturday(), "GMT fixture wrongly excluded"
    assert not decoy.is_3pm_saturday(), "4pm BST fixture wrongly included"
    print("  PASS BST/GMT handling "
          f"(summer 14:00Z -> {summer.kickoff_uk:%H:%M}, "
          f"winter 15:00Z -> {winter.kickoff_uk:%H:%M}, "
          f"decoy 15:00Z Aug -> {decoy.kickoff_uk:%H:%M} correctly rejected)")


def test_devig():
    """De-vigging must remove the margin and return a proper distribution."""
    fair, margin = rank._devig_1x2(2.10, 3.40, 3.80)
    print(f"  1X2 2.10/3.40/3.80 -> margin {margin*100:.2f}%, "
          f"fair {[round(f,4) for f in fair]}")
    assert abs(sum(fair) - 1.0) < 1e-12, "de-vigged probabilities must sum to 1"
    assert margin > 0, "positive margin expected"
    # Every fair probability must be below its raw implied probability.
    for f, o in zip(fair, (2.10, 3.40, 3.80)):
        assert f < 1 / o
    print("  PASS de-vig")


if __name__ == "__main__":
    print("test_bst_timezone_trap"); test_bst_timezone_trap()
    print("test_devig");             test_devig()
    print("test_pipeline");          test_pipeline()
    print("\nAll pipeline tests passed.")
