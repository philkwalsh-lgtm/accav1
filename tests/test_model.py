"""Verify the model recovers known parameters and produces calibrated probabilities.

Because we generate the matches ourselves, we know the true answer, which is
the only way to check the fitting code is right rather than merely plausible.
"""

import sys
import pathlib

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from accatool import model as M
from accatool import config


def simulate_league(n_teams=20, n_seasons=3, seed=0, home_adv=0.26, rho=-0.05):
    """Generate seasons of results from known team strengths."""
    rng = np.random.default_rng(seed)
    teams = [f"Team{i:02d}" for i in range(n_teams)]

    true_attack = rng.normal(0, 0.35, n_teams)
    true_attack -= true_attack.mean()
    true_defence = rng.normal(0, 0.30, n_teams)

    rows = []
    date = pd.Timestamp("2023-08-01")
    for _ in range(n_seasons):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lam = np.exp(true_attack[i] + true_defence[j] + home_adv)
                mu = np.exp(true_attack[j] + true_defence[i])
                hg = rng.poisson(lam)
                ag = rng.poisson(mu)
                rows.append({"date": date, "div": "TEST", "home": teams[i],
                             "away": teams[j], "hg": hg, "ag": ag})
                date += pd.Timedelta(hours=6)

    return pd.DataFrame(rows), dict(zip(teams, true_attack)), dict(zip(teams, true_defence)), home_adv


def test_parameter_recovery():
    matches, true_att, true_def, true_ha = simulate_league()
    # No decay: we want to use every simulated match, since the true strengths
    # were constant across the simulated seasons.
    m = M.fit_division(matches, "TEST", half_life_days=100_000)

    att_fit = np.array([m.attack[t] for t in m.teams])
    att_true = np.array([true_att[t] for t in m.teams])
    def_fit = np.array([m.defence[t] for t in m.teams])
    def_true = np.array([true_def[t] for t in m.teams])

    # Defence ratings are only identified up to a constant offset that trades
    # off against home advantage, so compare after centring.
    def_fit = def_fit - def_fit.mean()
    def_true = def_true - def_true.mean()

    att_rmse = np.sqrt(((att_fit - att_true) ** 2).mean())
    def_rmse = np.sqrt(((def_fit - def_true) ** 2).mean())
    att_corr = np.corrcoef(att_fit, att_true)[0, 1]
    def_corr = np.corrcoef(def_fit, def_true)[0, 1]

    print(f"  attack  : rmse {att_rmse:.3f}  corr with truth {att_corr:.3f}")
    print(f"  defence : rmse {def_rmse:.3f}  corr with truth {def_corr:.3f}")
    print(f"  home_adv: fitted {m.home_adv:.3f} vs true {true_ha:.3f}")

    # Ratings are estimated from a finite number of matches, so exact recovery
    # is impossible -- what matters is that the estimates are unbiased and
    # rank teams correctly.
    assert att_rmse < 0.12, f"attack ratings not recovered (rmse {att_rmse:.3f})"
    assert def_rmse < 0.12, f"defence ratings not recovered (rmse {def_rmse:.3f})"
    assert att_corr > 0.90, f"attack ratings poorly correlated ({att_corr:.3f})"
    assert def_corr > 0.90, f"defence ratings poorly correlated ({def_corr:.3f})"
    assert abs(m.home_adv - true_ha) < 0.08, "home advantage not recovered"
    print("  PASS parameter recovery")


def test_probabilities_sum_to_one():
    matches, *_ = simulate_league(n_teams=12, n_seasons=2, seed=3)
    m = M.fit_division(matches, "TEST", half_life_days=100_000)

    worst = 0.0
    for h in m.teams[:5]:
        for a in m.teams[:5]:
            if h == a:
                continue
            p = m.probabilities(h, a)
            total = p["HOME"] + p["DRAW"] + p["AWAY"]
            worst = max(worst, abs(total - 1.0))
            assert 0.0 < p["BTTS"] < 1.0
    print(f"  max deviation of H+D+A from 1.0: {worst:.2e}")
    assert worst < 1e-9
    print("  PASS probabilities are coherent")


