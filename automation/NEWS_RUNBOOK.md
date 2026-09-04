# News Runbook - green card tool DAILY immigration-news layer

The human-facing DAILY procedure for monitoring immigration NEWS (EB-1, EB-2,
EB-3, and H-1B only) and turning it into a dated digest plus a Slack DM. This is
Aashay's personal-learning project. NOT legal advice, NOT official guidance.

This is the DAILY news stream. It is SEPARATE from the MONTHLY facts refresh.

- **Daily (this runbook):** monitor news - policy shifts, rule-making, litigation,
  H-1B lottery/cap cycles, RFE and processing trends. Output: a dated digest and a
  Slack payload. Does NOT write `rulebook.json`.
- **Monthly (see `automation/RUNBOOK.md`):** refresh the bulletin FACTS in
  `rulebook.json`. That is the only path that changes the data the tool serves.

The bridge between them: when a daily news item is `affects_facts:true` (a new
Visa Bulletin, a fee change, a new final rule), the digest flags it at the top.
That flag is your cue to run the monthly facts flow (Step 4 below).

Read `freshness_agent_sop.md` for the SOP philosophy this layer inherits: fetch
tier-1 first, fall back to two agreeing tier-2 sources, label confidence, human
approves any fact change, never fabricate.

---

## The honest architecture (read this first)

The daily news scan has the SAME hard boundary as the monthly facts harness:

- **Step 1 - FETCH (Claude-assisted, NOT pure-cron).** USCIS Newsroom, DOS visa
  news, DOL OFLC, and the Federal Register are **Cloudflare-walled or
  rate-limited** to scripts and headless browsers. Even the reliably-fetchable
  law-firm practitioner sites need a real fetch tool. The only path that works is
  **Claude's WebFetch tool**, and a bare cron has no access to it. So **a cron
  CANNOT do this step.** A human or a scheduled Claude session gathers the news
  and writes a `news_results_<date>.json` file.

- **Step 2 - DIGEST (pure Python stdlib).** Given the news-results JSON,
  `news_digest.py` dedups every item against a persistent ledger (so the same
  story is never re-surfaced), ranks the new items, writes a dated markdown
  digest, and emits a Slack payload file. Fully automatable.

- **Step 3 - NOTIFY (Claude-assisted).** Post the generated Slack payload to your
  self-DM. Python has no Slack creds, so a Claude session (with the Slack MCP)
  does the actual post.

- **Step 4 - HANDOFF (human + monthly flow).** If any item is `affects_facts:true`,
  run the MONTHLY facts flow to update the rulebook after human approval.

So: **a scheduled job can only REMIND** (see `news_remind.sh`). It fires a daily
notification that the scan is due and opens this runbook. It does not - and
honestly cannot - fetch or change anything unattended.

| Step | What | Who / how | Automation |
|---|---|---|---|
| 1. Fetch | Gather in-scope news into a JSON | Claude session (WebFetch) or Aashay - NOT cron | needs Claude |
| 2. Digest | Dedup, rank, write digest + Slack payload | `news_digest.py` | pure Python |
| 3. Notify | Post the Slack payload to self-DM | Claude session (Slack MCP) - NOT Python | needs Claude |
| 4. Handoff | If affects_facts, refresh the rulebook | `automation/RUNBOOK.md` -> `diff_proposal.py` | needs human approval |
| (reading + approving any fact change) | Judgment | Human | needs human |

---

## When to run

Daily. News (especially H-1B cap-season announcements, Federal Register rules, and
litigation) can land any day, so run it once a day. Contrast with the monthly
facts refresh, which runs around the 9th-10th of the month to catch the freshly
published Visa Bulletin (see `automation/RUNBOOK.md`).

If it is a quiet news day and there is nothing in scope, that is fine - the fetch
produces an empty `items[]` and the digest says "no new items today." Never
fabricate news to fill the digest.

---

## Step 1 - FETCH (Claude-assisted)

Start a Claude session and give it the prompt below. The output is a file named
`news_results_<date>.json` (e.g. `news_results_2026-08-07.json`) placed in the
repo root, conforming to `automation/news_results_schema.json`. Use
`automation/news_results_example.json` as a shape template.

### The exact Step-1 fetch prompt

> Scan for U.S. immigration NEWS from the last 1 day in scope EB-1, EB-2, EB-3,
> and H-1B ONLY (H-1B cap, lottery, extensions, RFEs, portability). Do NOT include
> EB-4/EB-5, family-based, asylum, or enforcement news - out of scope. Try tier-1
> official sources first from news_sources.json (USCIS Newsroom, DOS visa news,
> DOL OFLC, Federal Register USCIS/DHS, USCIS Policy Manual updates); expect most
> to 403 (Cloudflare/bot walls) and fall back to at least TWO tier-2 practitioner
> sources (AILA, Fragomen, BAL, Murthy, Boundless, Morgan Lewis, NAFSA) and require
> them to AGREE before treating an item as confirmed. Tier-3 (Forbes/NFAP,
> Immigration Impact, Reddit) is sanity-check only, never authoritative. For every
> item require a real source and a published_date - no unsourced claims. Assign
> each item a stable id (source_id + published_date + short-topic-slug). Set
> affects_facts:true when the item indicates a rulebook fact changed (a new Visa
> Bulletin, a fee change, a new final/proposed rule, a processing-time shift).
> Label importance (high/medium/low), confidence (high = tier-1 or two tier-2
> agreeing; medium = single tier-2; low = tier-3/unconfirmed), and best tier
> (1/2/3). Emit a JSON file conforming to automation/news_results_schema.json with
> run_date set to today and one items[] entry per distinct in-scope story. If it
> is a quiet day, emit an empty items[] - do NOT fabricate news.

