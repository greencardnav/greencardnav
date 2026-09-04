# Setup - unattended daily monitor + monthly facts assist

One-time human setup to turn the green card news/facts monitor into a genuinely
self-running daily job. Personal-learning project. NOT legal advice, NOT official
guidance.

This covers the UNATTENDED layer added on top of the existing tool:

- `automation/fetch_feeds.py` - unattended DAILY news fetcher (authorized feeds only).
- `automation/news_digest.py` - the existing mechanical core (dedup, rank, digest, Slack payload).
- `automation/post_slack.py` - posts the digest payload to a Slack incoming webhook.
- `.github/workflows/daily-monitor.yml` - the always-on scheduler (GitHub Actions).
- `automation/fetch_bulletin.py` - MONTHLY bulletin FACTS snapshot for human review (3-source quorum: two public-domain community mirrors + the Internet Archive of the official page).
- `automation/USCIS_PROCESSING_TIMES.md` - documents the LEGITIMATE OAuth path for USCIS processing times, and why that field is intentionally not automated.

## Honest boundary (read first)

The daily job fetches ONLY feeds that answer a plain stdlib client with HTTP 200:
the Federal Register API v1 (public JSON, no auth), law-firm / community / DOL
RSS, Google News RSS, and a best-effort read of flag.dol.gov. It NEVER scrapes
the bot-walled official pages (travel.state.gov, egov.uscis.gov processing-times,
USCIS newsroom RSS) - those 403 a scripted client, and bypassing bot protection
is out of bounds. The descriptive User-Agent the fetchers send is normal client
courtesy, not evasion.

