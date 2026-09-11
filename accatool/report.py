"""Render the shortlist as a single self-contained HTML page."""

from __future__ import annotations

import datetime as dt
import html
import json

from . import config

CSS = """
:root{
  --bg:#0f1115; --panel:#171a21; --line:#252a34; --ink:#e8eaed; --muted:#9aa3b2;
  --accent:#4ea3ff; --good:#3ddc84; --warm:#ffb020; --both:#c084fc;
}
@media (prefers-color-scheme: light){
  :root{ --bg:#f6f7f9; --panel:#fff; --line:#e3e6eb; --ink:#141822;
         --muted:#5d6675; --accent:#0b6bcb; --good:#0f8a4d; --warm:#a86400;
         --both:#7c3aed; }
}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:14px;margin-bottom:28px}
.rules{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 30px}
.rule{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:5px 13px;font-size:12.5px;color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media (max-width:900px){.cols{grid-template-columns:1fr}}
.col{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.col h2{margin:0;padding:15px 18px;font-size:15px;border-bottom:1px solid var(--line);
  display:flex;justify-content:space-between;align-items:baseline}
.col h2 span{font-weight:400;color:var(--muted);font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:500;color:var(--muted);font-size:11.5px;
  text-transform:uppercase;letter-spacing:.05em;padding:9px 10px;border-bottom:1px solid var(--line)}
td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pick{font-weight:600}
.fix{color:var(--muted);font-size:12px;display:block;margin-top:2px}
.tag{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:4px;
  background:var(--line);color:var(--muted);margin-left:6px;vertical-align:1px}
.both{background:color-mix(in srgb,var(--both) 22%,transparent);color:var(--both);font-weight:600}
.thin{background:color-mix(in srgb,var(--warm) 20%,transparent);color:var(--warm);font-weight:600}
.slot{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);
  font-weight:600;padding:1px 5px;border-radius:4px}
.pos{color:var(--good)} .neg{color:var(--muted)} .muted{color:var(--muted)}
th[title]{cursor:help;border-bottom:1px dotted var(--line)}
.note b{color:var(--ink)}
.note br{content:"";display:block;margin-bottom:6px}

/* tick-to-build slip */
td.sel,th.sel{width:34px;padding-left:14px;padding-right:0}
input.pk{width:16px;height:16px;cursor:pointer;accent-color:var(--both);margin-top:1px}
tr:has(input.pk:checked){background:color-mix(in srgb,var(--both) 10%,transparent)}
body{padding-bottom:132px}
#slip{position:fixed;left:0;right:0;bottom:0;z-index:50;
  background:var(--panel);border-top:1px solid var(--line);
  box-shadow:0 -8px 28px rgba(0,0,0,.28);
  transform:translateY(105%);transition:transform .18s ease}
#slip.on{transform:none}
.slip-in{max-width:1180px;margin:0 auto;padding:13px 20px;display:flex;
  align-items:center;gap:20px;flex-wrap:wrap;justify-content:space-between}
.slip-stats{display:flex;gap:22px;align-items:baseline;flex-wrap:wrap}
.slip-n{font-weight:600;font-size:15px}
.slip-s{font-size:12.5px;color:var(--muted)}
.slip-s b{color:var(--ink);font-size:15px;font-variant-numeric:tabular-nums;
  margin-left:5px;font-weight:600}
.slip-btns{display:flex;gap:9px}
#slip button{font:inherit;font-size:13.5px;font-weight:500;padding:8px 17px;
  border-radius:8px;border:1px solid transparent;cursor:pointer;
  background:var(--both);color:#fff}
#slip button.ghost{background:transparent;border-color:var(--line);color:var(--muted)}
#slip button:hover{filter:brightness(1.08)}
#slip-warn{display:none;max-width:1180px;margin:0 auto;padding:0 20px 13px;
  font-size:12.5px;color:var(--warm)}
#slip-warn b{color:var(--warm)}
@media (max-width:640px){.slip-in{gap:12px}.slip-s{font-size:12px}}
.note{margin-top:30px;padding:16px 18px;background:var(--panel);
  border:1px solid var(--line);border-left:3px solid var(--warm);border-radius:10px;
  font-size:13.5px;color:var(--muted)}
.note b{color:var(--ink)}

/* sweet spot -- the lead section */
.sweet{background:var(--panel);border:1px solid var(--line);
  border-top:3px solid var(--both);border-radius:14px;overflow:hidden;margin-bottom:22px}
.sweet h2{margin:0;padding:16px 18px 14px;border-bottom:1px solid var(--line)}
.sweet h2 .t{font-size:16px;display:flex;align-items:center;gap:9px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--both);flex:none}
.sweet h2 .d{font-weight:400;color:var(--muted);font-size:12.5px;margin-top:5px;
  display:block;max-width:70ch}
.empty{padding:22px 18px;color:var(--muted);font-size:13.5px}
.bar{display:flex;gap:26px;flex-wrap:wrap;padding:13px 18px;
  border-top:1px solid var(--line);background:color-mix(in srgb,var(--both) 7%,transparent)}
.stat{font-size:12px;color:var(--muted)}
.stat b{display:block;font-size:17px;color:var(--ink);font-variant-numeric:tabular-nums;
  margin-top:2px;letter-spacing:-.01em}
.gate{font-size:11.5px;color:var(--muted);padding:0 18px 14px}
details{margin-top:26px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
summary{padding:14px 18px;cursor:pointer;font-size:14px;font-weight:500}
details table{border-top:1px solid var(--line)}
.foot{margin-top:34px;color:var(--muted);font-size:12px;text-align:center}
.fake{background:#7a1d1d;color:#ffe4e4;border-radius:12px;padding:14px 18px;
  margin-bottom:22px;font-size:14px;border:1px solid #a33}
.fake b{color:#fff}
@media (prefers-color-scheme: light){.fake{background:#fdecec;color:#7a1d1d;border-color:#e5a0a0}
  .fake b{color:#7a1d1d}}
"""


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


