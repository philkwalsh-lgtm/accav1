"""Match API-Football team names to football-data.co.uk team names.

These two sources disagree constantly -- "Manchester United" vs "Man United",
"Nottingham Forest" vs "Nott'm Forest" -- and an unmatched team means a
fixture silently drops out of the shortlist. Explicit aliases first, fuzzy
matching as a fallback, and anything still unmatched is reported loudly
rather than skipped quietly.
"""

from __future__ import annotations

import difflib
import re

# API-Football name -> football-data.co.uk name.
# Extend this as you spot misses; the tool prints anything it couldn't match.
ALIASES = {
    # Premier League
    "manchester united": "Man United",
    "manchester city": "Man City",
    "newcastle united": "Newcastle",
    "nottingham forest": "Nott'm Forest",
    "tottenham": "Tottenham",
    "wolverhampton wanderers": "Wolves",
    "brighton & hove albion": "Brighton",
    "west ham united": "West Ham",
    "leeds united": "Leeds",
    "leicester city": "Leicester",
    "sheffield united": "Sheffield United",
    "afc bournemouth": "Bournemouth",
    # Championship / League One / League Two
    "west bromwich albion": "West Brom",
    "queens park rangers": "QPR",
    "sheffield wednesday": "Sheffield Weds",
    "peterborough united": "Peterboro",
    "milton keynes dons": "Milton Keynes Dons",
    "bolton wanderers": "Bolton",
    "wigan athletic": "Wigan",
    "blackburn rovers": "Blackburn",
    "cardiff city": "Cardiff",
    "swansea city": "Swansea",
    "stoke city": "Stoke",
    "hull city": "Hull",
    "birmingham city": "Birmingham",
    "coventry city": "Coventry",
    "preston north end": "Preston",
    "bristol city": "Bristol City",
    "bristol rovers": "Bristol Rvs",
    "derby county": "Derby",
    "ipswich town": "Ipswich",
    "norwich city": "Norwich",
    "oxford united": "Oxford",
    "plymouth argyle": "Plymouth",
    "portsmouth": "Portsmouth",
    "charlton athletic": "Charlton",
    "lincoln city": "Lincoln",
    "shrewsbury town": "Shrewsbury",
    "wycombe wanderers": "Wycombe",
    "burton albion": "Burton",
    "exeter city": "Exeter",
    "notts county": "Notts County",
    "grimsby town": "Grimsby",
    "colchester united": "Colchester",
    "salford city": "Salford",
    "swindon town": "Swindon",
    "bradford city": "Bradford",
    "walsall": "Walsall",
    "crewe alexandra": "Crewe",
    "barrow": "Barrow",
    "chesterfield": "Chesterfield",
    "accrington stanley": "Accrington",
    "milton keynes": "Milton Keynes Dons",
    # Scotland
    "celtic": "Celtic",
    "rangers": "Rangers",
    "heart of midlothian": "Hearts",
    "hibernian": "Hibernian",
    "st mirren": "St Mirren",
    "st johnstone": "St Johnstone",
    "dundee united": "Dundee United",
    "ross county": "Ross County",
    "kilmarnock": "Kilmarnock",
    "motherwell": "Motherwell",
    "aberdeen": "Aberdeen",
    "livingston": "Livingston",
}

_NOISE = re.compile(r"\b(fc|afc|cf|city|town|united|wanderers|athletic|rovers|county)\b")


def _normalise(name: str) -> str:
    s = name.lower().strip()
    s = s.replace("&", "and").replace(".", "").replace("'", "")
    return re.sub(r"\s+", " ", s)


def resolve(api_name: str, known_teams: list[str], cutoff: float = 0.72) -> str | None:
    """Best football-data.co.uk name for an API-Football team name."""
    norm = _normalise(api_name)

    # 1. Explicit alias.
    if norm in ALIASES and ALIASES[norm] in known_teams:
        return ALIASES[norm]

    # 2. Exact match, case-insensitive.
    lookup = {_normalise(t): t for t in known_teams}
    if norm in lookup:
        return lookup[norm]

    # 3. Fuzzy match on the full name.
    hits = difflib.get_close_matches(norm, list(lookup), n=1, cutoff=cutoff)
    if hits:
        return lookup[hits[0]]

    # 4. Fuzzy match with common suffixes stripped from both sides.
    stripped = {_NOISE.sub("", k).strip(): v for k, v in lookup.items()}
    hits = difflib.get_close_matches(_NOISE.sub("", norm).strip(),
                                     list(stripped), n=1, cutoff=cutoff)
    if hits:
        return stripped[hits[0]]

    return None


def resolve_fixtures(fixtures, models) -> tuple[list, list[str]]:
    """Attach model-side names to fixtures. Returns (resolved, unmatched)."""
    unmatched = []
    resolved = []
    for f in fixtures:
        model = models.get(f.div)
        if model is None:
            unmatched.append(f"{f.div}: no model for this division")
            continue
        h = resolve(f.home, model.teams)
        a = resolve(f.away, model.teams)
        if h is None or a is None:
            missing = f.home if h is None else f.away
            unmatched.append(f"{f.div}: '{missing}' (in {f.home} v {f.away})")
            continue
        f.model_home, f.model_away = h, a
        resolved.append(f)
    return resolved, unmatched
