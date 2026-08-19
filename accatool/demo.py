"""Fully offline demo data.

`--mock` needs to work with no network at all, so that unzipping the tool and
running one command tells you whether your Python install is sound —
separately from whether football-data.co.uk is reachable. Two failures that
look identical from the outside are worth being able to tell apart.

Results are generated from known team strengths, so the model has something
real to fit and the output page is structurally identical to a live run. The
prices are random, so the EV and edge numbers are noise. Don't read them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .odds import mock_fixtures


def synthetic_history(seed: int = 42, seasons: int = 2) -> pd.DataFrame:
    """Two seasons of results for the teams in mock_fixtures()."""
    rng = np.random.default_rng(seed)

    by_div: dict[str, set] = {}
    for f in mock_fixtures():
        by_div.setdefault(f.div, set()).update([f.home, f.away])

    # Each division gets its own scoring environment, as in real life.
    base_rate = {"E0": 0.10, "E1": 0.02, "E2": -0.02, "E3": -0.08, "SC0": 0.0}

    rows = []
    for div, team_set in by_div.items():
        teams = sorted(team_set)
        base = base_rate.get(div, 0.0)

        attack = rng.normal(base, 0.30, len(teams))
        attack -= attack.mean() - base
        defence = rng.normal(0, 0.25, len(teams))

        # Leave one side per division with almost no history, so a mock run
        # shows what a newly-promoted team looks like on the page.
        newcomer = teams[-1]

        date = pd.Timestamp("2024-08-01")
        for _ in range(seasons):
            for i, home in enumerate(teams):
                for j, away in enumerate(teams):
                    if i == j:
                        continue
                    if (home == newcomer or away == newcomer) and rng.random() < 0.88:
                        continue
                    lam = np.exp(attack[i] + defence[j] + 0.26)
                    mu = np.exp(attack[j] + defence[i])
                    rows.append({
                        "date": date, "div": div, "home": home, "away": away,
                        "hg": int(rng.poisson(lam)), "ag": int(rng.poisson(mu)),
                    })
                    date += pd.Timedelta(hours=8)

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