def _slot_label() -> str:
    """Describe the configured slots in English, however many there are."""
    parts = [f"{DAY_NAMES[d]} {h}:{m:02d}" for d, h, m in config.SLOTS]
    if len(parts) == 1:
        return f"{parts[0]} kick-offs"
    return " · ".join(parts)


def _per_tenner(ev):
    """Expected value as money, because '+24.7% EV' means nothing to most people.

    'Per £10' is the same number expressed as: if you backed this same
    situation every week for a season, this is what you'd average per bet.
    """
    v = ev * 10.0
    return f"{'+' if v >= 0 else '−'}£{abs(v):.2f}"


def _key(leg):
    return (leg.home, leg.away, leg.market)


def _when(leg, show):
    """Kick-off time, with the group's 3pm Saturday slot marked.

    Once the page covers midweek games too, "Sat 15:00" stops being implied
    and the main ritual needs picking out of the crowd.
    """
    if not (show and leg.when):
        return ""
    if leg.is_3pm_sat:
        return (f'<span class="slot">{html.escape(leg.when)}</span> &middot; ')
    return f"{html.escape(leg.when)} &middot; "


def _thin_tag(leg):
    """Mark picks where the model is working from very little.

    Almost all of what the model knows is historical. Early in a season, or
    for a side promoted over the summer, that means a confident-looking
    percentage is resting on thin air. Better to say so on the row than to
    let the number stand unqualified.
    """
    if not leg.thin:
        return ""
    return (f'<span class="tag thin" title="The model has little recent data on '
            f'{html.escape(leg.thin)} — treat this percentage with caution">'
            f'little data: {html.escape(leg.thin)}</span>')


def _tick(leg, idx):
    """Checkbox cell. The same leg can appear in more than one table, so it
    carries a stable id and all its copies stay in sync."""
    i = idx[_key(leg)]
    return (f'<td class="sel"><input type="checkbox" class="pk" '
            f'data-i="{i}" aria-label="Add to slip"></td>')


def _row(leg, is_both, idx, show_when=False):
    tag = '<span class="tag both">both lists</span>' if is_both else ""
    ev_cls = "pos" if leg.ev > 0 else "neg"
    return f"""<tr>
      {_tick(leg, idx)}
      <td><span class="pick">{html.escape(leg.label)}</span>{tag}{_thin_tag(leg)}
          <span class="fix">{_when(leg, show_when)}{html.escape(leg.fixture)} &middot; {html.escape(leg.league_short)}</span></td>
      <td class="num">{leg.odds:.2f}</td>
      <td class="num">{leg.prob * 100:.0f}%</td>
      <td class="num {ev_cls}">{_per_tenner(leg.ev)}</td>
    </tr>"""


