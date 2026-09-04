# Email-ingestion setup - closing the bot-walled gap with AUTHORIZED alerts

One-time human setup for the EMAIL-INGESTION path (`ingest_email.py`). This
closes the ONE gap the unattended fetchers cannot reach: USCIS case processing
times, the DOS Visa Bulletin release, and DOL OFLC notices all sit behind
Cloudflare / bot walls that 403 a scripted client (see `SETUP.md` "honest
boundary" and `fetch_feeds.py`). Those same agencies publish the exact same
information as AUTHORIZED email alerts via GovDelivery. A dedicated inbox
subscribed to those alerts, read over read-only IMAP, folds the official updates
into the pipeline without any scraping.

Personal-learning project. NOT legal advice, NOT official guidance.

## Honest boundary (read first)

- **Subscribing is a ONE-TIME HUMAN action.** No script can subscribe:
  GovDelivery requires clicking the signup, choosing topics, and confirming a
  double-opt-in email. `ingest_email.py` does NOT and cannot subscribe.
- **Reading is automated.** This is an authorized channel - the agency sends the
  email to an inbox that opted in. There is no scraping and no bot-bypass; the
  bot-walled pages are never touched.
- **The Visa Bulletin email is the AUTHORIZED way to get the bulletin** that the
  403-walled `travel.state.gov` bulletin page blocks. The **USCIS
  processing-time emails close the gap that has no API.**
- **IMAP is strictly read-only.** The script uses `EXAMINE` + `.fetch`, never
  `.store` flags or delete, so your inbox is left untouched - you can read it
  too. De-duplication is tracked locally in `email_seen_ledger.json` by
  Message-ID, not by mutating the mailbox.
- **Facts from email are still human-reviewed** before any `rulebook.json`
  change - the same gate as everything else (`RUNBOOK.md`).

## 1. Create (or carve out) a dedicated inbox

Create a dedicated Gmail (e.g. `yourname.gcmonitor@gmail.com`), or a dedicated
label + filter on an existing account.

Why dedicated:
- **Clean parsing.** Only GovDelivery / official-alert mail lands there, so the
  sender filter and scope classifier work on a high-signal stream instead of
  your whole inbox.
- **Credential isolation.** The IMAP app password used by this tool grants
  read access to whatever inbox it points at. A dedicated account means that
  credential can never read your personal mail. If it leaks, the blast radius is
  a public-alert inbox, not your life.

If you use a label+filter on an existing account instead, point `--mailbox` at
that label (e.g. `--mailbox "GreenCard"`), and still use a dedicated App
Password. Note the tool then still authenticates to the whole account, so the
separate-account option is the safer one.

## 2. Enable 2FA and generate a Gmail App Password; store it securely

Gmail IMAP requires an **App Password**, which requires 2-Step Verification. A
regular account password will NOT work for IMAP.

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
   (pick "Mail" / "Other"; Google shows a 16-character password once).

Store it - never hardcode it, never pass it on the CLI. The script reads it ONLY
from the `GC_IMAP_PASSWORD` environment variable.

- **macOS Keychain (recommended for the laptop):**
  ```
  security add-generic-password -s gc-imap -a <your-addr> -w <app-password>
  ```
  Then, in the shell / launchd job that runs the tool:
  ```
  export GC_IMAP_PASSWORD="$(security find-generic-password -s gc-imap -w)"
  ```
- **GitHub Actions (if you run the monitor there):** add a repository secret
  named exactly `GC_IMAP_PASSWORD` (Settings -> Secrets and variables -> Actions
  -> New repository secret), and map it into the step's `env:` exactly like
  `SLACK_WEBHOOK_URL` is mapped in `SETUP.md`. It is injected as an env var,
  never printed, never committed.

If `GC_IMAP_PASSWORD` is unset, `ingest_email.py` prints this guidance and exits
0 without connecting - it never crashes and never takes the password on the CLI.

## 3. Subscribe the inbox to the GovDelivery lists (the one-time clicks)

For each list below: open the signup, enter the dedicated inbox address, then
**pick the relevant topics** and **confirm the double-opt-in email** GovDelivery
sends to that inbox. Until you click the confirmation link, no alerts arrive.

### USCIS (the USDHSCIS GovDelivery account) - closes the processing-times gap

- Signup: `https://public.govdelivery.com/accounts/USDHSCIS/subscriber/new`
- **Verified live (2026-08-07):** the page loads and is the real USCIS/DHS
  GovDelivery signup (DHS/USCIS seal, email vs. SMS choice). GovDelivery shows
  the topic checkboxes on the step AFTER you submit your email, so the specific
  topic list is not visible on the first page.
- **Topics to check** (names vary slightly on the topic page - pick the closest):
  - **Check Case Processing Times / Processing Time updates** - this is the one
    that closes the no-API processing-times gap.
  - **Policy Alerts / Policy Manual Updates** - EB-2 NIW and H-1B
    specialty-occupation adjudication guidance.
  - **Newsroom / News Releases / All News** - H-1B cap-season announcements, fee
    rules, lottery rounds.
  - (Optional) **Forms updates** for I-140 / I-907 changes.

### DOS Visa Bulletin - NOT collected by email in this setup

There is **no usable email subscription** for the Visa Bulletin here:
- The old `register.state.gov/visabulletin/visabulletin.asp` endpoint is dead, and
  there is no State/visa `public.govdelivery.com` account (verified 2026-08-26:
  `USDOSVISAS`, `USDOSTRAVEL`, `USDOS` all 404).
- The only remaining DoS email channel is the State Department **LISTSERV**
  (`listserv@calist.state.gov`, body `Subscribe Visa-Bulletin`). It is a legacy
  listserv and is **deliberately NOT used** in this pipeline.

And `travel.state.gov` is Cloudflare bot-walled, so there is no scripted fetch of
the bulletin page. **This project does NOT bypass that protection** - we do not
use undetected-ChromeDriver / TLS-impersonation / stealth tooling to defeat a
federal site's bot wall (same honest boundary stated in `RUNBOOK.md`,
`daily-monitor.yml`, and `bulletin_pdf_fetch.py`). Public-ness of the data does
not make evading the access control OK.

