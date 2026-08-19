/**
 * 3pm Acca Shortlist — Google Apps Script
 *
 * Runs on Google's servers every Saturday morning. Your laptop can be shut,
 * in a bag, or at the bottom of a lake.
 *
 * What it does:
 *   1. Reads team ratings from the 'ratings' tab (exported from the Python
 *      tool — see export_ratings.py; refit monthly, it's not urgent).
 *   2. Fetches Saturday's fixtures and odds from API-Football.
 *   3. Filters to 3pm UK kick-offs in your five leagues.
 *   4. Scores every fixture from the ratings, applies the 1.50 floor.
 *   5. Writes the shortlist to the 'shortlist' tab and emails the group.
 *
 * The heavy maths (fitting 50 parameters by maximum likelihood) happens in
 * Python, offline. All this does is exp() and an 11x11 grid, which is fast
 * and well inside the 6-minute execution limit.
 *
 * SETUP: see SETUP.md. Short version — paste this in, set your API key in
 * Script Properties, run setUp() once.
 */

// ============================================================ configuration

const CFG = {
  // Where fixtures and odds come from.
  //
  //   'free' — football-data.co.uk fixtures.csv. NO API KEY, no signup, no
  //            quota. Six UK bookmakers, best-available and average columns.
  //            Team names match the ratings exactly. Win markets only.
  //   'api'  — API-Football. Needs a free key in Script Properties. Adds the
  //            BTTS market; costs ~45 of your 100 daily requests per run.
  SOURCE: 'free',

  FIXTURES_CSV: 'https://www.football-data.co.uk/fixtures.csv',

  // Which columns to read on the free source.
  //   Price:  Max (best available anywhere), Avg, B365, SKB, PP, BV, BW, BFD
  //   Fair:   Avg is the stable consensus and is what the edge is measured
  //           against. See the long note in accatool/fixtures_csv.py.
  PRICE_SOURCE: 'Max',
  FAIR_SOURCE: 'Avg',

  // Your rules.
  MIN_ODDS: 1.50,
  KICKOFF_HOUR: 15,          // 3pm...
  KICKOFF_MINUTE: 0,
  TIMEZONE: 'Europe/London', // ...UK local. Never compare on UTC — see note below.

  // Sweet spot gate.
  SWEET_MIN_PROB: 0.55,
  SWEET_MIN_EDGE: 0.03,
  SWEET_SIZE: 10,
  SHORTLIST_SIZE: 12,

  // API-Football league ids. Run verifyLeagues() once to confirm.
  LEAGUES: {
    'E0':  { name: 'Premier League',       short: 'PL',  id: 39  },
    'E1':  { name: 'Championship',         short: 'CH',  id: 40  },
    'E2':  { name: 'League One',           short: 'L1',  id: 41  },
    'E3':  { name: 'League Two',           short: 'L2',  id: 42  },
    'SC0': { name: 'Scottish Premiership', short: 'SPL', id: 179 },
  },

  BET_MATCH_WINNER: 1,
  BET_BTTS: 8,

  MAX_GOALS: 10,
  API_HOST: 'https://v3.football.api-sports.io',

  // Who gets the email. Comma-separated. Leave '' to skip emailing.
  EMAIL_TO: '',
};


// =================================================================== entry

/** Run once after pasting the script in. Creates tabs and the weekly trigger. */
function setUp() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  ['ratings', 'shortlist', 'log'].forEach(function (name) {
    if (!ss.getSheetByName(name)) ss.insertSheet(name);
  });

  const ratings = ss.getSheetByName('ratings');
  if (ratings.getLastRow() === 0) {
    ratings.getRange(1, 1, 1, 6)
      .setValues([['div', 'team', 'attack', 'defence', 'home_adv', 'rho']])
      .setFontWeight('bold');
  }

  // Clear any existing triggers for this function so re-running setUp()
  // doesn't stack up duplicate Saturday jobs.
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runWeekly') ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger('runWeekly')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.SATURDAY)
    .atHour(9)
    .inTimezone(CFG.TIMEZONE)
    .create();

  const msg = CFG.SOURCE === 'free'
    ? 'Set up.\n\n' +
      'One thing left: paste your ratings into the "ratings" tab ' +
      '(run export_ratings.py, then paste at A1).\n\n' +
      'No API key needed — fixtures and odds come from football-data.co.uk.\n\n' +
      'The shortlist will build every Saturday at 9am UK.'
    : 'Set up.\n\n' +
      '1. Paste your ratings into the "ratings" tab (from export_ratings.py).\n' +
      '2. Set API_FOOTBALL_KEY in Project Settings > Script Properties.\n' +
      '3. Run verifyLeagues() once to check the league ids.\n\n' +
      'The shortlist will build every Saturday at 9am UK.';

  SpreadsheetApp.getUi().alert(msg);
}