def _table(title, subtitle, legs, both_keys, idx, show_when=False):
    rows = "\n".join(_row(l, _key(l) in both_keys, idx, show_when) for l in legs)
    return f"""<div class="col">
      <h2>{title}<span>{subtitle}</span></h2>
      <table>
        <thead><tr><th class="sel"></th><th>Pick</th>
        <th class="num" title="The bookmaker's price">Odds</th>
        <th class="num" title="How often we think this wins">We&nbsp;say</th>
        <th class="num" title="Average profit per £10 staked, if we're right, over many bets">Per&nbsp;£10</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


SLIP_JS = """
(function () {
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.pk'));
  var slip = document.getElementById('slip');
  var picked = new Set();

  function fmtMoney(v) { return (v < 0 ? '−£' : '£') + Math.abs(v).toFixed(2); }

  function selected() {
    var out = [];
    picked.forEach(function (i) { out.push(LEGS[i]); });
    // Keep them in the order they appear on the page, not click order.
    return out.sort(function (a, b) { return a.i - b.i; });
  }

  function render() {
    var legs = selected();
    if (!legs.length) { slip.classList.remove('on'); return; }
    slip.classList.add('on');

    var odds = 1, prob = 1;
    legs.forEach(function (l) { odds *= l.odds; prob *= l.prob; });

    // Two picks from the same match are not independent, and most bookmakers
    // won't take them as an ordinary acca anyway. Say so rather than quietly
    // printing a probability that is wrong.
    var seen = {}, clash = null;
    legs.forEach(function (l) {
      if (seen[l.fixture]) clash = l.fixture;
      seen[l.fixture] = true;
    });

    document.getElementById('slip-n').textContent =
      legs.length + (legs.length === 1 ? ' pick' : ' picks');
    document.getElementById('slip-odds').textContent = odds.toFixed(2) + '/1';
    document.getElementById('slip-prob').textContent = Math.round(prob * 1000) / 10 + '%';
    document.getElementById('slip-ret').textContent = fmtMoney(10 * odds);

    var warn = document.getElementById('slip-warn');
    if (clash) {
      warn.style.display = 'block';
      warn.innerHTML = '<b>Two picks from ' + clash + '.</b> Same-game picks ' +
        'affect each other, so the chance shown above is optimistic — and most ' +
        'bookies won\\'t take them as a normal acca.';
    } else {
      warn.style.display = 'none';
    }
  }

  function slipText() {
    var legs = selected();
    var odds = 1, prob = 1;
    legs.forEach(function (l) { odds *= l.odds; prob *= l.prob; });

    var lines = [ACCA_TITLE, ''];
    legs.forEach(function (l, n) {
      lines.push((n + 1) + '. ' + l.label + ' @ ' + l.odds.toFixed(2) +
                 '  (' + l.fixture + ')');
    });
    lines.push('');
    lines.push(legs.length + ' picks @ ' + odds.toFixed(2) + '/1 — £10 returns ' +
               fmtMoney(10 * odds));
    lines.push('We make it ' + (Math.round(prob * 1000) / 10) + '% that all ' +
               legs.length + ' win.');
    return lines.join('\\n');
  }

  function flash(msg) {
    var b = document.getElementById('slip-copy');
    var old = b.textContent;
    b.textContent = msg;
    setTimeout(function () { b.textContent = old; }, 1600);
  }

  function copy() {
    var text = slipText();
    // navigator.clipboard needs a secure context. A page opened from disk
    // usually qualifies, but not always — so fall back to the old textarea
    // trick rather than failing silently.
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text)
        .then(function () { flash('Copied'); })
        .catch(function () { legacyCopy(text); });
    } else {
      legacyCopy(text);
    }
  }

  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    flash(ok ? 'Copied' : 'Press Cmd+C');
    if (!ok) window.prompt('Copy your slip:', text);
  }

  boxes.forEach(function (b) {
    b.addEventListener('change', function () {
      var i = Number(b.dataset.i);
      if (b.checked) picked.add(i); else picked.delete(i);
      // The same pick can be listed in two tables; keep the copies in step.
      boxes.forEach(function (o) {
        if (Number(o.dataset.i) === i) o.checked = b.checked;
      });
      render();
    });
  });

  document.getElementById('slip-copy').addEventListener('click', copy);
  document.getElementById('slip-clear').addEventListener('click', function () {
    picked.clear();
    boxes.forEach(function (b) { b.checked = false; });
    render();
  });
})();
"""


def _held_note(held):
    """Say plainly that some picks were withheld, and why.

    Silently shortening a list is worse than not filtering at all -- it looks
    like the week was quiet when actually the tool binned its own worst
    guesses.
    """
    if not held:
        return ""
    teams = sorted({t.strip() for l in held for t in l.thin.split(",") if t.strip()})
    shown = ", ".join(teams[:6]) + (" and others" if len(teams) > 6 else "")
    return f"""<div class="note"><b>{len(held)} pick{"s" if len(held) != 1 else ""}
      held back from the ranked lists.</b> They involve teams the model has barely
      seen &mdash; {html.escape(shown)} &mdash; usually promoted or relegated sides,
      or clubs a couple of games into a season.
      <br>A thin rating doesn't just make a pick uncertain, it makes it
      <em>more likely to be chosen</em>: little data gives an unreliable number,
      an unreliable number disagrees loudly with the bookies, and disagreeing
      loudly is exactly what "best value" rewards. Left alone, this page fills
      up with the model's worst guesses dressed as its best ideas.
      They're all still listed at the bottom if you want to judge for yourself.</div>"""


