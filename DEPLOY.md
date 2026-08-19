# Getting the live URL up

Twenty minutes, £0, and at the end you have a link you can drop in the group chat.

You'll end up with:

- **A page at `https://<your-username>.github.io/acca-shortlist/`** — open on any phone, no login, no app.
- **Saturday 3pm games**, which is what the group actually plays.
- **Rebuilt automatically** Friday evening and Saturday morning, plus a button for on-demand.
- **BTTS included**, via The Odds API's free tier.
- **Your API key encrypted** in GitHub secrets. Never in the code, never in the page, never in a chat.

> **Note on API-Football.** Don't use it. Its free plan is capped at seasons 2022–2024 and cannot see the current season at all — the run fails with *"Free plans do not have access to this season"*. Their marketing says all plans include all features, which is true of endpoints and false of seasons. Current-season access starts at $19/month. **The Odds API** has no season restriction and covers all betting markets on its free tier, so that's what this uses.

---

## Step 1 — Make the repo

1. Go to [github.com/new](https://github.com/new).
2. Name it **`acca-shortlist`**.
3. Leave it **Public**. (This is what makes GitHub Pages free. Nothing sensitive goes in here — the key lives in encrypted secrets, and the page is a list of football fixtures.)
4. Don't tick "Add a README".
5. **Create repository.**

## Step 2 — Upload the files

On the empty repo page, click **uploading an existing file**.

Drag in **everything from the unzipped `acca` folder**. Two things people miss:

- The **`.github`** folder — it holds the scheduled job. Some systems hide folders starting with a dot; if drag-and-drop skips it, make sure "show hidden files" is on (Cmd+Shift+. in Finder).
- The **`docs`** folder — that's what gets published.

Then **Commit changes**.

## Step 3 — Get a key and add it

Free key from **[the-odds-api.com](https://the-odds-api.com/)** — email address, no card. 500 credits a month. They email the key straight back.

Then in the repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

1. Name: `ODDS_API_KEY` — spelled exactly that, capitals and underscores.
2. Secret: paste the key.
3. **Add secret**.

Once saved, GitHub encrypts it. Nobody can read it back out, including you — if you lose it, regenerate on API-Football and paste the new one.

## Step 4 — Turn on Pages

1. **Settings** → **Pages**.
2. Source: **Deploy from a branch**.
3. Branch: **main**, folder: **`/docs`**.
4. **Save.**

Give it a minute, then reload — GitHub shows the live URL at the top. There'll already be a placeholder page there with mock data and a red banner saying so.

## Step 5 — First real run

1. **Actions** tab → **Build shortlist** in the left sidebar → **Run workflow** → **Run workflow**.
2. Watch it. Takes about two minutes.

**Send me the log from that first run**, especially anything under "Could not match these to the historical data". Team names differ between API-Football and the results archive, and the first run is where we find which ones need fixing.

If it goes green, refresh your Pages URL. That's the live page.

---

## Sharing it

Just send the URL. No accounts, no installs. It works on a phone, and everyone can tick their own picks and hit **Copy slip** independently — the ticking is per-person and per-device, nothing is shared or saved.

---

## Running it again

- **Automatic:** Saturday 09:00 UK. Once a week, to stay well inside the credit allowance.
- **On demand:** Actions → Build shortlist → Run workflow. Each one costs ~45 credits.

If a run finds no fixtures, it exits without writing anything and the previous page stays up. Better a slightly old page than an empty one.

---

## What it costs

| | |
|---|---|
| GitHub account, repo, Pages | £0 |
| GitHub Actions (public repo) | £0, unlimited |
| The Odds API free tier | £0 — 500 credits/month |
| **Total** | **£0/month** |

**How the credits work**, because this is the one real constraint. The Odds API charges 1 credit per league for the match-result sweep — which returns every fixture regardless of how many there are — and 1 credit per *fixture* for BTTS, from a separate endpoint.

So the tool pulls match odds for all five leagues (5 credits), throws away everything that isn't a 3pm Saturday kick-off, and *only then* spends a credit each on BTTS for the ~40 survivors. About **45 credits a run**.

Fetching BTTS before filtering would cost ~130 a run and drain the month's allowance in a fortnight. Nothing would error — the page would just stop updating. There's a test pinning that ordering for exactly this reason.

At 45 a run: the weekly scheduled build uses ~195/month, leaving ~300 spare — roughly six manual rebuilds. The tool prints your remaining balance after every run and warns when you drop below 100.

---

## Adding other days later

It's one line. In `accatool/config.py`:

```python
SLOTS = [(5, 15, 0)]                              # Saturday 3pm — current
SLOTS = [(5, 15, 0), (6, 14, 0)]                  # + Sunday 2pm
SLOTS = [(5, 15, 0), (1, 19, 45), (2, 19, 45)]    # + Tuesday and Wednesday nights
```

Each entry is `(weekday, hour, minute)` in UK time, Monday = 0. Push the change and the next run picks it up — kick-off times appear on each row automatically once more than one slot is in play, with your 3pm Saturday games highlighted.

For a one-off look at everything upcoming without touching config:

```bash
python3 run.py --source api --days 8
```

Two things to watch when you do widen it. More fixtures means more API requests — a full week is 60–75, still inside the daily 100 but with less headroom. And you may want to move the schedule, since midweek prices go up on a different day to weekend ones.

---

## Before you trust the numbers

Two things worth doing once it's live, in this order.

**1. Tune the form weighting empirically.** The model currently weights a result from six months ago at half of yesterday's. That's a sensible default, not a proven one — and it's the thing you flagged. Settle it with data rather than opinion:

```bash
python3 backtest.py --season 2526 --legs 6
python3 backtest.py --season 2526 --legs 6 --refit-every 2
```

Then try the model at different half-lives and compare which is better *calibrated* — that is, whether things it calls 60% actually happen 60% of the time:

```bash
python3 run.py --half-life 90  --days 8
python3 run.py --half-life 180 --days 8
python3 run.py --half-life 365 --days 8
```

**Expect negative ROI in the backtest.** Six legs means the bookmaker's margin applied six times over, so a model that merely matches the market still loses money. What you're looking for is which setting is *least* wrong and whether the predicted strike rate matches reality. If it claims 12% and you got 4%, the model is flattering itself and the page is decoration.

Once you know the best half-life, set `HALF_LIFE_DAYS` in `accatool/config.py`, push the change, and the live page uses it from the next run.

---

## Troubleshooting

**Actions run fails on the API key.** The secret name has to be exactly `ODDS_API_KEY`. Check for a trailing space in the pasted value.

**"Free plans do not have access to this season".** That's API-Football, not The Odds API — make sure the workflow says `--source oddsapi`.

**429 / out of credits.** You've used the month's 500. It resets on your signup date. Until then, switch the workflow to `--source free` for win-only markets at no cost.

**Page shows mock data with a red banner.** That's the placeholder from before the first real run. Trigger the workflow.

**Lots of unmatched teams.** Expected on run one, mostly in League One and Two. Send me the list and I'll extend the alias table.

**Page hasn't updated.** Actions tab shows every run and why it failed. A run that finds no fixtures deliberately changes nothing.

**Quota exceeded.** 100 requests/day. If you trigger manual runs repeatedly in one day you'll hit it — it resets at midnight UTC.
