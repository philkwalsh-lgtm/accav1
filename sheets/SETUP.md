# Google Sheets version — runs itself on Saturday morning

Your laptop can be shut. This runs on Google's servers.

**No API key required.** Fixtures and odds come from football-data.co.uk's free `fixtures.csv`, fetched directly by the script. Nothing to sign up for. The only optional upgrade is BTTS legs, which need a free API-Football key — see the last section.

## Why it works this way

Fitting the model is a 50-parameter maximum-likelihood optimisation — that needs scipy, and it isn't happening in Apps Script. But **scoring a fixture once you already have the ratings is just arithmetic**: two exponentials and an 11×11 grid. That part is trivial JavaScript.

So the work splits:

| | Where | How often |
|---|---|---|
| Fit the model → team ratings | Python, your Mac | Monthly (2 minutes) |
| Fetch fixtures + odds, score, rank, publish | Apps Script, Google's servers | Every Saturday, automatic |

The Apps Script side fetches `fixtures.csv` itself via `UrlFetchApp` and parses it with the built-in `Utilities.parseCsv()`. Because that's the same source the ratings were fitted on, team names line up exactly and no name-matching is needed.

**Ratings go stale slowly.** With a 180-day half-life, one week of results barely moves a team's attack rating. Refitting monthly is plenty — at season start and every few weeks after is fine. If you forget for six weeks, the shortlist degrades gently rather than breaking.

Both the model and the fixtures parser are cross-checked against the Python versions by `tests/test_apps_script.py`, which runs the actual `Code.gs` functions in node over identical inputs. The model agrees to **machine precision** (max difference 1.1e-15) and the parser returns byte-identical fixtures. Two implementations of the same maths is exactly where things quietly drift, so that test is worth re-running after any edit to `Code.gs`.

---

## Setup — about 15 minutes, once

### 1. Create the Sheet

New Google Sheet, name it whatever. Then **Extensions → Apps Script**.

Delete the placeholder `myFunction`, paste in all of `Code.gs`, and save.

### 2. Run `setUp()`

Back in the editor, pick `setUp` from the function dropdown and hit **Run**.

Google will ask you to authorise the script — it needs permission to fetch URLs, edit the Sheet, and send mail. Click through the "unverified app" warning (it's your own script; that warning appears for everything not published to the Marketplace).

This creates three tabs — `ratings`, `shortlist`, `log` — and a trigger for **9am every Saturday, UK time**.

### 3. Export ratings from the Python tool

On your Mac, in the `acca` folder:

```bash
python export_ratings.py --tsv --clipboard
```

Then in the Sheet, open the **`ratings`** tab, click **A1**, and paste. You should get about 120 rows — one per team, six columns.

(Without `--clipboard` it writes `ratings.csv`, which you can import instead.)

### 4. Test it

**Acca → Build shortlist now** (the menu appears after reloading the Sheet). It'll fetch this Saturday's fixtures and fill the `shortlist` tab.

### 5. Email the group (optional)

In `Code.gs`, set `EMAIL_TO` near the top:

```js
EMAIL_TO: 'you@example.com, mate1@example.com, mate2@example.com',
```

Save. Every Saturday run now emails a plain-text summary — sweet spot, safest, value, and a link back to the Sheet. Reads fine on a phone.

---

## Weekly rhythm

**Saturday 9am:** trigger fires, ~45 API requests (of your 100/day), Sheet updated, email sent. Nothing required from you.

**Monthly:** `python export_ratings.py --tsv --clipboard`, paste into the `ratings` tab. Two minutes.

**Any time:** Acca → Build shortlist now, to re-run manually.

---

## What the tabs do

**`ratings`** — the model, as a table. Attack and defence per team, plus home advantage and rho per division. You paste this; the script reads it.

**`shortlist`** — the output, rebuilt each Saturday. Sweet spot first, then safest, then value, then every qualifying leg. If any team couldn't be matched to the ratings, they're listed here too.

**`log`** — one row per run: timestamp, summary, unmatched teams, how long it took. First place to look if a Saturday goes quiet.

---

## Things that will go wrong, and what they mean

**"No ratings found"** — the `ratings` tab is empty. Run step 4.

**Unmatched teams in the shortlist tab.** API-Football says "Nottingham Forest", football-data.co.uk says "Nott'm Forest". The script tries exact match, then prefix, then token overlap — but it won't get everything, especially in League Two. Those fixtures are **skipped and reported**, never silently dropped. Fix by editing the team name in the `ratings` tab to match what API-Football calls it.

**A promoted or relegated team is missing.** Ratings only contain teams the model has seen. Re-export after the season starts and they'll appear.

**Empty sweet spot.** Not a bug. It means nothing that week is both likely and generously priced. Thresholds are `SWEET_MIN_PROB` and `SWEET_MIN_EDGE` at the top of `Code.gs` if you want a longer list.

**No 3pm fixtures.** International break, or a TV-heavy round. The log will say so.

**No fixtures listed.** The free file is refreshed Friday afternoons for the weekend. Run it on a Tuesday and the weekend may not be in there yet.

---

## Optional: adding BTTS

The free source has no both-teams-to-score market, so the default gives win legs only. To get BTTS back:

1. Free key from [dashboard.api-football.com/register](https://dashboard.api-football.com/register) — email and password, or sign in with Google. No card.
2. In the Apps Script editor: **Project Settings** (gear) → **Script Properties** → add `API_FOOTBALL_KEY` with your key. Script Properties keep the key out of the Sheet itself, so you can still share the Sheet with the group.
3. In `Code.gs`, change `SOURCE: 'free'` to `SOURCE: 'api'`.
4. Run **Acca → Verify league ids** once to confirm the five ids match what your key sees.

Quota then applies: 100 requests/day, a run uses about 45. You also inherit the team-name matching problem, since API-Football's names differ from the ratings — unmatched teams are reported in the shortlist tab.

---

## The timezone thing

The 3pm filter compares in `Europe/London`, not UTC. From late March to late October the UK is on BST and 3pm local is **14:00 UTC** — filtering on UTC would silently drop every fixture for half the season. Both the Python and Apps Script versions handle this; don't "simplify" it.