/** The weekly job. */
function runWeekly() {
  buildShortlist(nextSaturday());
}

/** Manual run — same thing, but you can watch it. */
function runNow() {
  const result = buildShortlist(nextSaturday());
  SpreadsheetApp.getUi().alert(result.summary);
}

/** Confirm the league ids match what your key sees. */
function verifyLeagues() {
  const out = [];
  Object.keys(CFG.LEAGUES).forEach(function (div) {
    const meta = CFG.LEAGUES[div];
    try {
      const res = apiGet('/leagues', { id: meta.id });
      out.push(res.length
        ? div + ' id=' + meta.id + ' -> ' + res[0].league.name + ' (' + res[0].country.name + ')'
        : div + ' id=' + meta.id + ' -> NOT FOUND');
    } catch (e) {
      out.push(div + ' id=' + meta.id + ' -> ERROR ' + e.message);
    }
  });
  SpreadsheetApp.getUi().alert(out.join('\n'));
}


// ============================================================== the job

function buildShortlist(targetDate) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const started = new Date();

  const ratings = readRatings();
  if (!ratings.count) {
    return finish_(ss, started, 'No ratings found. Paste export_ratings.py output ' +
                   'into the "ratings" tab first.', []);
  }

  const dateStr = Utilities.formatDate(targetDate, CFG.TIMEZONE, 'yyyy-MM-dd');
  const season = seasonFor(targetDate);

  // ---- fixtures (+ odds, on the free source)
  let fixtures, threePm;

  if (CFG.SOURCE === 'free') {
    fixtures = fetchFreeFixtures(targetDate);
    // The free file gives kick-off as a UK local time string, already in the
    // timezone we filter on.
    threePm = fixtures.filter(function (f) {
      return f.hour === CFG.KICKOFF_HOUR && f.minute === CFG.KICKOFF_MINUTE;
    });
  } else {
    fixtures = [];
    Object.keys(CFG.LEAGUES).forEach(function (div) {
      const res = apiGet('/fixtures', {
        league: CFG.LEAGUES[div].id, season: season, from: dateStr, to: dateStr,
      });
      res.forEach(function (item) {
        fixtures.push({
          id: item.fixture.id,
          div: div,
          league: CFG.LEAGUES[div].name,
          kickoff: new Date(item.fixture.date),
          home: item.teams.home.name,
          away: item.teams.away.name,
        });
      });
    });

    // Must be done in UK local time. From late March to late October the
    // clocks are on BST and 3pm local is 14:00 UTC — filter on UTC and you
    // silently drop every fixture for half the season.
    threePm = fixtures.filter(function (f) {
      const h = Number(Utilities.formatDate(f.kickoff, CFG.TIMEZONE, 'H'));
      const m = Number(Utilities.formatDate(f.kickoff, CFG.TIMEZONE, 'm'));
      return h === CFG.KICKOFF_HOUR && m === CFG.KICKOFF_MINUTE;
    });
  }

  if (!fixtures.length) {
    return finish_(ss, started,
      'No fixtures listed for ' + dateStr + '. The free file is refreshed ' +
      'Friday afternoons for the weekend — try again then.', []);
  }

  if (!threePm.length) {
    return finish_(ss, started,
      'No 3pm kick-offs on ' + dateStr + ' — international break, or a TV-heavy round.', []);
  }

  // ---- odds (API source only; the free source already carried them)
  if (CFG.SOURCE !== 'free') {
    threePm.forEach(function (f) {
      try {
        f.odds = fetchOdds(f.id);
      } catch (e) {
        f.odds = {};
      }
    });
  }

  // ---- score and filter
  const legs = [];
  const unmatched = [];

  threePm.forEach(function (f) {
    const R = ratings.byDiv[f.div];
    if (!R) return;

    const home = resolveTeam(f.home, R.teams);
    const away = resolveTeam(f.away, R.teams);
    if (!home || !away) {
      unmatched.push((home ? f.away : f.home) + '  (' + f.home + ' v ' + f.away + ')');
      return;
    }

    const p = probabilities(R, home, away);
    const o = f.odds || {};
    // On the free source the edge is measured against the market average
    // while the price credited is best-available. Different jobs.
    const fair = devig(f.fairOdds || o);

    [['HOME', p.HOME], ['AWAY', p.AWAY], ['BTTS', p.BTTS]].forEach(function (pair) {
      const market = pair[0], prob = pair[1];
      const price = o[market];
      if (!price || price < CFG.MIN_ODDS) return;

      const fp = fair[market] != null ? fair[market] : (1 / price) * 0.95;
      legs.push({
        div: f.div, league: f.league, leagueShort: CFG.LEAGUES[f.div].short,
        home: f.home, away: f.away,
        market: market,
        label: market === 'BTTS' ? 'Both teams to score'
             : (market === 'HOME' ? f.home : f.away) + ' to win',
        fixture: f.home + ' v ' + f.away,
        odds: price, prob: prob, fair: fp,
        edge: prob - fp, ev: prob * price - 1,
        xgH: p.xgH, xgA: p.xgA,
      });
    });
  });

  if (!legs.length) {
    return finish_(ss, started, 'No legs cleared the rules on ' + dateStr + '.', unmatched);
  }

  // ---- three views
  const safest = legs.slice().sort(function (a, b) { return b.prob - a.prob; })
                     .slice(0, CFG.SHORTLIST_SIZE);
  const value  = legs.slice().sort(function (a, b) { return b.ev - a.ev; })
                     .slice(0, CFG.SHORTLIST_SIZE);
  const sweet  = legs.filter(function (l) {
                        return l.prob >= CFG.SWEET_MIN_PROB && l.edge >= CFG.SWEET_MIN_EDGE;
                      })
                     .sort(function (a, b) { return b.ev - a.ev; })
                     .slice(0, CFG.SWEET_SIZE);

  writeSheet(ss, dateStr, sweet, safest, value, legs, unmatched);

  const summary = dateStr + ': ' + threePm.length + ' fixtures at 3pm, ' +
                  legs.length + ' legs clear the rules, ' +
                  sweet.length + ' in the sweet spot.';

  if (CFG.EMAIL_TO) sendEmail(dateStr, sweet, safest, value, threePm.length, legs.length);

  return finish_(ss, started, summary, unmatched);
}


