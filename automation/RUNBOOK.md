# Freshness Runbook - green card questionnaire tool

The human-facing monthly procedure for keeping `rulebook.json` (and `rulebook.js`,
the shared data file the live multi-page site reads via `window.__RULEBOOK__`)
current. This is Aashay's personal-learning project.
NOT legal advice, NOT official guidance.

This runbook operationalizes `freshness_agent_sop.md`. Read that SOP for the
"why" behind each safety rule; this file is the "how to run it".

---

## The honest architecture (read this first)

The monthly refresh is now **automated end-to-end with NO LLM** via the
`monthly-bulletin-auto.yml` GitHub Action, within the honest no-bypass boundary.
The historical "a cron CANNOT fetch" claim was superseded on 2026-08-26: the
Cloudflare-walled `travel.state.gov` PDF is fetched from the **Internet Archive
(Wayback Machine)**, which keeps its own public capture and is not bot-walled.

- **Step 1 - FETCH (AUTOMATED, no LLM, no bypass).** `wayback_fetch.py` resolves
  the archived official bulletin PDF via the archive.org availability API and
  downloads the captured bytes. `travel.state.gov`/`uscis.gov` are NEVER fetched
  or bypassed. `bulletin_pdf_fetch.py --parse` (pdftotext + regex) reads the
  numbers deterministically, and `pdf_to_fetch_results.py` emits a tier-1
  `fetch_results` snapshot. No Claude/WebFetch required. (Legacy fallbacks if the
  capture is late: a Claude/WebFetch read of tier-2 aggregators, or a human PDF
  download — but neither is normally needed.)

- **Steps 2, 4, 5 - MECHANICAL (pure Python / bash).** `diff_proposal.py`
  categorizes; `apply_proposal.py` + `refresh_bulletin_meta.py` write
  `rulebook.json` + regenerate `rulebook.js` + advance the month metadata; a
  `git push` auto-deploys via Amplify.

- **Step 3 - APPROVAL (human, only on anomalies).** The auto workflow applies
  clean months (no cutoff movement / new-coverage fills) with ZERO human action.
  It HOLDS and Slacks for review only when `diff_proposal.py` raises a hard flag
  — which, by design, includes ANY movement of a `verified:true` cutoff cell, plus
  processing-time/fee anomalies and bad parses. So real cutoff changes always get
  a human glance; quiet months are fully hands-off.

| Step | What | Who / how |
|---|---|---|
| 1. Fetch | Get bulletin numbers | **AUTO via Wayback** (`wayback_fetch.py` -> `bulletin_pdf_fetch.py --parse` -> `pdf_to_fetch_results.py`); Claude/human fallback |
| 2. Diff | Categorize changes, write proposal | `diff_proposal.py` (automated) |
| 3. Review | Read proposal, decide | **Human only on hard-flags**; clean months auto |
| 4. Apply | Write rulebook.json/.js + month metadata | `apply_proposal.py` + `refresh_bulletin_meta.py` (auto on clean months) |
| 5. Deploy | Publish | `git push` -> AWS Amplify auto-deploy |

---

## When to run

Around the **9th-10th of the month**. The U.S. Department of State publishes the
Visa Bulletin for month N around the **9th of month N-1**. Running on the 9th/10th
catches the freshly published next-month bulletin. (The SOP's cron cadence note
suggests the 8th at 09:00 America/Los_Angeles as the quiet day to fire the
reminder; the fetch itself is done once the new bulletin is actually live.)

If the next month's bulletin is not yet published on any source, note that in the
fetch results and re-run the fetch the next day - do not fabricate a value.

---

## Step 1 - FETCH (Claude-assisted)

Start a Claude session and give it the prompt below. The output is a file named
`fetch_results_<date>.json` (e.g. `fetch_results_2026-09-10.json`) placed in the
repo root, conforming to `automation/fetch_results_schema.json`. Use
`automation/fetch_results_example.json` as a shape template.

### The exact Step-1 fetch prompt

> Fetch the latest U.S. Visa Bulletin employment-based Final Action Dates and
> Dates for Filing for EB-1, EB-2, EB-3 across India, China, ROW, Mexico, and
> Philippines, plus the DOL PERM PWD and ETA-9089 queue-position notes. Try
> tier-1 government sources first (travel.state.gov, flag.dol.gov); expect
> travel.state.gov to 403 and fall back to at least TWO tier-2 aggregators from
> sources.json (Murthy, Fragomen, Boundless, Morgan Lewis, Green Card Clock, USA
> Visa Law) and require them to AGREE before accepting a value. Do NOT fetch
> uscis-processing-times (it is auto_fetchable:false - a Cloudflare human wall);
> skip those fields. Label each finding's confidence (high = tier-1/structured,
> medium = two tier-2 agreeing, low = single source/ambiguous) and its best
> tier. Preserve `null` for UNAVAILABLE and the literal string `CURRENT`. Emit a
> JSON file conforming to automation/fetch_results_schema.json with run_date set
> to today, bulletin_month_found, and one findings[] entry per field.