def _fake_banner(meta):
    """Mock mode has to be impossible to miss.

    The page is otherwise identical to a real one, so a small footnote is not
    enough -- every number here is invented and someone will otherwise read
    them as picks.
    """
    if "mock" not in meta.get("mode", "").lower():
        return ""
    return """<div class="fake"><b>These are made-up numbers.</b>
      You ran with <code>--mock</code>, so the fixtures, the odds and every
      percentage on this page are invented for testing. Nothing here is a real
      match or a real price. Run <code>python run.py</code> without
      <code>--mock</code> for the real thing.</div>"""


def _slip_bar():
    return """
  <div id="slip">
    <div class="slip-in">
      <div class="slip-stats">
        <span class="slip-n" id="slip-n">0 picks</span>
        <span class="slip-s">pays <b id="slip-odds">—</b></span>
        <span class="slip-s">chance all win <b id="slip-prob">—</b></span>
        <span class="slip-s">£10 returns <b id="slip-ret">—</b></span>
      </div>
      <div class="slip-btns">
        <button id="slip-clear" class="ghost">Clear</button>
        <button id="slip-copy">Copy slip</button>
      </div>
    </div>
    <div id="slip-warn"></div>
  </div>"""


def _sweet_section(sweet, summary, idx, show_when=False):
    """The crossover: likely to land and priced generously."""
    head = f"""<h2><span class="t"><span class="dot"></span>Best picks</span>
      <span class="d">These pass both tests: we think they'll <strong>probably
      win</strong>, and we think the <strong>bookies are paying too much</strong>
      for them. Best first.</span></h2>"""

    if not sweet:
        return f"""<div class="sweet">{head}
          <div class="empty"><b>Nothing passed both tests this week.</b>
          That's a real answer, not a gap. It means the picks that look likely are
          priced about right, and the picks that are paying well are genuinely
          risky. Use the two lists below and pick which of those you'd rather have.</div>
        </div>"""

    rows = "\n".join(f"""<tr>
      {_tick(l, idx)}
      <td><span class="pick">{html.escape(l.label)}</span>{_thin_tag(l)}
          <span class="fix">{_when(l, show_when)}{html.escape(l.fixture)} &middot; {html.escape(l.league_short)}
          &middot; avg goals {l.xg_home:.1f} v {l.xg_away:.1f}</span></td>
      <td class="num">{l.odds:.2f}</td>
      <td class="num">{l.prob * 100:.0f}%</td>
      <td class="num muted">{l.fair_prob * 100:.0f}%</td>
      <td class="num pos">{_per_tenner(l.ev)}</td>
    </tr>""" for l in sweet)

    n = min(6, len(sweet))
    bar = f"""<div class="bar">
      <div class="stat">Picks that passed<b>{len(sweet)}</b></div>
      <div class="stat">Top {n} together pay<b>{summary['odds']:.0f}/1</b></div>
      <div class="stat">Chance all {n} win<b>{summary['prob']*100:.1f}%</b></div>
      <div class="stat">£10 would return<b>£{summary['returns_on_10']:,.0f}</b></div>
    </div>"""

    return f"""<div class="sweet">{head}
      <table>
        <thead><tr><th class="sel"></th><th>Pick</th>
        <th class="num" title="The bookmaker's price">Odds</th>
        <th class="num" title="How often we think this wins">We&nbsp;say</th>
        <th class="num" title="How often the price says it wins">Bookies&nbsp;say</th>
        <th class="num" title="Average profit per £10 staked, if we're right, over many bets">Per&nbsp;£10</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>{bar}
    </div>"""