So the monthly Visa Bulletin **numbers** come from `RUNBOOK.md` Step 1, not email:
- **Path B (recommended, automatable):** a Claude/WebFetch read of tier-2
  law-firm aggregators (Murthy, Fragomen, Boundless, Morgan Lewis, ...) that
  republish the bulletin the same day, requiring two to agree per value. Those
  pages are not bot-walled - no evasion. A scheduled Claude session can do this
  monthly and feed the same diff -> review -> apply -> deploy flow.
- **Path C:** a human opens the official bulletin PDF once a month in a normal
  browser (a real user legitimately passing Cloudflare - not evasion), saves it,
  and `bulletin_pdf_fetch.py --parse` turns it into the rulebook shape.

**Email's role for the bulletin is only as a TRIGGER, not the data:** the USCIS
"Immigration Policy" / "News Releases" GovDelivery topics you subscribed above
announce the monthly Adjustment-of-Status filing chart, giving an authorized
"a new bulletin is out" nudge - at which point you run Path B or Path C.

### DOL OFLC / flag.dol.gov - if a list exists

- **Verified live (2026-08-07):** `flag.dol.gov` itself exposes no dedicated
  OFLC/PERM/prevailing-wage subscribe control. The only email signup on the DOL
  site is the general DOL newsletter via GovDelivery:
  `https://public.govdelivery.com/accounts/USDOL/subscriber/new?topic_id=USDOL_167`
  (the `USDOL_167` topic id was not resolvable to a name from the signup page
  alone).
- **What to do:** subscribe to the USDOL GovDelivery account and, on the topic
  page, check any **Employment and Training Administration (ETA)** or **Office of
  Foreign Labor Certification (OFLC)** / **PERM** / **prevailing wage** topics
  if they appear. Coverage here is weaker than USCIS/DOS; the Federal Register
  API in `fetch_feeds.py` already catches DOL/ETA rule-making, so treat the DOL
  email list as a nice-to-have, not the primary DOL signal.

**Honest note:** GovDelivery topic pages are themselves JavaScript-driven and
often do not render for a plain fetch, so the exact per-account topic checkboxes
could not all be enumerated live. The signup URLs above are verified-loading
(USCIS, DOL) or best-known-canonical from official documentation (DOS Visa
Bulletin). Pick the closest-named topics when you subscribe.

## 4. Run `ingest_email.py`

Always safe to preview first (no writes, and without a password it will not even
connect):

```
python3 automation/ingest_email.py --dry-run --as news --user <addr>
```

### News mode (feeds the DAILY digest)

```
export GC_IMAP_PASSWORD="$(security find-generic-password -s gc-imap -w)"
python3 automation/ingest_email.py --as news --user <addr> --since-days 3 \
    --out automation/email_results_news.json
```

This writes an `email_results_news.json` conforming to
`news_results_schema.json`. Hand it to the mechanical core exactly like
`fetch_feeds.py` output:

```
python3 automation/news_digest.py \
    --news-results automation/email_results_news.json --date <date>
```

Because `ingest_email.py` uses the **same sha1 stable-id scheme** as
`fetch_feeds.py`, the `news_seen_ledger.json` dedups a story whether it arrived
by email or by web fetch - the same USCIS announcement won't appear twice.

### Facts mode (feeds the MONTHLY facts flow, human-gated)

```
python3 automation/ingest_email.py --as facts --user <addr> --since-days 35 \
    --out automation/email_results_facts.json
```

This emits a `fetch_results_schema.json`-shaped snapshot for the messages that
plausibly touch a rulebook fact (a Visa Bulletin release, a processing-time
update, a fee change). Every finding is deliberately `confidence: "low"` with a
`found_value: null` and the observed text in `notes` - it is a HUMAN-REVIEW
hand-off, never an auto-apply value. A human reads the notes, maps them to the
exact rulebook field, and hand-authors the real value before running
`diff_proposal.py` (see `RUNBOOK.md`). Nothing here writes `rulebook.json`.

### Where it slots into the runbooks

- **Daily (`NEWS_RUNBOOK.md`):** run `ingest_email.py --as news` alongside (or
  instead of) the Step-1 fetch when the useful signal is arriving by email, then
  continue with `news_digest.py` (Step 2) and the Slack post (Step 3). The email
  path is a second authorized source into the same Step-2 harness.
- **Monthly (`RUNBOOK.md`):** when a Visa Bulletin release or processing-time
  email lands, run `ingest_email.py --as facts` to capture the hand-off, then
  follow the existing human-gated facts flow (`diff_proposal.py` -> review ->
  `apply_proposal.py --commit` -> `deploy.sh`).

## 5. Honest boundary statement

- **You do ONCE, by hand:** create the dedicated inbox, enable 2FA, generate the
  App Password, store it, and click through each GovDelivery signup + topic
  selection + double-opt-in confirmation email. No script can do this - it is a
  human click-and-confirm.
- **Runs automatically after that:** `ingest_email.py` reads the new alert
  emails over read-only IMAP and converts them to the pipeline's JSON. The Visa
  Bulletin email is the authorized way to receive the bulletin the 403-walled
  page blocks; the USCIS processing-time emails close the gap that has no API.
- **Still human-reviewed:** any fact derived from email is reviewed by a human
  before it changes `rulebook.json`, the same gate as every other source.