// ============================================================ the model
//
// Everything below is arithmetic on ratings that were fitted elsewhere.
// No optimisation happens here, which is why it runs in seconds.

function poissonPmf(k, lambda) {
  let logp = -lambda + k * Math.log(lambda);
  for (let i = 2; i <= k; i++) logp -= Math.log(i);
  return Math.exp(logp);
}

/** Full scoreline grid, with the Dixon-Coles low-score correction. */
function scoreMatrix(R, home, away) {
  const lam = Math.exp(R.attack[home] + R.defence[away] + R.homeAdv);
  const mu  = Math.exp(R.attack[away] + R.defence[home]);
  const n = CFG.MAX_GOALS + 1;

  const ph = [], pa = [];
  for (let i = 0; i < n; i++) { ph.push(poissonPmf(i, lam)); pa.push(poissonPmf(i, mu)); }

  const m = [];
  for (let i = 0; i < n; i++) {
    m.push([]);
    for (let j = 0; j < n; j++) m[i].push(ph[i] * pa[j]);
  }

  // Plain Poisson underrates 0-0 and 1-1 and overrates 1-0 and 0-1. Those are
  // exactly the scorelines that decide BTTS in tight games.
  const rho = R.rho;
  m[0][0] *= 1 - lam * mu * rho;
  m[0][1] *= 1 + lam * rho;
  m[1][0] *= 1 + mu * rho;
  m[1][1] *= 1 - rho;

  let total = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    if (m[i][j] < 0) m[i][j] = 0;
    total += m[i][j];
  }
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) m[i][j] /= total;

  return { m: m, lam: lam, mu: mu };
}