def _all_fixtures_table(legs):
    by_fixture = {}
    for l in legs:
        by_fixture.setdefault((l.league_short, l.fixture, l.xg_home, l.xg_away), []).append(l)

    rows = []
    for (league, fixture, xh, xa), group in sorted(by_fixture.items(), key=lambda k: k[0][0]):
        markets = " &middot; ".join(
            f"{html.escape(l.label.split(' to win')[0] if l.market != 'BTTS' else 'Both score')} "
            f"@{l.odds:.2f} ({l.prob*100:.0f}%)" for l in group)
        rows.append(f"""<tr><td>{html.escape(fixture)}
          <span class="fix">{html.escape(league)} &middot; avg goals
          {xh:.1f} v {xa:.1f}</span></td>
          <td>{markets}</td></tr>""")

    return f"""<details>
      <summary>Every game that made the cut ({len(by_fixture)})</summary>
      <table><thead><tr><th>Game</th><th>Bets available &amp; our chance</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table>
    </details>"""


def render(safest, value, both_keys, all_legs, meta, sweet=None, sweet_summary=None,
           held=None) -> str:
    generated = dt.datetime.now(config.UK).strftime("%a %d %b %Y, %H:%M")
    show_when = bool(meta.get("window"))

    # One stable index per distinct leg, so a pick listed in two tables ticks
    # once and counts once.
    idx = {}
    legs_js = []
    for leg in all_legs:
        k = _key(leg)
        if k in idx:
            continue
        idx[k] = len(legs_js)
        legs_js.append({
            "i": len(legs_js),
            "label": leg.label,
            "fixture": leg.fixture,
            "league": leg.league,
            "odds": round(leg.odds, 2),
            "prob": round(leg.prob, 6),
        })

    rules = "".join(f'<span class="rule">{html.escape(r)}</span>' for r in [
        ("All kick-off times" if show_when else _slot_label()),
        "Premier League · EFL · Scottish Premiership",
        "Win or both teams to score",
        f"Nothing shorter than {config.MIN_ODDS:.2f}",
    ])

    n_both = len(both_keys)
    both_note = (f"<b>{n_both} pick{'s' if n_both != 1 else ''} show up in both lists</b> "
                 "(tagged above). Likely to win <em>and</em> well paid — worth a look."
                 ) if n_both else (
                 "<b>Nothing shows up in both lists this week.</b> The likely winners are "
                 "priced about right, and the well-paid ones are genuinely risky. "
                 "That's normal — most weeks look like this.")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>3pm Acca Shortlist — {meta['date']}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
  <h1>{"Acca Shortlist" if show_when else "3pm Acca Shortlist"}</h1>
  <div class="sub">{meta['date']} &middot; {meta['n_fixtures']} games
    &middot; {len(all_legs)} bets worth considering</div>
  <div class="rules">{rules}</div>

  {_fake_banner(meta)}

  {_sweet_section(sweet or [], sweet_summary or {}, idx, show_when)}

  <div class="cols">
    {_table("Most likely to win", "safest bets, whatever the price", safest, both_keys, idx, show_when)}
    {_table("Best value", "biggest overpay, whatever the risk", value, both_keys, idx, show_when)}
  </div>

  <div class="note">{both_note}</div>

  {_held_note(held or [])}

  <div class="note"><b>What the numbers mean.</b><br>
    <b>Odds</b> — the bookmaker's price. 2.50 means a £10 bet returns £25 if it wins.<br>
    <b>We say</b> — how often we reckon this wins. 65% means we'd expect it to come off
      roughly two times in three.<br>
    <b>Bookies say</b> — the same thing, but according to the price, with the bookmaker's
      cut taken out. If we say 65% and they say 50%, we think they're paying over the odds.<br>
    <b>Per £10</b> — if you backed this same kind of bet every week all season, this is
      what you'd average per £10 bet. <b>+£2.50 doesn't mean you win £2.50 this Saturday</b>
      — you either win the bet or you don't. It's the long-run average, and only if we're
      right about the chances.<br>
    <b>little data</b> — an amber tag means the model has barely seen that team: newly
      promoted, or only a couple of games in. Nearly everything it knows is historical,
      so early in a season a confident-looking percentage can be resting on last year's
      squad. Treat those with suspicion.<br>
    <b>Avg goals</b> — how many goals we'd expect each side to score <em>on average</em>,
      not a prediction of the final score. "1.1 v 2.5" means the away side is the stronger
      bet, but plenty of individual games finish 0-0 or 4-3. Every percentage above is
      worked out from these two numbers.</div>


  {_all_fixtures_table(all_legs)}

  <div class="foot">Generated {generated} · model fitted on
    {meta['n_matches']:,} matches · {meta['mode']}</div>
</div>

{_slip_bar()}

<script>
const ACCA_TITLE = {json.dumps(('Acca — ' if show_when else '3pm Acca — Sat ') + meta['date'])};
const LEGS = {json.dumps(legs_js)};
</script>
<script>{SLIP_JS}</script>
</body></html>"""
