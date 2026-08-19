"""Cross-check the Apps Script implementation against the Python one.

There are now two implementations of the same tool — Python for local runs and
backtesting, JavaScript for the hands-off Saturday job in Google Sheets. Two
implementations of the same maths is exactly the situation where they quietly
drift apart, so this runs both over identical inputs and asserts they agree.

Needs node on PATH. Skips cleanly if it isn't there.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import datetime as dt

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from accatool import model, rank, fixtures_csv          # noqa: E402
from test_fixtures_csv import STUB                       # noqa: E402

CODE_GS = ROOT / "sheets" / "Code.gs"


def _node():
    exe = shutil.which("node")
    if not exe:
        print("  SKIP: node not found on PATH")
    return exe


# ---------------------------------------------------------------- the model

MODEL_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const CFG = { MAX_GOALS: 10 };
eval(src.match(/function poissonPmf[\s\S]*?\n}\n/)[0]);
eval(src.match(/function scoreMatrix[\s\S]*?\n}\n\n/)[0]);
eval(src.match(/function probabilities[\s\S]*?\n}\n\n/)[0]);
eval(src.match(/function devig[\s\S]*?\n}\n/)[0]);

const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify(cases.map(c => {
  const R = { attack: {H: c.ah, A: c.aa}, defence: {H: c.dh, A: c.da},
              homeAdv: c.ha, rho: c.rho };
  return probabilities(R, 'H', 'A');
})));
"""


def test_model_agreement(n=200):
    node = _node()
    if not node:
        return

    rng = np.random.default_rng(1)
    cases = [{
        "ah": float(rng.normal(0, .4)), "aa": float(rng.normal(0, .4)),
        "dh": float(rng.normal(0, .35)), "da": float(rng.normal(0, .35)),
        "ha": float(rng.uniform(.1, .4)), "rho": float(rng.uniform(-.15, .15)),
    } for _ in range(n)]

    tmp_cases = ROOT / ".cases.json"
    tmp_js = ROOT / ".harness.js"
    tmp_cases.write_text(json.dumps(cases))
    tmp_js.write_text(MODEL_HARNESS)

    try:
        out = subprocess.run([node, str(tmp_js), str(CODE_GS), str(tmp_cases)],
                             capture_output=True, text=True, check=True)
        js = json.loads(out.stdout)
    finally:
        tmp_cases.unlink(missing_ok=True)
        tmp_js.unlink(missing_ok=True)

    worst = {}
    for c, j in zip(cases, js):
        m = model.DivisionModel(
            div="X", teams=["H", "A"],
            attack={"H": c["ah"], "A": c["aa"]},
            defence={"H": c["dh"], "A": c["da"]},
            home_adv=c["ha"], rho=c["rho"])
        p = m.probabilities("H", "A")
        for pk, jk in (("HOME", "HOME"), ("DRAW", "DRAW"), ("AWAY", "AWAY"),
                       ("BTTS", "BTTS"), ("xg_home", "xgH"), ("xg_away", "xgA")):
            worst[pk] = max(worst.get(pk, 0.0), abs(p[pk] - j[jk]))

    print(f"  {n} random rating sets:")
    for k, v in worst.items():
        print(f"    {k:9s} max difference {v:.2e}")

    assert max(worst.values()) < 1e-9, "Python and JavaScript models disagree"
    print("  PASS model agreement (machine precision)")


# -------------------------------------------------------------- the parser

PARSER_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const STUB = fs.readFileSync(process.argv[3], 'utf8');

global.UrlFetchApp = { fetch: () => ({ getResponseCode: () => 200,
                                       getContentText: () => STUB }) };
global.Utilities = {
  parseCsv: (t) => t.trim().split('\n').map(l => l.split(',')),
  formatDate: (d, tz, fmt) => {
    const p = n => String(n).padStart(2, '0');
    if (fmt === 'dd/MM/yyyy')
      return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
    throw new Error('unexpected format ' + fmt);
  },
};
const CFG = {
  SOURCE: 'free', FIXTURES_CSV: 'x', PRICE_SOURCE: 'Max', FAIR_SOURCE: 'Avg',
  TIMEZONE: 'Europe/London', KICKOFF_HOUR: 15, KICKOFF_MINUTE: 0,
  LEAGUES: { E0: {name: 'Premier League'}, E1: {name: 'Championship'},
             E2: {name: 'League One'}, E3: {name: 'League Two'},
             SC0: {name: 'Scottish Premiership'} },
};
eval(src.match(/function fetchFreeFixtures[\s\S]*?\n}\n/)[0]);

const d = new Date(Number(process.argv[4]), Number(process.argv[5]) - 1,
                   Number(process.argv[6]));
console.log(JSON.stringify(fetchFreeFixtures(d)));
"""


def test_parser_agreement():
    node = _node()
    if not node:
        return

    import io
    import pandas as pd
    fixtures_csv.fetch = lambda url=None: pd.read_csv(io.StringIO(STUB))

    target = dt.date(2026, 8, 22)
    py = fixtures_csv.load_fixtures(target)

    tmp_stub = ROOT / ".stub.csv"
    tmp_js = ROOT / ".parser.js"
    tmp_stub.write_text(STUB)
    tmp_js.write_text(PARSER_HARNESS)

    try:
        out = subprocess.run(
            [node, str(tmp_js), str(CODE_GS), str(tmp_stub),
             str(target.year), str(target.month), str(target.day)],
            capture_output=True, text=True, check=True)
        js = json.loads(out.stdout)
    finally:
        tmp_stub.unlink(missing_ok=True)
        tmp_js.unlink(missing_ok=True)

    print(f"  python parsed {len(py)}, javascript parsed {len(js)}")
    assert len(py) == len(js), "parsers returned different fixture counts"

    py_key = sorted((f.div, f.home, f.away, f.kickoff_uk.hour,
                     f.kickoff_uk.minute,
                     round(f.odds.get("HOME") or 0, 6),
                     round(f.odds.get("AWAY") or 0, 6),
                     round((f.fair_odds or {}).get("HOME") or 0, 6)) for f in py)
    js_key = sorted((f["div"], f["home"], f["away"], f["hour"], f["minute"],
                     round(f["odds"].get("HOME") or 0, 6),
                     round(f["odds"].get("AWAY") or 0, 6),
                     round((f["fairOdds"] or {}).get("HOME") or 0, 6)) for f in js)

    for a, b in zip(py_key, js_key):
        assert a == b, f"parser mismatch:\n  py {a}\n  js {b}"

    for row in py_key:
        print(f"    {row[0]:4s} {row[3]:02d}:{row[4]:02d} {row[1]} v {row[2]}  "
              f"H={row[5]} (fair {row[7]})")

    # And both must agree on which survive the 3pm filter.
    py_3pm = sum(1 for f in py if f.is_3pm_saturday())
    js_3pm = sum(1 for f in js if f["hour"] == 15 and f["minute"] == 0)
    assert py_3pm == js_3pm == 3, f"3pm filter disagrees: py {py_3pm}, js {js_3pm}"
    print(f"  both keep {py_3pm} fixtures at 3pm")
    print("  PASS parser agreement")


if __name__ == "__main__":
    print("test_model_agreement");  test_model_agreement()
    print("test_parser_agreement"); test_parser_agreement()
    print("\nPython and Apps Script implementations agree.")