The MONTHLY bulletin FACTS still require a human. `fetch_bulletin.py` triangulates
across THREE legitimate sources (two public-domain community mirrors -
mixseomin/visa-bulletin-history and DavidBellamy/visa_dates - plus the Internet
Archive's copy of the official travel.state.gov page) and trusts a value only on
quorum. It is still just an eyeball assist: the numbers the tool actually serves
change only through the human-gated flow in `RUNBOOK.md` (`diff_proposal.py` ->
`apply_proposal.py` -> `deploy.sh`). No live official machine-readable feed exists,
so this quorum is the legitimate automated approximation - not an official source.

USCIS processing times are a separate, non-automated field (OAuth-gated official
API - see `automation/USCIS_PROCESSING_TIMES.md`). `fetch_bulletin.py` does not
touch them.

---

## 1. Create a GitHub repo and push the tool

The tool is already de-identified, so it is fine to push. The ONLY thing you must
never commit is a real Slack webhook URL (it is a secret - see step 2).

1. Create a repo (private is fine). Note: private repos get a monthly pool of free
   Actions minutes; a once-a-day job uses a tiny fraction of it. Public repos get
   unlimited Actions minutes.
2. Push at least `automation/` and `.github/workflows/` (pushing the whole
   `green_card_tool/` is fine):
   ```
   cd ~/green_card_tool
   git init            # if not already a repo
   git add automation/ .github/ rulebook.json sources.json index.html
   git commit -m "green card monitor: unattended daily layer"
   git branch -M main
   git remote add origin git@github.com:<you>/<repo>.git
   git push -u origin main
   ```
3. Do NOT commit: any real `SLACK_WEBHOOK_URL`, or a populated
   `automation/news_seen_ledger.json` from testing (keep it `{"seen": []}` until
   the first real run). Test artifacts (`/tmp/...`) never belong in the repo.

## 2. Create a Slack incoming webhook and store it as a repo secret

1. Create a Slack incoming webhook for the channel (or your self-DM) you want the
   digest posted to. Slack's guide:
   https://api.slack.com/messaging/webhooks
   (Create a Slack app -> Incoming Webhooks -> Activate -> Add New Webhook to
   Workspace -> copy the `https://hooks.slack.com/services/...` URL.)
2. In the GitHub repo: Settings -> Secrets and variables -> Actions -> New
   repository secret. Name it exactly `SLACK_WEBHOOK_URL` and paste the URL.
3. That secret is injected into the workflow's Slack step as an env var. It is
   never printed and never committed. If it is unset, `post_slack.py` simply
   prints the payload and exits 0 (graceful degradation) - the run still succeeds.

## 3. Enable Actions, confirm the schedule, run it manually once

1. Repo -> Actions tab -> enable workflows if prompted.
2. The `daily-monitor` workflow runs on `schedule: cron '0 14 * * *'` = 14:00 UTC
   daily (~06:00 PT in summer / ~07:00 PT in winter - GitHub cron is UTC and does
   not follow DST). Edit the cron in `.github/workflows/daily-monitor.yml` if you
   want a different local time.
3. Trigger a manual run to verify end-to-end: Actions -> daily-monitor -> "Run
   workflow" (this uses the `workflow_dispatch` trigger). Watch the three steps
   (fetch -> digest -> post) and the commit-back step.

### How persistence works (and why commit-back)

The workflow commits `automation/news_seen_ledger.json` and `news_digests/` back
to the repo after each run. We chose commit-back over `actions/cache` on purpose:

- It is DURABLE - a cache can silently evict, and if the ledger is lost the same
  stories re-surface as "new".
- It gives a VISIBLE, auditable history - every day's digest lands in the repo.

This needs `permissions: contents: write` (already set, least-privilege - it is
the only permission granted). If you would rather grant no write access, replace
the "Commit ledger + digests back" step with an `actions/cache` step keyed on the
ledger path and set `permissions: contents: read` - but you then lose the visible
digest history.

## 4. Monthly facts routine (human-gated - the tool's data)

Once a month (around the 9th-10th, when the new Visa Bulletin publishes):

1. Run the snapshot assist (optionally pin the month with `--month YYYY-MM`):
   ```
   python3 automation/fetch_bulletin.py --out automation/bulletin_snapshot.json
   ```
2. Eyeball `bulletin_snapshot.json`:
   - `source_status` - which of the 3 sources answered (ok / stale / unavailable /
     rate-limited). DavidBellamy is frequently STALE and archive.org frequently 429s;
     either failing is expected and does not fail the run.
   - `quorum[]` - per (category, country, chart) cell with confidence (high =
     >=2 sources agree, medium = single-source, low = disagreement with all values kept).
   - `rulebook_discrepancies[]` - every cell where the quorum differs from the current
     `rulebook.json`, for your review.
   Remember: these are unofficial mirrors + a lagged official-archive backstop, trusted
   only on quorum - verify anything that matters against travel.state.gov before
   trusting it.
3. If the numbers hold up, follow the existing human-gated flow in `RUNBOOK.md`:
   hand-author a `fetch_results_<date>.json` (or use the Claude-assisted Step-1
   fetch), then `diff_proposal.py` -> review -> `apply_proposal.py --commit` ->
   `deploy.sh`. That is the ONLY path that writes `rulebook.json`.
4. Cross-reference `RUNBOOK.md` for the full monthly procedure and safety gates.

`fetch_bulletin.py` never writes `rulebook.json` and is not auto-apply-eligible.

## 5. Optional residual-killer: GovDelivery email subscriptions

The bot-walled official sources we cannot fetch (USCIS processing times, the DOS
visa bulletin release, DOL notices) all offer EMAIL updates via GovDelivery. A
dedicated Gmail subscribed to these closes that gap without scraping:

- USCIS: https://public.govdelivery.com/accounts/USDHSCIS/subscriber/new
- Visa Bulletin: travel.state.gov "Get Updates" / email subscription for the
  Visa Bulletin.
- DOL: subscribe to the relevant OFLC / DOL update lists.

FUTURE (not built yet): an IMAP step could poll that Gmail and fold the official
email alerts into the daily news-results JSON - closing the USCIS-processing-times
gap through an authorized channel. Flagging this as a documented next step, not a
current capability.

## 6. launchd fallback (laptop-only, no GitHub)

If you would rather not use GitHub Actions, the existing `news_remind.sh` +
launchd plist (see `NEWS_RUNBOOK.md`) can fire a local daily REMINDER, and you
could wire a local launchd job to run `fetch_feeds.py` -> `news_digest.py` ->
`post_slack.py` on your Mac.

GitHub Actions is RECOMMENDED over launchd, because launchd only fires when the
Mac is awake - it silently misses any day the laptop is off or asleep, so the
daily monitor would have gaps. Actions runs in the cloud every day regardless.
