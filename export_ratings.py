#!/usr/bin/env python3
"""Export fitted team ratings for the Google Sheet.

The split that makes the Sheets version work:

  Hard maths, done rarely   -> here, on your machine (scipy, ~30 seconds)
  Easy maths, done weekly   -> in Apps Script, on Google's servers, Saturday 9am

Fitting the model is a 50-parameter maximum-likelihood optimisation. Scoring a
fixture once you HAVE the ratings is just exp() and a 11x11 grid -- trivial
JavaScript. So we fit here, publish the ratings, and let the Sheet do the
weekly work with no laptop involved.

Ratings go stale slowly. With a 180-day half-life, one week of results barely
moves them -- refitting monthly is plenty, and at season start plus every few
weeks is fine.

    python export_ratings.py              # writes ratings.csv
    python export_ratings.py --tsv        # tab-separated, for pasting
    python export_ratings.py --clipboard  # straight to clipboard (macOS)
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from accatool import config, data, model


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ratings.csv")
    ap.add_argument("--tsv", action="store_true", help="tab-separated for pasting")
    ap.add_argument("--clipboard", action="store_true", help="copy to clipboard (macOS)")
    ap.add_argument("--refresh", action="store_true", help="re-download results first")
    args = ap.parse_args()

    print("Loading historical results...")
    matches = data.load_results(refresh=args.refresh)
    print(f"  {len(matches):,} matches to {matches['date'].max():%d %b %Y}\n")

    print("Fitting models...")
    models = model.fit_all(matches)
    if not models:
        print("No models fitted.")
        return 1

    sep = "\t" if args.tsv else ","
    lines = [sep.join(["div", "team", "attack", "defence", "home_adv", "rho"])]

    for div, m in models.items():
        for team in m.teams:
            lines.append(sep.join([
                div,
                team,
                f"{m.attack[team]:.6f}",
                f"{m.defence[team]:.6f}",
                f"{m.home_adv:.6f}",
                f"{m.rho:.6f}",
            ]))

    text = "\n".join(lines)
    n_teams = sum(len(m.teams) for m in models.values())

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"\nWrote {args.out}: {n_teams} teams across {len(models)} divisions")

    if args.clipboard:
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            print("Copied to clipboard -- paste into the Sheet's 'ratings' tab at A1.")
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("Could not copy to clipboard (pbcopy is macOS only).")

    print("\nNext: paste this into the 'ratings' tab of your Google Sheet, "
          "starting at cell A1 (including the header row).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