function probabilities(R, home, away) {
  const s = scoreMatrix(R, home, away);
  const m = s.m, n = m.length;
  let ph = 0, pd = 0, pa = 0, btts = 0;

  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if (i > j) ph += m[i][j];
      else if (i === j) pd += m[i][j];
      else pa += m[i][j];
      if (i >= 1 && j >= 1) btts += m[i][j];
    }
  }
  return { HOME: ph, DRAW: pd, AWAY: pa, BTTS: btts, xgH: s.lam, xgA: s.mu };
}

/**
 * Strip the bookmaker's margin. Implied probabilities from odds sum to more
 * than 1; the excess is the cut. Normalising gives the market's actual view,
 * which is the only fair thing to compare a model against.
 */
function devig(o) {
  const out = {};
  if (o.HOME && o.DRAW && o.AWAY) {
    const r = [1 / o.HOME, 1 / o.DRAW, 1 / o.AWAY];
    const t = r[0] + r[1] + r[2];
    out.HOME = r[0] / t;
    out.AWAY = r[2] / t;
  }
  if (o.BTTS && o.BTTS_NO) {
    const r = [1 / o.BTTS, 1 / o.BTTS_NO];
    out.BTTS = r[0] / (r[0] + r[1]);
  }
  return out;
}


// ====================================================== free fixtures source
//
// football-data.co.uk publishes upcoming fixtures with odds from six UK
// bookmakers, refreshed Friday afternoons for the weekend. No key, no quota.
// It's the same source as the historical data the ratings were fitted on,
// so team names match exactly and no name-matching is needed.
//
// Columns:
//   Div,Date,Time,HomeTeam,AwayTeam,Referee,
//   B365*  Bet365     BFD*  Betfair Sportsbook   BV*  BetVictor
//   BW*    Bet&Win    PP*   Paddy Power          SKB* Sky Bet
//   Max*   best price available anywhere
//   Avg*   market average
// (each with H/D/A suffixes). No BTTS market — that's the one thing the
// API source adds.

function fetchFreeFixtures(targetDate) {
  const resp = UrlFetchApp.fetch(CFG.FIXTURES_CSV, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) {
    throw new Error('fixtures.csv returned ' + resp.getResponseCode());
  }

  const rows = Utilities.parseCsv(resp.getContentText());
  if (!rows.length) return [];

  const head = rows[0].map(function (h) { return String(h).trim(); });
  const col = {};
  head.forEach(function (h, i) { col[h] = i; });

  const need = ['Div', 'Date', 'Time', 'HomeTeam', 'AwayTeam'];
  need.forEach(function (c) {
    if (col[c] === undefined) throw new Error('fixtures.csv missing column: ' + c);
  });

  const P = CFG.PRICE_SOURCE, F = CFG.FAIR_SOURCE;
  if (col[P + 'H'] === undefined) {
    throw new Error('fixtures.csv has no ' + P + 'H column. Set PRICE_SOURCE to ' +
                    'one of: Max, Avg, B365, SKB, PP, BV, BW, BFD');
  }

  const want = Utilities.formatDate(targetDate, CFG.TIMEZONE, 'dd/MM/yyyy');

  const num = function (r, name) {
    if (col[name] === undefined) return null;
    const v = parseFloat(r[col[name]]);
    return (isNaN(v) || v <= 1.0) ? null : v;
  };

  const out = [];
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r || r.length < need.length) continue;

    const div = String(r[col.Div]).trim();
    if (!CFG.LEAGUES[div]) continue;                    // not one of our five

    if (String(r[col.Date]).trim() !== want) continue;  // wrong day

    const time = String(r[col.Time]).trim().split(':');
    const hour = parseInt(time[0], 10);
    const minute = parseInt(time[1], 10);
    if (isNaN(hour) || isNaN(minute)) continue;

    const odds = {}, fairOdds = {};
    [['HOME', 'H'], ['DRAW', 'D'], ['AWAY', 'A']].forEach(function (pair) {
      const p = num(r, P + pair[1]);
      if (p !== null) odds[pair[0]] = p;
      const q = num(r, F + pair[1]);
      if (q !== null) fairOdds[pair[0]] = q;
    });

    if (!odds.HOME && !odds.AWAY) continue;             // no usable prices

    out.push({
      id: 0,
      div: div,
      league: CFG.LEAGUES[div].name,
      leagueShort: CFG.LEAGUES[div].short,
      home: String(r[col.HomeTeam]).trim(),
      away: String(r[col.AwayTeam]).trim(),
      hour: hour,
      minute: minute,
      odds: odds,
      fairOdds: Object.keys(fairOdds).length ? fairOdds : null,
    });
  }

  return out;
}