Notes:
- Tier-1 confirmation is the ONLY thing that lets a `verified:false` field flip to
  `verified:true` later. Tier-2 agreement fills values but keeps the flag false.
- A single tier-2 source alone is `low` confidence and will be rejected by the
  harness - so aim for two agreeing aggregators per field.

---

## Step 2 - DIFF (automated)

From the repo root:

```
python3 automation/diff_proposal.py --fetch-results fetch_results_<date>.json --date <date>
```

This writes `freshness_proposals/<date>.md` and prints a summary:
N no_change, N expected, N unexpected (hard-flagged), N new_coverage eligible,
N rejected-low-confidence, N skipped, N apply-set changes.

The proposal contains a machine-readable ```json``` apply-set block listing exactly
the changes that passed all safety gates. That block is what Step 4 consumes.

---

## Step 3 - REVIEW (human)

Open `freshness_proposals/<date>.md` and read, in priority order:

1. **unexpected_change (HARD FLAG)** - a field that should not drift on a monthly
   cadence changed (processing time, audit rate, fee), or a value contradicts a
   `verified:true` field. Each needs written justification. Do not proceed until
   you understand each one. These are NOT in the auto-merge apply set.
2. **could-not-verify** - low-confidence rejects, auto_fetchable:false skips, and
   out-of-scope rejects. Confirm nothing important was silently dropped.
3. **verification_transition** - `verified:false -> true` flips. Confirm each was a
   genuine tier-1 confirmation.
4. **expected_change / new_coverage** - normal monthly drift and newly-filled cells.

Only proceed to apply when you accept the apply set.

---

## Step 4 - APPLY (automated; dry-run then commit)

Dry-run is the default and prints a unified diff without touching any file:

```
python3 automation/apply_proposal.py --proposal freshness_proposals/<date>.md
```

Review the printed diff. When satisfied, commit:

```
python3 automation/apply_proposal.py --proposal freshness_proposals/<date>.md --commit
```

`--commit` writes `rulebook.json` (only the apply-set fields + `meta.version`
patch bump + `meta.last_verified`), regenerates `rulebook.js` (the shared
`window.__RULEBOOK__` file every page loads; a legacy inline `index.html` block is
also re-synced if still present, otherwise skipped),
and validates both files parse. On any validation failure it restores both from
an in-memory backup and exits non-zero. It never flips a verified flag the
proposal did not authorize, and it asserts `wrong_calls_to_avoid[]` and the
`meta` source lists are byte-for-byte unchanged.

---

## Step 5 - DEPLOY (partial automation)

**Caching note (Amplify):** `customHttp.yml` at the repo root sets `Cache-Control: no-cache`
on the HTML pages and the shared assets (`app.js`, `styles.css`, `rulebook.js`, `*.json`).
Since the single-file tool was split into 5 pages sharing those assets, this makes browsers
always revalidate, so a deploy (or the daily cron commit) never leaves a visitor running a
stale `app.js`/`styles.css` against new HTML. No manual version bump needed. It only takes
effect on AWS Amplify hosting (no effect on local `file://` or other hosts).

```
bash automation/deploy.sh
```

This validates `index.html` is self-contained and its inlined JSON parses, then:
- If the Netlify CLI is installed: prints the `netlify deploy` command form.
- If not (default): prints the manual **anonymous drag-and-drop** steps
  (`https://app.netlify.com/drop`, drag `index.html`). This drag is manual - no
  script can perform a browser drop. That is the honest limitation.

A managed static-hosting path (kept in local deployment notes, not committed
here) is available as a future option; after one-time setup, updates become a
simple sync of `index.html` to the host.

---

## Automation: what can and cannot be scheduled

**Now fully scheduled (no LLM):** `.github/workflows/monthly-bulletin-auto.yml`
runs daily on the 10th-20th and does Steps 1-5 unattended for clean months —
fetch (Wayback), parse, diff, and, if there are no hard-flags, apply + deploy.
It early-exits once the month's bulletin is already reflected. This works because
the fetch source is the Internet Archive's public capture (archive.org), NOT the
Cloudflare-walled origin — no bypass, no LLM.

**Still requires a human (rare):** Step 3 review, but only when the workflow
raises a hard-flag (any `verified:true` cutoff cell moved, a processing-time/fee
anomaly, or a bad parse). In that case it Slacks you, commits the proposal, and
leaves `rulebook.json` untouched until you run `apply_proposal.py --commit`.

**Historical note:** the old claim that "a cron CANNOT fetch" (only Claude's
WebFetch could) was true until the Wayback path was added on 2026-08-26. The
`remind.sh` launchd/cron reminder below is now optional legacy — the auto
workflow supersedes it.

### Sample launchd plist (macOS)