Single-sentence version:

> Fetch today's U.S. immigration news for EB-1/EB-2/EB-3/H-1B only, tier-1 first
> then two agreeing tier-2 practitioner sources per news_sources.json, one sourced
> and dated items[] entry per story with id, category, topic, importance,
> confidence, tier, and affects_facts, conforming to news_results_schema.json -
> and never fabricate on a quiet day.

Notes:
- Tier-1 confirmation makes an item high-confidence; two agreeing tier-2 sources
  also count as high; a single tier-2 source is medium; tier-3/community is low.
- `affects_facts:true` is the trigger for the monthly facts flow (Step 4). Be
  conservative: set it only when a rulebook FACT (bulletin date, fee, rule)
  plausibly changed, not for general commentary.

---

## Step 2 - DIGEST (automated)

From the repo root:

```
python3 automation/news_digest.py --news-results news_results_<date>.json --date <date>
```

This writes `news_digests/<date>.md` and `automation/.news_slack_payload_<date>.txt`,
updates the persistent seen-ledger (`automation/news_seen_ledger.json`), and
prints a summary: N new, N deduped-as-seen, N affects_facts, the digest path, and
the Slack payload path.

The ledger is what prevents the SAME story from being re-reported day over day: an
item is NEW only if its id (or a hash of source_id + headline + published_date) is
not already in the ledger. Only new items appear in today's digest; their ids are
added to the ledger after the digest is written.

Ranking of new items: importance (high > medium > low), then affects_facts first
within a tier, then tier (1 > 2 > 3), then topic (rule-making/policy above
commentary). Any `affects_facts:true` items also get a dedicated callout at the
TOP of the digest.

If there are zero new items, the digest is a minimal "no new items today" file and
the Slack payload is a one-liner saying so. Nothing is fabricated.

**This step is pure Python** - no network, no Slack creds, fully automatable. It is
the only fully-automated step in the daily flow.

---

## Step 3 - NOTIFY (Claude-assisted; Python cannot post to Slack)

`news_digest.py` wrote a ready-to-send payload to
`automation/.news_slack_payload_<date>.txt` (plain text, mrkdwn-safe, no emojis).
Python has no Slack credentials, so posting is a Claude step:

1. Read `automation/.news_slack_payload_<date>.txt`.
2. In a Claude session with the Slack MCP, post its contents to your self-DM
   (open a DM to yourself, then post the message).
3. The payload already links back to the full digest file (`news_digests/<date>.md`).

Do NOT try to post from Python - it has no creds and the script intentionally does
not attempt it.

---

## Step 4 - HANDOFF to the monthly facts flow (only if affects_facts)

If the digest's "AFFECTS FACTS" callout lists any items - or the stdout summary
shows `affects_facts > 0` - a rulebook fact may have changed (a new Visa Bulletin,
a fee change, a new rule). This is the bridge to the MONTHLY facts layer:

1. Open `automation/RUNBOOK.md` (the monthly facts runbook).
2. Run its Step 1 fetch (bulletin numbers) and Step 2 `diff_proposal.py`.
3. Review the proposal and, on approval, `apply_proposal.py --commit` +
   `deploy.sh`.

The daily news layer never writes `rulebook.json` itself. It only tells you WHEN
to run the monthly flow that does.

---

## Automation: what can and cannot be scheduled

**Can be scheduled:** a REMINDER. `news_remind.sh` prints (and, on macOS,
notifies) that the daily scan is due and points at this runbook. It never fetches
or changes data - that is the honest "cron part".

**Cannot be scheduled:** Step 1 (fetch) unattended, because Cloudflare / bot walls
block scripted and headless access to the official sources, and even the
practitioner sites need Claude's WebFetch. So the reminder tells a human/Claude to
run Step 1; it does not do it. Step 3 (Slack post) also needs Claude (no creds in
Python).

### Sample launchd plist (macOS)

Save as `~/Library/LaunchAgents/com.greencard.newsremind.plist`, then
`launchctl load` it. Fires DAILY at 09:00 local.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.greencard.newsremind</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>~/green_card_tool/automation/news_remind.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>   <integer>9</integer>
      <key>Minute</key> <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/greencard_newsremind.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/greencard_newsremind.err</string>
  </dict>
</plist>
```

### Sample crontab line

Fires daily at 09:00. `crontab -e`, then:

```
0 9 * * * /bin/bash ~/green_card_tool/automation/news_remind.sh >> /tmp/greencard_newsremind.log 2>&1
```

Either mechanism only reminds. You still run Steps 1-4 by hand / with Claude.

---

## Files in automation/ (news layer)

| File | Role |
|---|---|
| `news_sources.json` | Tiered trusted-source registry for NEWS (separate from bulletin-data sources.json). |
| `news_results_schema.json` | JSON Schema for the Step-1 news fetch output (the hand-off artifact). |
| `news_results_example.json` | A synthetic ~6-item template spanning every category, an affects_facts item, and a duplicate (dedup demo). |
| `news_digest.py` | Step 2: dedup vs ledger, rank, write dated digest + Slack payload. Pure Python. |
| `news_seen_ledger.json` | The persistent seen-ledger (created/updated by news_digest.py). Prevents re-reporting the same story. |
| `news_remind.sh` | The daily cron/launchd reminder. Pure reminder - never fetches or changes anything. |
| `NEWS_RUNBOOK.md` | This file. |