// ============================================================== API calls

function apiKey() {
  const k = PropertiesService.getScriptProperties().getProperty('API_FOOTBALL_KEY');
  if (!k) throw new Error('API_FOOTBALL_KEY not set. Project Settings > Script Properties.');
  return k;
}

function apiGet(path, params) {
  const qs = Object.keys(params).map(function (k) {
    return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
  }).join('&');

  const resp = UrlFetchApp.fetch(CFG.API_HOST + path + '?' + qs, {
    headers: { 'x-apisports-key': apiKey() },
    muteHttpExceptions: true,
  });

  if (resp.getResponseCode() !== 200) {
    throw new Error(path + ' returned ' + resp.getResponseCode());
  }

  const body = JSON.parse(resp.getContentText());
  if (body.errors && Object.keys(body.errors).length) {
    throw new Error(path + ': ' + JSON.stringify(body.errors));
  }
  return body.response || [];
}

/**
 * Match-winner and BTTS in a single request. We collect the draw and BTTS-No
 * prices too — never bet them, but without the other side of the market you
 * cannot strip the margin out, and the value column depends on that.
 */
function fetchOdds(fixtureId) {
  const res = apiGet('/odds', { fixture: fixtureId });
  if (!res.length) return {};

  const buckets = { HOME: [], DRAW: [], AWAY: [], BTTS: [], BTTS_NO: [] };

  (res[0].bookmakers || []).forEach(function (book) {
    (book.bets || []).forEach(function (bet) {
      if (bet.id === CFG.BET_MATCH_WINNER) {
        (bet.values || []).forEach(function (v) {
          const val = String(v.value || '').toLowerCase();
          const odd = parseFloat(v.odd);
          if (!odd) return;
          if (val === 'home' || val === '1') buckets.HOME.push(odd);
          else if (val === 'draw' || val === 'x') buckets.DRAW.push(odd);
          else if (val === 'away' || val === '2') buckets.AWAY.push(odd);
        });
      } else if (bet.id === CFG.BET_BTTS) {
        (bet.values || []).forEach(function (v) {
          const val = String(v.value || '').toLowerCase();
          const odd = parseFloat(v.odd);
          if (!odd) return;
          if (val === 'yes') buckets.BTTS.push(odd);
          else if (val === 'no') buckets.BTTS_NO.push(odd);
        });
      }
    });
  });

  // Median across bookmakers: a fair proxy for the price you'll actually get,
  // and immune to one outlier.
  const out = {};
  Object.keys(buckets).forEach(function (k) {
    const v = buckets[k];
    if (!v.length) return;
    v.sort(function (a, b) { return a - b; });
    const mid = Math.floor(v.length / 2);
    out[k] = v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
  });
  return out;
}


// ============================================================== ratings

function readRatings() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('ratings');
  if (!sh || sh.getLastRow() < 2) return { count: 0, byDiv: {} };

  const rows = sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues();
  const byDiv = {};
  let count = 0;

  rows.forEach(function (r) {
    const div = String(r[0]).trim();
    const team = String(r[1]).trim();
    if (!div || !team) return;

    if (!byDiv[div]) byDiv[div] = { attack: {}, defence: {}, homeAdv: 0, rho: 0, teams: [] };
    byDiv[div].attack[team] = Number(r[2]);
    byDiv[div].defence[team] = Number(r[3]);
    byDiv[div].homeAdv = Number(r[4]);
    byDiv[div].rho = Number(r[5]);
    byDiv[div].teams.push(team);
    count++;
  });

  return { count: count, byDiv: byDiv };
}

