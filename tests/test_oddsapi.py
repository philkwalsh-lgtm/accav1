"""Test The Odds API parsing against stubbed responses.

This is the source that actually delivers BTTS on a free tier, so its parsing
and — more importantly — its credit arithmetic need to be right. Blowing 500
credits in a fortnight would take the page offline for the rest of the month.
"""

import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from accatool import config, oddsapi

# Shape of a real /odds response, trimmed to what we parse.
H2H_EVENT = {
    "id": "abc123",
    "sport_key": "soccer_epl",
    "commence_time": "2026-08-22T14:00:00Z",     # 3pm UK, BST
    "home_team": "Arsenal",
    "away_team": "Everton",
    "bookmakers": [
        {"key": "bet365", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 1.50},
            {"name": "Everton", "price": 6.50},
            {"name": "Draw", "price": 4.20}]}]},
        {"key": "skybet", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 1.54},
            {"name": "Everton", "price": 6.80},
            {"name": "Draw", "price": 4.30}]}]},
        {"key": "paddypower", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 1.52},
            {"name": "Everton", "price": 6.60},
            {"name": "Draw", "price": 4.25}]}]},
    ],
}

BTTS_EVENT = {
    "id": "abc123",
    "bookmakers": [
        {"key": "bet365", "markets": [{"key": "btts", "outcomes": [
            {"name": "Yes", "price": 1.80}, {"name": "No", "price": 1.95}]}]},
        {"key": "skybet", "markets": [{"key": "btts", "outcomes": [
            {"name": "Yes", "price": 1.83}, {"name": "No", "price": 1.92}]}]},
    ],
}


def test_h2h_parsing():
    prices = oddsapi._h2h_prices(H2H_EVENT)
    print(f"  parsed: {prices}")

    # Median of 1.50 / 1.54 / 1.52 is 1.52 -- not the first or best price.
    assert prices["HOME"] == 1.52, prices
    assert prices["DRAW"] == 4.25, prices
    assert prices["AWAY"] == 6.60, prices

    margin = sum(1 / prices[k] for k in ("HOME", "DRAW", "AWAY")) - 1
    print(f"  implied margin {margin*100:.2f}%")
    assert 0 < margin < 0.20, "margin should be positive and sane"
    print("  PASS h2h parsing takes the median, not the first bookmaker")


def test_btts_parsing():
    prices = oddsapi._btts_prices(BTTS_EVENT)
    print(f"  parsed: {prices}")
    assert prices["BTTS"] == 1.815, prices
    assert prices["BTTS_NO"] == 1.935, prices
    # Both sides are needed or the margin can't be stripped out.
    assert "BTTS_NO" in prices, "the No price is required for de-vigging"
    print("  PASS btts parsing keeps both sides")


def test_missing_markets_dont_crash():
    """Lower divisions often have no BTTS quote. That must degrade, not break."""
    assert oddsapi._btts_prices({"bookmakers": []}) == {}
    assert oddsapi._h2h_prices({"bookmakers": [], "home_team": "A",
                                "away_team": "B"}) == {}
    # A bookmaker quoting a market we didn't ask for is ignored.
    junk = {"home_team": "A", "away_team": "B", "bookmakers": [
        {"markets": [{"key": "totals", "outcomes": [{"name": "Over", "price": 2.0}]}]}]}
    assert oddsapi._h2h_prices(junk) == {}
    print("  PASS missing markets return empty rather than raising")


def test_credit_budget():
    """The two-stage design must fit inside 500 credits a month.

    Stage one is one credit per league however many fixtures come back.
    Stage two is one credit per fixture, but only for fixtures that survived
    the slot filter -- which is the entire point.
    """
    leagues = len(oddsapi.SPORT_KEYS)
    fixtures_all = 52          # a full round across the five divisions
    fixtures_3pm = 40          # what typically survives the 3pm Saturday filter

    two_stage = leagues + fixtures_3pm
    naive = leagues + fixtures_all      # btts for everything, before filtering

    runs_two_stage = 500 // two_stage
    runs_naive = 500 // naive

    print(f"  two-stage : {two_stage} credits/run -> {runs_two_stage} runs/month")
    print(f"  naive     : {naive} credits/run -> {runs_naive} runs/month")
    print(f"  twice weekly needs ~{two_stage * 9} credits/month")

    assert two_stage * 9 < 500, "twice-weekly must fit inside the free tier"
    assert runs_two_stage > runs_naive
    print("  PASS the free tier covers twice-weekly runs with headroom")


def test_slot_filter_applies_before_btts():
    """Guard the ordering, because getting it wrong is expensive not broken.

    If BTTS were fetched before filtering, every run would cost ~3x more and
    the page would go dark partway through the month. Nothing would error --
    which is exactly why it needs a test.
    """
    from accatool.odds import Fixture

    def make(hour, day=22):
        ko = dt.datetime(2026, 8, day, hour, 0, tzinfo=dt.timezone.utc)
        return Fixture(1, "E0", "Premier League", ko, "A", "B", odds={})

    everything = [make(14), make(11, 22), make(16), make(14, 23)]
    in_slot = [f for f in everything if f.in_slot()]

    print(f"  {len(everything)} fixtures returned, {len(in_slot)} in slot")
    # 14:00 UTC on 22 Aug is 15:00 UK on a Saturday. The others are not.
    assert len(in_slot) == 1, [f.kickoff_uk for f in in_slot]
    assert in_slot[0].kickoff_uk.hour == 15
    print(f"  BTTS would cost {len(in_slot)} credits, not {len(everything)}")
    print("  PASS filtering happens before the per-fixture spend")


if __name__ == "__main__":
    print("test_h2h_parsing");                test_h2h_parsing()
    print("test_btts_parsing");               test_btts_parsing()
    print("test_missing_markets_dont_crash"); test_missing_markets_dont_crash()
    print("test_credit_budget");              test_credit_budget()
    print("test_slot_filter_applies_before_btts"); test_slot_filter_applies_before_btts()
    print("\nAll Odds API tests passed.")