Save as `~/Library/LaunchAgents/com.greencard.remind.plist`, then
`launchctl load` it. Fires on the 9th of each month at 09:00 local.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.greencard.remind</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>~/green_card_tool/automation/remind.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Day</key>    <integer>9</integer>
      <key>Hour</key>   <integer>9</integer>
      <key>Minute</key> <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/greencard_remind.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/greencard_remind.err</string>
  </dict>
</plist>
```

### Sample crontab line

Fires on the 9th of each month at 09:00. `crontab -e`, then:

```
0 9 9 * * /bin/bash ~/green_card_tool/automation/remind.sh >> /tmp/greencard_remind.log 2>&1
```

Either mechanism only reminds. You still run Steps 1-5 by hand / with Claude.

---

## Files in automation/

| File | Role |
|---|---|
| `fetch_results_schema.json` | JSON Schema for the Step-1 fetch output (the hand-off artifact). |
| `fetch_results_example.json` | A synthetic 5-finding template spanning every category. |
| `diff_proposal.py` | Step 2: diff fetch results vs rulebook, categorize, write proposal + apply set. |
| `apply_proposal.py` | Step 4: apply the approved apply set (dry-run default; --commit to write) → writes rulebook.json + regenerates rulebook.js (live-site data); re-syncs a legacy index.html inline block only if present. |
| `deploy.sh` | Step 5: validate self-containment + inlined JSON, then Netlify deploy guidance. |
| `remind.sh` | The cron/launchd reminder. Pure reminder - never fetches or changes anything. |
| `fetch_eb_inventory.py` | Parses the monthly USCIS pending-I-485 inventory workbook into `eb_inventory.json`. See below. |
| `RUNBOOK.md` | This file. |

---

## Monthly: refresh the pending-I-485 inventory (`eb_inventory.json`)

This feeds the "Who is already in line ahead of that date" panel in the queue
projector - a second, independent reading of the wait that counts people rather than
measuring cutoff movement.

USCIS publishes a new workbook roughly monthly. **The download is manual**, because
uscis.gov sits behind the same Cloudflare bot wall documented in
`BULLETIN_PDF_FINDINGS.md` - a scripted client gets a 403 challenge page, not the file.
This is the same human-in-the-loop shape as the Visa Bulletin PDF flow.

1. Open the cover page in a browser and download the newest employment-based
   inventory `.xlsx`:
   `https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data?topic_id%5B%5D=33682`
   (that topic filter is "Employment Based")
2. Parse it:
   ```
   automation/.venv/bin/python3 automation/fetch_eb_inventory.py \
       ~/Downloads/eb_inventory_<month>_<year>_v1.0.xlsx
   ```
   That venv holds `openpyxl`. Homebrew's Python is PEP 668 externally-managed, so a
   plain `pip install openpyxl` is refused and the dependency has to live in a venv.
   The venv is gitignored; recreate it with:
   ```
   python3 -m venv automation/.venv && automation/.venv/bin/pip install openpyxl
   ```
   A bare `python3 automation/fetch_eb_inventory.py ...` still works. The script keeps a
   stdlib fallback that reads the `.xlsx` as a zip of XML, so it runs anywhere even with
   no venv. After touching either reader, prove they still agree:
   ```
   automation/.venv/bin/python3 automation/fetch_eb_inventory.py --compare-readers <file>
   ```
   That parses with both and asserts byte-identical output; it writes nothing.
3. Sanity-check the summary it prints: `as_of` should be the new month, and the
   per-series `known` totals should move by a plausible amount rather than collapsing.
4. Commit `eb_inventory.json`.

**Two parsing traps the script already handles** - do not "simplify" them away:

- **The year columns differ per sheet.** Five sheets are labelled `Prior Years, 2017
  ... 2026`, but `India (EB2 EB3)` is labelled `Prior Years, 2006 ... 2015`, because
  Indian EB-2/EB-3 priority dates run past the workbook's 10-year window. Reading that
  sheet with the other sheets' labels misdates every Indian EB-2 record by 11 years.
  The script reads the header row per sheet.
- **`D` is a suppressed small count, not zero.** USCIS never defines it, but across the
  August 2026 file the smallest non-zero value anywhere is 11 while 1,234 cells hold
  `D` - values 1 through 10 never appear. So each `D` is a count of 1-10, and the script
  reports `known` and `suppressed_cells` separately so the UI can show a range instead
  of a fabricated point estimate.

`openpyxl` is the primary reader (in `automation/.venv`), with a stdlib zip-of-XML
fallback so the script never hard-depends on it. Both are checked against each other by
`--compare-readers`.

**The scope limit is load-bearing and is repeated in the UI:** the workbook counts only
applications *already filed*. USCIS excludes anyone holding a pending or approved I-140
who has not yet filed an I-485, the State Department consular queue, and everything
still at DOL. In a retrogressed category most of the real queue cannot file at all, so
these counts are a **floor** on the people ahead of you, never the length of the line.
Never re-word the UI to imply otherwise.