/** API-Football says "Nottingham Forest"; football-data.co.uk says "Nott'm Forest". */
function resolveTeam(apiName, knownTeams) {
  const norm = function (s) {
    return String(s).toLowerCase().replace(/&/g, 'and').replace(/[.'']/g, '')
                    .replace(/\s+/g, ' ').trim();
  };
  const target = norm(apiName);

  for (let i = 0; i < knownTeams.length; i++) {
    if (norm(knownTeams[i]) === target) return knownTeams[i];
  }

  // Prefix match handles most of the rest: "Manchester United" -> "Man United"
  // won't hit, but "Wigan Athletic" -> "Wigan" and "Bolton Wanderers" ->
  // "Bolton" both do, and those are the common shape.
  let best = null, bestLen = 0;
  for (let i = 0; i < knownTeams.length; i++) {
    const k = norm(knownTeams[i]);
    if ((target.indexOf(k) === 0 || k.indexOf(target) === 0) && k.length > bestLen) {
      best = knownTeams[i];
      bestLen = k.length;
    }
  }
  if (best) return best;

  // Token overlap, for the awkward ones.
  const tt = target.split(' ');
  let bestScore = 0;
  for (let i = 0; i < knownTeams.length; i++) {
    const kt = norm(knownTeams[i]).split(' ');
    let shared = 0;
    tt.forEach(function (t) { if (kt.indexOf(t) !== -1 && t.length > 2) shared++; });
    const score = shared / Math.max(tt.length, kt.length);
    if (score > bestScore && score >= 0.5) { bestScore = score; best = knownTeams[i]; }
  }
  return best;
}


// =============================================================== output

function writeSheet(ss, dateStr, sweet, safest, value, allLegs, unmatched) {
  const sh = ss.getSheetByName('shortlist');
  sh.clear();

  const rows = [];
  const pct = function (x) { return Math.round(x * 100) + '%'; };
  // '+24.7% EV' means nothing to most people. Money does.
  const per10 = function (ev) {
    const v = ev * 10;
    return (v >= 0 ? '+' : '-') + '£' + Math.abs(v).toFixed(2);
  };

  rows.push(['3pm Acca Shortlist — Saturday ' + dateStr]);
  rows.push(['3pm Saturday kick-offs · Premier League, EFL, Scottish Premiership · ' +
             'win or both teams to score · nothing shorter than ' +
             CFG.MIN_ODDS.toFixed(2)]);
  rows.push(['We say = how often we reckon it wins. Bookies say = the same, ' +
             'according to the price. Per £10 = long-run average profit per £10 ' +
             'staked, not what you win this Saturday.']);
  rows.push([]);

  // ---- sweet spot
  rows.push(['BEST PICKS — we think these will probably win, AND that the ' +
             'bookies are paying too much for them. Best first.']);
  rows.push(['Pick', 'Game', 'League', 'Odds', 'We say', 'Bookies say', 'Per £10']);

  if (sweet.length) {
    sweet.forEach(function (l) {
      rows.push([l.label, l.fixture, l.leagueShort, l.odds, pct(l.prob), pct(l.fair),
                 per10(l.ev)]);
    });
    const n = Math.min(6, sweet.length);
    let odds = 1, prob = 1;
    for (let i = 0; i < n; i++) { odds *= sweet[i].odds; prob *= sweet[i].prob; }
    rows.push(['Put the top ' + n + ' together', '', '', odds.toFixed(2) + '/1',
               pct(prob) + ' chance all ' + n + ' win', '',
               '£10 returns £' + (10 * odds).toFixed(2)]);
  } else {
    rows.push(['Nothing passed both tests this week. That is a real answer, not a gap: ' +
               'the likely winners are priced about right, and the well-paid ones are ' +
               'genuinely risky. Use the two lists below.']);
  }

  rows.push([]);
  rows.push(['MOST LIKELY TO WIN — safest bets, whatever the price']);
  rows.push(['Pick', 'Game', 'League', 'Odds', 'We say', 'Bookies say', 'Per £10']);
  safest.forEach(function (l) {
    rows.push([l.label, l.fixture, l.leagueShort, l.odds, pct(l.prob), pct(l.fair),
               per10(l.ev)]);
  });

  rows.push([]);
  rows.push(['BEST VALUE — biggest overpay, whatever the risk']);
  rows.push(['Pick', 'Game', 'League', 'Odds', 'We say', 'Bookies say', 'Per £10']);
  value.forEach(function (l) {
    rows.push([l.label, l.fixture, l.leagueShort, l.odds, pct(l.prob), pct(l.fair),
               per10(l.ev)]);
  });

  if (unmatched.length) {
    rows.push([]);
    rows.push(['UNMATCHED TEAMS — these fixtures were skipped, add them to the ratings tab']);
    unmatched.forEach(function (u) { rows.push([u]); });
  }

  rows.push([]);
  rows.push(['EVERY BET THAT MADE THE CUT (' + allLegs.length + ')']);
  rows.push(['Pick', 'Game', 'League', 'Odds', 'We say', 'Bookies say', 'Per £10']);
  allLegs.slice().sort(function (a, b) { return b.prob - a.prob; }).forEach(function (l) {
    rows.push([l.label, l.fixture, l.leagueShort, l.odds, pct(l.prob), pct(l.fair),
               per10(l.ev)]);
  });

  // Pad to a rectangle — setValues requires equal row lengths.
  const width = 7;
  const padded = rows.map(function (r) {
    const copy = r.slice();
    while (copy.length < width) copy.push('');
    return copy;
  });

  sh.getRange(1, 1, padded.length, width).setValues(padded);
  sh.getRange(1, 1, 1, width).setFontSize(14).setFontWeight('bold');
  sh.setFrozenRows(2);
  for (let c = 1; c <= width; c++) sh.autoResizeColumn(c);
}

