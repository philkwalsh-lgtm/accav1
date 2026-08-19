"""Dixon-Coles goal model.

Each team gets an attack and a defence rating; there is one global home
advantage term and one low-score correction term (rho). Expected goals are

    lambda_home = exp(attack_home + defence_away + home_adv)
    lambda_away = exp(attack_away + defence_home)

and from those two numbers a full scoreline matrix falls out -- which is what
lets one model price both the match result and BTTS without extra work.

Fitted separately per division, because League Two is a different scoring
environment from the Premier League and a shared model misprices both.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from . import config


def _tau(hg, ag, lam, mu, rho):
    """Dixon-Coles low-score correction.

    Raw Poisson treats home and away goals as independent, which underrates
    0-0 and 1-1 and overrates 1-0 and 0-1. Those four scorelines are exactly
    the ones that decide BTTS in tight games, so the correction matters here
    more than it would for a pure match-result model.
    """
    hg, ag = np.asarray(hg), np.asarray(ag)
    out = np.ones_like(lam, dtype=float)
    out = np.where((hg == 0) & (ag == 0), 1.0 - lam * mu * rho, out)
    out = np.where((hg == 0) & (ag == 1), 1.0 + lam * rho, out)
    out = np.where((hg == 1) & (ag == 0), 1.0 + mu * rho, out)
    out = np.where((hg == 1) & (ag == 1), 1.0 - rho, out)
    return out


@dataclass
class DivisionModel:
    """A fitted model for one division."""

    div: str
    teams: list[str]
    attack: dict[str, float]
    defence: dict[str, float]
    home_adv: float
    rho: float
    n_matches: int = 0
    converged: bool = True
    # How much evidence each team's rating actually rests on, after time
    # decay. A promoted side, or one that has played twice this season, gets a
    # rating from almost nothing -- and the page should say so rather than
    # printing a confident percentage.
    evidence: dict[str, float] = field(default_factory=dict, repr=False)
    recent: dict[str, int] = field(default_factory=dict, repr=False)
    median_evidence: float = 0.0
    _idx: dict[str, int] = field(default_factory=dict, repr=False)

    def is_thin(self, team: str, ratio: float = 0.5) -> bool:
        """True when this team's rating rests on much less than its rivals'."""
        if not self.median_evidence:
            return False
        return self.evidence.get(team, 0.0) < ratio * self.median_evidence

    # ---------------------------------------------------------------- rates

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        if home not in self.attack or away not in self.attack:
            raise KeyError(f"unknown team: {home if home not in self.attack else away}")
        lam = np.exp(self.attack[home] + self.defence[away] + self.home_adv)
        mu = np.exp(self.attack[away] + self.defence[home])
        return float(lam), float(mu)

    # ------------------------------------------------------------ score grid

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        """P(home scores i, away scores j) for i,j in 0..MAX_GOALS."""
        lam, mu = self.expected_goals(home, away)
        n = config.MAX_GOALS + 1

        m = np.outer(poisson.pmf(np.arange(n), lam), poisson.pmf(np.arange(n), mu))

        # Apply the correction to the four affected cells.
        m[0, 0] *= 1.0 - lam * mu * self.rho
        m[0, 1] *= 1.0 + lam * self.rho
        m[1, 0] *= 1.0 + mu * self.rho
        m[1, 1] *= 1.0 - self.rho

        m = np.clip(m, 0.0, None)
        return m / m.sum()

    def probabilities(self, home: str, away: str) -> dict[str, float]:
        """Everything we price, from one matrix."""
        m = self.score_matrix(home, away)
        return {
            "HOME": float(np.tril(m, -1).sum()),   # home goals > away goals
            "DRAW": float(np.trace(m)),
            "AWAY": float(np.triu(m, 1).sum()),    # away goals > home goals
            "BTTS": float(m[1:, 1:].sum()),        # both scored at least one
            "xg_home": self.expected_goals(home, away)[0],
            "xg_away": self.expected_goals(home, away)[1],
        }


def fit_division(matches: pd.DataFrame, div: str, half_life_days: int | None = None,
                 as_of: pd.Timestamp | None = None) -> DivisionModel:
    """Maximum-likelihood fit for one division, with exponential time decay."""
    half_life_days = half_life_days or config.HALF_LIFE_DAYS

    df = matches[matches["div"] == div]
    if as_of is not None:
        df = df[df["date"] < as_of]
    df = df.dropna(subset=["home", "away", "hg", "ag"])

    if len(df) < 50:
        raise ValueError(f"{div}: only {len(df)} matches, need at least 50 to fit")

    teams = sorted(set(df["home"]) | set(df["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    hi = df["home"].map(idx).to_numpy()
    ai = df["away"].map(idx).to_numpy()
    hg = df["hg"].to_numpy()
    ag = df["ag"].to_numpy()

    # Recent matches count for more. Half-life expressed in days, converted
    # to the decay constant the likelihood actually uses.
    latest = as_of if as_of is not None else df["date"].max()
    age_days = (latest - df["date"]).dt.days.to_numpy().astype(float)
    weights = 0.5 ** (age_days / half_life_days)

    def neg_log_likelihood(params):
        attack = params[:n]
        defence = params[n:2 * n]
        home_adv, rho = params[2 * n], params[2 * n + 1]

        # Identifiability: attack ratings are only meaningful relative to each
        # other, so pin their mean at zero.
        attack = attack - attack.mean()

        lam = np.exp(attack[hi] + defence[ai] + home_adv)
        mu = np.exp(attack[ai] + defence[hi])

        lam = np.clip(lam, 1e-10, 25.0)
        mu = np.clip(mu, 1e-10, 25.0)

        log_p = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu)
        tau = _tau(hg, ag, lam, mu, rho)
        log_tau = np.log(np.clip(tau, 1e-10, None))

        return -np.sum(weights * (log_p + log_tau))

    x0 = np.concatenate([
        np.zeros(n),          # attack
        np.zeros(n),          # defence
        [0.25],               # home advantage: ~1.28x goals, a sane start
        [-0.05],              # rho: small and negative in practice
    ])
    bounds = [(-3, 3)] * n + [(-3, 3)] * n + [(-1, 1), (-0.2, 0.2)]

    res = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 500})

    attack = res.x[:n] - res.x[:n].mean()
    defence = res.x[n:2 * n]

    # Evidence per team: the decayed weight of every match they appear in.
    evidence = {t: 0.0 for t in teams}
    recent = {t: 0 for t in teams}
    for h, a, w, age in zip(hi, ai, weights, age_days):
        evidence[teams[h]] += w
        evidence[teams[a]] += w
        if age <= 120:
            recent[teams[h]] += 1
            recent[teams[a]] += 1
    median_evidence = float(np.median(list(evidence.values()))) if evidence else 0.0

    return DivisionModel(
        div=div,
        teams=teams,
        attack=dict(zip(teams, attack)),
        defence=dict(zip(teams, defence)),
        home_adv=float(res.x[2 * n]),
        rho=float(res.x[2 * n + 1]),
        n_matches=len(df),
        converged=bool(res.success),
        evidence=evidence,
        recent=recent,
        median_evidence=median_evidence,
        _idx=idx,
    )


def fit_all(matches: pd.DataFrame, as_of: pd.Timestamp | None = None,
            verbose: bool = True) -> dict[str, DivisionModel]:
    """Fit every division we have data for."""
    models = {}
    for div in config.LEAGUES:
        try:
            m = fit_division(matches, div, as_of=as_of)
        except ValueError as exc:
            if verbose:
                print(f"  ! skipping {div}: {exc}")
            continue
        models[div] = m
        if verbose:
            flag = "" if m.converged else "  (did not fully converge)"
            thin = [t for t in m.teams if m.is_thin(t)]
            print(f"  {div:4s} {config.LEAGUES[div]['name']:22s} "
                  f"{m.n_matches:5d} matches  home_adv={np.exp(m.home_adv):.3f}x  "
                  f"rho={m.rho:+.3f}{flag}")
            if thin:
                print(f"       thin evidence ({len(thin)}): {', '.join(sorted(thin)[:6])}"
                      f"{' ...' if len(thin) > 6 else ''}")
    return models