def test_calibration():
    """The real test: over many simulated matches, do stated probabilities
    match observed frequencies? A model that says 60% should be right 60%
    of the time."""
    matches, *_ = simulate_league(n_teams=20, n_seasons=4, seed=7)

    train = matches.iloc[:len(matches) * 3 // 4]
    test = matches.iloc[len(matches) * 3 // 4:]

    m = M.fit_division(train, "TEST", half_life_days=100_000)

    preds, outcomes_home, outcomes_btts, preds_btts = [], [], [], []
    for _, r in test.iterrows():
        p = m.probabilities(r["home"], r["away"])
        preds.append(p["HOME"])
        preds_btts.append(p["BTTS"])
        outcomes_home.append(1 if r["hg"] > r["ag"] else 0)
        outcomes_btts.append(1 if (r["hg"] > 0 and r["ag"] > 0) else 0)

    preds = np.array(preds); outcomes_home = np.array(outcomes_home)
    preds_btts = np.array(preds_btts); outcomes_btts = np.array(outcomes_btts)

    print(f"  home win : predicted {preds.mean():.3f}  actual {outcomes_home.mean():.3f}")
    print(f"  btts     : predicted {preds_btts.mean():.3f}  actual {outcomes_btts.mean():.3f}")

    # Calibration by decile for the home-win market.
    print("  home-win calibration by predicted band:")
    for lo in np.arange(0.1, 0.8, 0.1):
        mask = (preds >= lo) & (preds < lo + 0.1)
        if mask.sum() > 30:
            print(f"    {lo:.1f}-{lo+0.1:.1f}: predicted {preds[mask].mean():.3f} "
                  f"actual {outcomes_home[mask].mean():.3f}  (n={mask.sum()})")

    assert abs(preds.mean() - outcomes_home.mean()) < 0.03, "home win miscalibrated"
    assert abs(preds_btts.mean() - outcomes_btts.mean()) < 0.03, "btts miscalibrated"
    print("  PASS calibration")


def test_btts_matches_matrix():
    """BTTS read off the matrix must equal 1 - P(either team blanks)."""
    matches, *_ = simulate_league(n_teams=10, n_seasons=2, seed=11)
    m = M.fit_division(matches, "TEST", half_life_days=100_000)

    h, a = m.teams[0], m.teams[1]
    mat = m.score_matrix(h, a)
    direct = mat[1:, 1:].sum()
    complement = 1.0 - (mat[0, :].sum() + mat[:, 0].sum() - mat[0, 0])
    print(f"  btts direct {direct:.6f} vs complement {complement:.6f}")
    assert abs(direct - complement) < 1e-9
    print("  PASS btts consistency")


def test_thin_evidence_flag():
    """A team the model barely knows must be flagged, not quietly rated.

    This is the check on the biggest honest weakness of the whole tool: almost
    everything it knows is historical, so a side promoted this summer or one
    that has played twice gets a confident-looking percentage built on nothing.
    """
    rng = np.random.default_rng(5)
    teams = [f"T{i:02d}" for i in range(12)]
    rows, date = [], pd.Timestamp("2025-08-01")

    for _ in range(2):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j:
                    continue
                rows.append({"date": date, "div": "X", "home": h, "away": a,
                             "hg": int(rng.poisson(1.4)), "ag": int(rng.poisson(1.1))})
                date += pd.Timedelta(hours=8)

    for opp in teams[:2]:                      # newcomer plays only twice
        rows.append({"date": date, "div": "X", "home": "NewlyPromoted", "away": opp,
                     "hg": int(rng.poisson(1.2)), "ag": int(rng.poisson(1.2))})
        date += pd.Timedelta(days=3)

    m = M.fit_division(pd.DataFrame(rows), "X")
    print(f"  median evidence {m.median_evidence:.1f}, "
          f"newcomer {m.evidence['NewlyPromoted']:.1f}, "
          f"settled side {m.evidence['T00']:.1f}")

    flagged = [t for t in m.teams if m.is_thin(t)]
    assert flagged == ["NewlyPromoted"], f"expected only the newcomer, got {flagged}"
    assert not m.is_thin("T00"), "a settled side must not be flagged"
    print("  PASS thin-evidence flag")


if __name__ == "__main__":
    print("test_parameter_recovery");      test_parameter_recovery()
    print("test_probabilities_sum_to_one"); test_probabilities_sum_to_one()
    print("test_btts_matches_matrix");     test_btts_matches_matrix()
    print("test_calibration");             test_calibration()
    print("test_thin_evidence_flag");       test_thin_evidence_flag()
    print("\nAll model tests passed.")