function sendEmail(dateStr, sweet, safest, value, nFixtures, nLegs) {
  const line = function (l) {
    const v = l.ev * 10;
    return '  ' + Math.round(l.prob * 100) + '% we say  @' + l.odds.toFixed(2) +
           '  (' + (v >= 0 ? '+' : '-') + '£' + Math.abs(v).toFixed(2) + ' per £10)  ' +
           l.label + '  (' + l.fixture + ', ' + l.leagueShort + ')';
  };

  let body = '3pm Acca Shortlist — Saturday ' + dateStr + '\n\n' +
             nFixtures + ' games at 3pm, ' + nLegs + ' bets worth considering.\n\n';

  body += 'BEST PICKS (likely to win AND the bookies are paying too much)\n';
  if (sweet.length) {
    body += sweet.map(line).join('\n') + '\n';
    const n = Math.min(6, sweet.length);
    let odds = 1, prob = 1;
    for (let i = 0; i < n; i++) { odds *= sweet[i].odds; prob *= sweet[i].prob; }
    body += '\n  Top ' + n + ' together: ' + odds.toFixed(2) +
            ' at ' + (prob * 100).toFixed(1) + '% — £10 returns £' + (10 * odds).toFixed(2) + '\n';
  } else {
    body += '  Nothing passed both tests this week.\n';
  }

  body += '\nMOST LIKELY TO WIN\n' + safest.slice(0, 6).map(line).join('\n');
  body += '\n\nBEST VALUE\n' + value.slice(0, 6).map(line).join('\n');
  body += '\n\nFull tables: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl();
  body += '\n\nThese are estimates, not promises. Every leg has to win, so ' +
          'multiply the percentages together for your real chance: six at 70% ' +
          'is 11.8%, not 70%.';

  MailApp.sendEmail({
    to: CFG.EMAIL_TO,
    subject: '3pm Acca Shortlist — ' + dateStr,
    body: body,
  });
}


// =============================================================== helpers

function nextSaturday() {
  const now = new Date();
  const dow = Number(Utilities.formatDate(now, CFG.TIMEZONE, 'u')); // 1=Mon .. 7=Sun
  const daysAhead = (6 - dow + 7) % 7;   // 6 = Saturday
  const d = new Date(now.getTime() + daysAhead * 86400000);
  d.setHours(12, 0, 0, 0);
  return d;
}

/** API-Football labels a season by the year it starts in. */
function seasonFor(date) {
  const y = Number(Utilities.formatDate(date, CFG.TIMEZONE, 'yyyy'));
  const m = Number(Utilities.formatDate(date, CFG.TIMEZONE, 'M'));
  return m >= 7 ? y : y - 1;
}

function finish_(ss, started, summary, unmatched) {
  const log = ss.getSheetByName('log');
  const secs = ((new Date()) - started) / 1000;
  log.appendRow([new Date(), summary, unmatched.length ? unmatched.join('; ') : '',
                 secs.toFixed(1) + 's']);
  return { summary: summary, unmatched: unmatched };
}

/** Adds a menu so you can trigger things without opening the editor. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Acca')
    .addItem('Build shortlist now', 'runNow')
    .addItem('Verify league ids', 'verifyLeagues')
    .addItem('Set up / reset trigger', 'setUp')
    .addToUi();
}
