# 3pm Acca Shortlist

Ranks every 3pm Saturday leg that clears your rules three ways — **sweet spot**, **safest**, **best value** — and stops there. It doesn't pick the acca. That's still the group's argument.

**The rules, as encoded:** 3pm Saturday kick-off · Premier League, Championship, League One, League Two, Scottish Premiership · win or BTTS only · odds ≥ 1.50.

---

## Two ways to run it

**Python, locally** — no account, no key, works in two commands. Start here.

**Google Sheets** (`sheets/`) — runs on Google's servers every Saturday at 9am, laptop shut. Writes to a shared Sheet and emails the group. Also needs no API key. You refresh the model's ratings from the Python tool about once a month. **See `sheets/SETUP.md`.**

Neither route requires an account anywhere. The two share the same model and the same parser, cross-checked by `tests/test_apps_script.py`, which runs the real `Code.gs` functions in node: the model agrees to machine precision (max difference 1.1e-15), the parser returns identical fixtures.

---

## Setup — no account, no API key

```bash
pip install -r requirements.txt
python run.py --mock --open     # offline smoke test, proves the install works
python run.py doctor            # checks everything, says what's broken
python run.py --open            # the real thing
```

That's the whole setup. No signup, no key, no quota.

`--mock` fetches nothing at all — it generates synthetic seasons, fits the real model to them, and produces a structurally identical page. If that works, your Python install is sound. (The prices are random, so the EV and edge figures on that page are noise. Don't read them.)

`doctor` then checks each dependency separately — packages, the offline pipeline, historical results, upcoming fixtures — so "it didn't work" resolves to a specific cause rather than a guess.

The default source is football-data.co.uk's `fixtures.csv` — every upcoming fixture in your five leagues with match-result odds from six UK bookmakers (Bet365, Sky Bet, Paddy Power, BetVictor, Betfair Sportsbook, Bet&Win), plus best-available and market-average columns. It's collected Friday afternoons for the weekend, which suits a Saturday shortlist exactly.

Two bonuses from using the same source as the training data: **team names match exactly**, so the name-matching problem disappears, and you get a genuine *best available* price rather than one firm's.

**The one thing it lacks is a BTTS market.** The default run gives you win legs only.

### Optional: add BTTS

If you want BTTS legs back, that needs a free [API-Football](https://dashboard.api-football.com/register) key — email and password, or sign in with Google. No card. Key lives under Account → My Access.

```bash
export API_FOOTBALL_KEY=your_key_here
python run.py --source api --open
```

100 requests/day; a full Saturday uses about 45.

---

## Use

```bash
python run.py                    # next Saturday, no key needed
python run.py --date 2026-08-22  # a specific Saturday
python run.py --open             # open the HTML when done
python run.py doctor             # check your setup
python run.py --mock             # simulated data, fetches nothing
python run.py --source api       # adds BTTS legs (needs the free key)
python run.py verify             # check API-Football league ids (api source only)
python run.py --refresh          # re-download historical results
```

Output is `shortlist.html` — a single self-contained page, dark and light mode, fine to drop in a group chat.

**Building a slip.** Tick the box next to any pick in any of the three lists. A bar appears at the bottom with the combined price, the chance all of them win, and what £10 would return. **Copy slip** puts just your ticked picks on the clipboard as plain text, ready to paste into WhatsApp:

```
3pm Acca — Sat 22 August 2026

1. Barrow to win @ 3.33  (Swindon v Barrow)
2. Wycombe to win @ 2.71  (Wycombe v Shrewsbury)
3. Exeter to win @ 2.07  (Exeter v Burton)

3 picks @ 18.68/1 — £10 returns £186.80
We make it 26.7% that all 3 win.
```

A pick that appears in two lists ticks in both but only counts once. If you tick two picks from the *same match*, the bar warns you: those outcomes affect each other, so the combined chance shown is optimistic, and most bookmakers won't take them as an ordinary acca anyway.

**Timing matters.** `fixtures.csv` is refreshed Friday afternoons for the weekend, so a Tuesday run may find nothing for Saturday yet. `doctor` tells you which dates the file currently covers.

---

## Backtest before you trust it

```bash
python backtest.py --season 2526 --legs 6
```

Walks forward through last season, refitting the model on only what was known at the time, and reports what the safest and value accas would actually have returned at £10 a week.

**Expect a negative ROI.** Six legs means the bookmaker's margin applied six times, so a model that merely matches the market still bleeds. What you're looking for is whether one column loses meaningfully less than the other, and whether the predicted strike rate matches the actual one. If the model says 12% and reality says 4%, the model is lying to you and the shortlist is decoration.

---

## How it works

```
football-data.co.uk history CSVs  →  Dixon-Coles model  →  probabilities
                                                                ↓
football-data.co.uk fixtures.csv  →  3pm filter  →  rank  →  HTML
  (fixtures + odds, no key)                          ↑
                                                     │
API-Football (optional, free key) ───────────────────┘
  adds the BTTS market
```

**The model** gives each team an attack and a defence rating plus one global home-advantage term, fitted by maximum likelihood with exponential time decay (180-day half-life, so a result six months ago counts half as much as yesterday's). Dixon-Coles adds a correction for low-scoring games, because plain Poisson underrates 0-0 and 1-1 — exactly the scorelines that decide BTTS.

Each division is fitted **separately**. League Two is a different scoring environment from the Premier League and a shared model misprices both.

From the two expected-goals numbers you get a full scoreline matrix, and both your markets read straight off it:

```python
p_home = np.tril(m, -1).sum()   # home goals > away goals
p_away = np.triu(m,  1).sum()
p_btts = m[1:, 1:].sum()        # both scored at least one
```

One model, both markets.

**The two columns.** *Safest* ranks by raw model probability. *Value* strips the bookmaker's margin out of the price (implied probabilities are normalised to sum to 1) and ranks by expected value. They disagree most weeks; legs appearing in both are flagged.

**The sweet spot** is the lead section: legs clearing *both* bars at once — at least 55% likely to land **and** priced at least 3 percentage points above what the market implies. Ranked by expected value. Thresholds live in `config.py`.

It's an absolute filter, not an intersection of the two top-N columns. Intersecting makes the contents depend on how long the columns happen to be — a leg would drop out just because two others got added above it. Thresholds mean a leg qualifies on its own merits, and the section is honestly allowed to be **empty** in a week when nothing clears the bar. An empty sweet spot is information, not a gap.

Worth being straight about what it does and doesn't buy you. It does **not** raise return per pound — a 25% shot with an 8-point edge pays exactly the same per £1 as an 80% shot with an 8-point edge. It buys two other things:

1. **Lower variance**, which matters enormously for an acca because every leg must land. Six legs at 70% land 11.8% of the time; six at 35% land 0.2% of the time — same edge, wildly different experience.
2. **Fewer model errors.** A +200% edge on a 12.0 shot is almost never free money; it's the model being wrong about a team it has barely seen. Demanding real probability throws most of those artefacts out.

That second one is the bigger deal, and it's why the sweet spot is a better place to build an acca from than the raw value column.

---

## Things that will bite you

**The BST trap.** From late March to late October, UK clocks are on BST and 3pm local is **14:00 UTC**. Filter on UTC and you silently drop every fixture for half the season. The tool converts to `Europe/London` and compares on local time; `tests/test_pipeline.py` has a regression test for exactly this.

**Team names — only on the API source.** API-Football says "Nottingham Forest", football-data.co.uk says "Nott'm Forest". `accatool/names.py` handles this with an alias table plus fuzzy matching, and **prints anything it can't match** rather than dropping it quietly. If you see a warning, add the name to `ALIASES`. On the free source this problem doesn't exist — fixtures and history come from the same place, so the names are already identical.

**Which price you're comparing.** On the free source, the price credited to a leg is the **best available** (`MaxH/D/A`) while the edge is measured against the **market average** (`AvgH/D/A`). Two different jobs: you'd take the best price, but the average is the more stable read on what the market thinks — a Max quote is by construction the most extreme of six firms, so on any one outcome it can be a single bookmaker's error rather than a signal.

Worth being precise, because it's easy to overclaim here: de-vigged probabilities sum to 1 either way, so using Max wouldn't uniformly inflate edges — it *reshapes* them, since bookmakers don't spread margin evenly across outcomes. On realistic prices the difference is a few tenths of a point per leg and the sign varies. Small, but systematic, so it's set explicitly in `fixtures_csv.py` (`PRICE_SOURCE` / `FAIR_SOURCE`) rather than left to chance. Set `PRICE_SOURCE = "SKB"` or `"B365"` if the group all bets with one firm.

On the API source, prices are the **median** across bookmakers, and `PREFERRED_BOOKMAKER` in `config.py` narrows it to one firm.

**League One and League Two odds coverage** is thinner than the Premier League's everywhere, including here. Fixtures with no BTTS price simply won't produce a BTTS leg.

---

## Configuration

Everything adjustable is in `accatool/config.py`: the odds floor, shortlist length, which markets count, the time-decay half-life, league ids, and the preferred bookmaker.

---

## Tests

```bash
python tests/test_model.py      # parameter recovery + calibration on simulated seasons
python tests/test_pipeline.py   # full pipeline, BST handling, de-vig maths
```

`test_model.py` generates seasons from known team strengths and checks the fitter recovers them (RMSE < 0.12, correlation > 0.90) and that stated probabilities match observed frequencies. `test_pipeline.py` runs every stage end to end on synthetic history and asserts every leg obeys all four rules.

---

## Files

| | |
|---|---|
| `run.py` | entry point |
| `backtest.py` | replay last season |
| `export_ratings.py` | dump fitted ratings for the Google Sheet |
| `sheets/Code.gs` | Apps Script — the Saturday-morning job |
| `sheets/SETUP.md` | how to wire the Sheet up |
| `accatool/config.py` | all your settings |
| `accatool/data.py` | football-data.co.uk loader |
| `accatool/model.py` | Dixon-Coles fit and predict |
| `accatool/fixtures_csv.py` | free fixtures + odds, no key (default source) |
| `accatool/demo.py` | synthetic data for offline `--mock` runs |
| `accatool/odds.py` | API-Football client + mock mode |
| `accatool/names.py` | team-name matching between the two sources |
| `accatool/rank.py` | the two columns, de-vigging, acca maths |
| `accatool/report.py` | HTML output |

---

## A note on the numbers

The model's probabilities are estimates from public data, and on Premier League match-result markets they will not beat the bookmakers — that's the most efficiently priced football market there is. Whatever edge exists lives in League Two and the Scottish Premiership, where less money and less attention flow. The backtest is what tells you whether any of it is real. Treat the weekly stake as the price of the argument, not an investment.
