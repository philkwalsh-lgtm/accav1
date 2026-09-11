#!/usr/bin/env python3
"""3pm acca shortlist tool.

    python run.py                     # this Saturday. NO API KEY NEEDED.
    python run.py --date 2026-08-22
    python run.py --source api        # adds BTTS legs; needs a free key
    python run.py --mock              # simulated data, fetches nothing
    python run.py verify              # check API-Football league ids
    python run.py --refresh           # re-download historical results

By default this uses football-data.co.uk's free fixtures.csv -- real UK
bookmaker prices (Bet365, Sky Bet, Paddy Power, BetVictor, Betfair, Bet&Win),
no signup, no key, no quota. The only thing it lacks is a BTTS market, so the
default run produces win legs only.

Outputs shortlist.html.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import sys
import webbrowser

from accatool import (config, data, demo, fixtures_csv, model, names,
                      odds as odds_mod, oddsapi, rank, report)


def next_saturday(from_date: dt.date | None = None) -> dt.date:
    d = from_date or dt.datetime.now(config.UK).date()
    return d + dt.timedelta(days=(config.KICKOFF_WEEKDAY - d.weekday()) % 7)


def season_for(date: dt.date) -> int:
    """API-Football labels a season by the year it starts in."""
    return date.year if date.month >= 7 else date.year - 1


def doctor() -> int:
    """Check everything the tool needs, and say which part is broken.

    'It didn't work' has several very different causes -- missing package,
    blocked network, file not refreshed yet, no 3pm games that week. This
    tells them apart so you're not guessing.
    """
    ok = True
    print("Checking your setup...\n")

    # ---- packages
    print("Packages")
    for mod in ("numpy", "pandas", "scipy", "requests"):
        try:
            m = __import__(mod)
            print(f"  ok    {mod:10s} {getattr(m, '__version__', '?')}")
        except ImportError:
            print(f"  FAIL  {mod:10s} not installed "
                  f"-- run: pip install -r requirements.txt")
            ok = False
    if not ok:
        return 1

    # ---- offline pipeline
    print("\nOffline pipeline (no network needed)")
    try:
        from accatool import demo
        h = demo.synthetic_history()
        models = model.fit_all(h, verbose=False)
        print(f"  ok    model fits: {len(models)} divisions from "
              f"{len(h):,} synthetic matches")
    except Exception as exc:
        print(f"  FAIL  model could not fit: {exc}")
        return 1

    # ---- historical results
    print("\nHistorical results (football-data.co.uk)")
    try:
        matches = data.load_results(verbose=False)
        latest = matches["date"].max()
        age = (dt.datetime.now() - latest.to_pydatetime()).days
        print(f"  ok    {len(matches):,} matches, latest {latest:%d %b %Y} "
              f"({age} days ago)")
        for div in config.LEAGUES:
            n = int((matches["div"] == div).sum())
            flag = "ok  " if n >= 50 else "thin"
            print(f"  {flag}  {div:4s} {config.LEAGUES[div]['name']:22s} {n:5d} matches")
    except Exception:
        print("  FAIL  could not reach www.football-data.co.uk")
        print("        Everything else is fine -- this is a network problem, not")
        print("        a setup one. Check a proxy, VPN, or corporate firewall.")
        ok = False

    # ---- upcoming fixtures
    print("\nUpcoming fixtures (fixtures.csv)")
    try:
        dates = fixtures_csv.available_dates()
        if not dates:
            print("  WARN  file reachable but lists none of your five leagues.")
            print("        It's refreshed Friday afternoons for the weekend.")
        else:
            print(f"  ok    covers {len(dates)} date(s): "
                  f"{', '.join(f'{d:%a %d %b}' for d in dates[:8])}")
            sat = next_saturday()
            fx = fixtures_csv.load_fixtures(sat)
            three = [f for f in fx if f.is_3pm_saturday()]
            print(f"  ok    Saturday {sat:%d %b}: {len(fx)} fixtures, "
                  f"{len(three)} at 3pm UK")
            if fx and not three:
                print("        (fixtures exist but none at 3pm -- TV-heavy round?)")
            if not fx:
                print(f"        Nothing yet for {sat:%d %b}. Try again Friday.")
    except Exception:
        print("  FAIL  could not reach fixtures.csv (same host as above)")
        ok = False

    # ---- optional API key
    print("\nAPI-Football key (optional -- only needed for BTTS legs)")
    if os.environ.get("API_FOOTBALL_KEY"):
        print("  ok    API_FOOTBALL_KEY is set; --source api available")
    else:
        print("  --    not set. Fine: the default source needs no key.")

    print("\n" + ("All good. Run: python run.py --open"
                  if ok else
                  "Something above needs fixing. Meanwhile "
                  "`python run.py --mock --open` works offline."))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the 3pm acca shortlist.")
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "verify", "doctor"])
    ap.add_argument("--source", choices=["free", "oddsapi", "api"], default="free",
                    help="free: football-data.co.uk fixtures.csv, no key, no "
                         "BTTS (default). "
                         "oddsapi: The Odds API, free key, INCLUDES BTTS. "
                         "api: API-Football -- current season needs a paid plan.")
    ap.add_argument("--mock", action="store_true",
                    help="use simulated fixtures and prices; nothing fetched")
    ap.add_argument("--date", help="target Saturday, YYYY-MM-DD (default: next one)")
    ap.add_argument("--days", type=int, default=None, metavar="N",
                    help="ignore the 3pm-Saturday rule and cover every fixture "
                         "in the next N days -- Sunday afternoon, Tuesday night, "
                         "the lot. Whatever the fixtures file currently holds.")
    ap.add_argument("--refresh", action="store_true",
                    help="re-download historical results")
    ap.add_argument("--half-life", type=int, default=None, metavar="DAYS",
                    help=f"how fast old results stop counting (default "
                         f"{config.HALF_LIFE_DAYS}). Lower = more weight on "
                         f"recent form, but noisier.")
    ap.add_argument("--out", default="shortlist.html")
    ap.add_argument("--open", action="store_true", help="open the result in a browser")
    args = ap.parse_args()

    if args.command == "verify":
        odds_mod.ApiFootball().verify_leagues()
        return 0

    if args.command == "doctor":
        return doctor()

    if args.days:
        target = (dt.date.fromisoformat(args.date) if args.date
                  else dt.datetime.now(config.UK).date())
        until = target + dt.timedelta(days=args.days - 1)
    else:
        target = (dt.date.fromisoformat(args.date) if args.date else next_saturday())
        until = None
        if target.weekday() != config.KICKOFF_WEEKDAY:
            print(f"warning: {target} is a {target.strftime('%A')}, not a Saturday.\n")

    # ---------------------------------------------------------- 1. history
    if until:
        print(f"Building shortlist for {target:%a %d %b} to {until:%a %d %b} "
              f"(all kick-off times)\n")
    else:
        print(f"Building shortlist for Saturday {target:%d %b %Y}\n")
    if args.mock:
        print("MOCK MODE — generating synthetic history, nothing is fetched.")
        matches = demo.synthetic_history()
    else:
        print("Loading historical results...")
        matches = data.load_results(refresh=args.refresh)
    print(f"  {len(matches):,} matches, {matches['date'].min():%b %Y} "
          f"to {matches['date'].max():%b %Y}\n")

    # ------------------------------------------------------------ 2. model
    print("Fitting Dixon-Coles model per division...")
    if args.half_life:
        config.HALF_LIFE_DAYS = args.half_life
        print(f"  (half-life set to {args.half_life} days)")
    models = model.fit_all(matches)
    if not models:
        print("\nNo models could be fitted. Check the historical data.")
        return 1
    print()

    # --------------------------------------------------------- 3. fixtures
    api = None
    if args.mock:
        fixtures = odds_mod.mock_fixtures()
        print(f"  {len(fixtures)} simulated fixtures "
              f"(prices are random — EV and edge figures are noise)")

    elif args.source == "oddsapi":
        client = oddsapi.OddsApi()
        print("Fetching fixtures + match odds from The Odds API "
              f"({len(oddsapi.SPORT_KEYS)} credits)...")
        fixtures = client.fixtures_with_h2h()
        print(f"  {len(fixtures)} upcoming fixtures across the five leagues")

    elif args.source == "free":
        print("Fetching fixtures.csv from football-data.co.uk (no API key needed)...")
        fixtures = fixtures_csv.load_fixtures(target, until=until)
        print(f"  {len(fixtures)} fixtures across the five leagues")
        if not fixtures:
            dates = fixtures_csv.available_dates()
            print(f"\n  Nothing listed for {target}. The file currently covers: "
                  f"{', '.join(str(d) for d in dates[:8])}")
            print("  It's refreshed Friday afternoons for the weekend -- try again then.")
            return 0
        print("  Note: this source has no BTTS market, so win legs only.")
        print("  Run with --source api (and a free key) to add BTTS.\n")

    else:
        api = odds_mod.ApiFootball()
        print(f"Fetching fixtures from API-Football"
              f"{f' ({target} to {until})' if until else f' for {target}'}...")
        fixtures = api.fixtures_for_date(target, season_for(target), until=until)
        print(f"  {len(fixtures)} fixtures across the five leagues")

    if args.source == "oddsapi":
        # The Odds API returns everything upcoming, so the slot filter also
        # does the date filtering here.
        fixtures = [f for f in fixtures
                    if (until is None and f.kickoff_uk.date() == target)
                    or (until is not None and target <= f.kickoff_uk.date() <= until)]

    if until:
        # Whole-window mode: every kick-off counts, not just 3pm Saturday.
        three_pm = fixtures
        days = sorted({f.kickoff_uk.date() for f in fixtures})
        print(f"  {len(fixtures)} fixtures across {len(days)} day(s): "
              f"{', '.join(f'{d:%a %d %b}' for d in days)}\n")
    else:
        three_pm = [f for f in fixtures if f.is_3pm_saturday()]
        print(f"  {len(three_pm)} kick off at 3pm UK\n")

    if not three_pm:
        print("Nothing found. The fixtures file is refreshed Friday afternoons for "
              "the weekend\nand Tuesday afternoons for midweek games.")
        return 0

    if args.source == "oddsapi":
        # Stage two: one credit per surviving fixture, never per fixture in
        # the whole file. This is what keeps a run inside the free tier.
        print(f"\nFetching BTTS for the {len(three_pm)} shortlisted fixtures "
              f"({len(three_pm)} credits)...")
        client.add_btts(three_pm)
        print(f"  {client.credits_used} credits used this month"
              + (f", {client.credits_left} left" if client.credits_left is not None else ""))
        if client.credits_left is not None and client.credits_left < 100:
            print("  ! Running low. Reduce how often the job runs.")
        print()

    if api is not None:
        budget = len(three_pm) + len(config.LEAGUES)
        print(f"Fetching odds ({budget} requests of your {config.REQUESTS_PER_DAY}/day)...")
        if budget > config.REQUESTS_PER_DAY:
            print(f"  ! That exceeds the free daily allowance. Narrow the window "
                  f"with a smaller --days, or upgrade the plan.")
        api.enrich_with_odds(three_pm)
        print(f"  {api.requests_used} requests used\n")

    # ------------------------------------------------------------ 4. names
    resolved, unmatched = names.resolve_fixtures(three_pm, models)
    if unmatched:
        print("Could not match these to the historical data (add them to "
              "accatool/names.py ALIASES):")
        for u in unmatched:
            print(f"  ! {u}")
        print()

    # ------------------------------------------------------------- 5. rank
    legs, rejected = rank.build_legs(resolved, models)
    print(f"{len(legs)} legs clear all four rules "
          f"(3pm Saturday, right league, win/BTTS, odds >= {config.MIN_ODDS})")

    if not legs:
        print("\nNothing qualifies. Loosen MIN_ODDS in config.py or check the odds feed.")
        return 0

    safest, value, both = rank.shortlists(legs)
    sweet = rank.sweet_spot(legs)
    sweet_summary = rank.acca_summary(sweet[:6])
    held = rank.held_back(legs)
    if held:
        teams = sorted({t.strip() for l in held for t in l.thin.split(",") if t.strip()})
        print(f"  {len(held)} leg(s) held back -- model has too little data on: "
              f"{', '.join(teams[:8])}{' ...' if len(teams) > 8 else ''}")
    print(f"  {len(both)} leg(s) appear in both columns\n")

    print(f"SWEET SPOT  (>= {config.SWEET_SPOT_MIN_PROB*100:.0f}% likely "
          f"and >= {config.SWEET_SPOT_MIN_EDGE*100:.0f}pt edge)")
    if sweet:
        for l in sweet:
            print(f"  {l.prob*100:5.1f}%  {l.odds:5.2f}  edge {l.edge*100:+5.1f}pt  "
                  f"{l.label}  ({l.league})")
        n = min(6, len(sweet))
        print(f"  -> top {n} as a {n}-fold: {sweet_summary['odds']:.2f} at "
              f"{sweet_summary['prob']*100:.1f}% -- £10 returns "
              f"£{sweet_summary['returns_on_10']:,.2f}")
    else:
        print("  nothing clears both bars this week -- that's a real answer, not a gap")

    print("\nSAFEST")
    for l in safest[:6]:
        print(f"  {l.prob*100:5.1f}%  {l.odds:5.2f}  {l.label}  ({l.league})")
    print("\nVALUE")
    for l in value[:6]:
        print(f"  {l.ev*100:+5.1f}%  {l.odds:5.2f}  {l.label}  ({l.league})")

    top6 = rank.acca_summary(safest[:6])
    print(f"\nTop 6 safest as a six-fold: {top6['odds']:.2f} at "
          f"{top6['prob']*100:.1f}% -- £10 returns £{top6['returns_on_10']:.2f}")

    # ----------------------------------------------------------- 6. report
    meta = {
        "date": (f"{target:%a %d %b} – {until:%a %d %b}" if until
                 else target.strftime("%d %B %Y")),
        "window": bool(until),
        "n_fixtures": len(resolved),
        "n_matches": len(matches),
        "mode": ("mock data" if args.mock else
                 "football-data.co.uk (win markets only)" if args.source == "free"
                 else "The Odds API (win + BTTS)" if args.source == "oddsapi"
                 else "API-Football (win + BTTS)"),
    }
    html_out = report.render(safest, value, both, legs, meta,
                             sweet=sweet, sweet_summary=sweet_summary, held=held)

    out_path = pathlib.Path(args.out).resolve()
    out_path.write_text(html_out, encoding="utf-8")
    print(f"\nWrote {out_path}")

    if args.open:
        # as_uri() gives a valid absolute file:// URL. Building one by hand
        # from a relative path yields file://shortlist.html, which browsers
        # read as a hostname and reject.
        webbrowser.open(out_path.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
