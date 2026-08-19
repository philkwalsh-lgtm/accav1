"""Historical results from football-data.co.uk.

Free CSVs, no API key, one file per division per season. We only need four
columns (date, home, away, home goals, away goals) but the files also carry
closing bookmaker odds, which the backtest uses.
"""

from __future__ import annotations

import io
import pathlib

import pandas as pd
import requests

from . import config

CACHE = pathlib.Path(__file__).resolve().parent.parent / "data"


def _fetch_csv(season: str, div: str, refresh: bool = False,
               verbose: bool = True) -> pd.DataFrame | None:
    """Download one division-season, caching to disk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{season}_{div}.csv"

    if path.exists() and not refresh:
        raw = path.read_bytes()
    else:
        url = config.FOOTBALL_DATA_URL.format(season=season, div=div)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            if verbose:
                # Trim the stack of nested urllib3 wrappers down to the cause.
                reason = str(exc).split("(Caused by")[-1].strip(" )")
                print(f"  ! {div} {season}: {reason or exc}")
            return None
        raw = resp.content
        path.write_bytes(raw)

    # These files have a trailing comma problem in some seasons and are
    # latin-1 rather than utf-8. Both are long-standing quirks of the source.
    df = pd.read_csv(io.BytesIO(raw), encoding="latin-1", on_bad_lines="skip")
    df["Div"] = div
    df["Season"] = season
    return df


def load_results(seasons=None, divisions=None, refresh: bool = False,
                 verbose: bool = True) -> pd.DataFrame:
    """Every completed match across the five leagues, tidied.

    Returns columns: date, div, home, away, hg, ag  (+ odds if present).
    """
    seasons = seasons or config.SEASONS
    divisions = divisions or list(config.LEAGUES)

    frames = []
    for div in divisions:
        for season in seasons:
            df = _fetch_csv(season, div, refresh=refresh, verbose=verbose)
            if df is not None and len(df):
                frames.append(df)

    if not frames:
        raise RuntimeError(
            "No historical data could be loaded. Check your network connection "
            "-- football-data.co.uk needs to be reachable."
        )

    raw = pd.concat(frames, ignore_index=True)

    out = pd.DataFrame({
        "date": pd.to_datetime(raw["Date"], dayfirst=True, format="mixed", errors="coerce"),
        "div": raw["Div"],
        "home": raw["HomeTeam"].astype("string").str.strip(),
        "away": raw["AwayTeam"].astype("string").str.strip(),
        "hg": pd.to_numeric(raw["FTHG"], errors="coerce"),
        "ag": pd.to_numeric(raw["FTAG"], errors="coerce"),
    })

    # Closing odds, where available -- only used by the backtest.
    for src, dst in (("B365H", "odds_h"), ("B365D", "odds_d"), ("B365A", "odds_a")):
        if src in raw.columns:
            out[dst] = pd.to_numeric(raw[src], errors="coerce")

    out = out.dropna(subset=["date", "home", "away", "hg", "ag"])
    out["hg"] = out["hg"].astype(int)
    out["ag"] = out["ag"].astype(int)

    return out.sort_values("date").reset_index(drop=True)
