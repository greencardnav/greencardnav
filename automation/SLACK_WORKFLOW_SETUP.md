# Slack Workflow Setup - Structured "structure-in-step" digest (15 variables)

This guide builds your Slack Workflow Builder (WFB) workflow so the RICH FRAME
(bold labels, numbering, links) is TYPED INTO the workflow's message step, and
the pipeline sends only PLAIN DATA as named variables. This is the
"structure-in-step" pattern.

The variable set is deliberately capped at **15 variables** - well under WFB's
HARD 20-variable webhook cap. (An earlier design used ~29 and hit the cap.)

## Why this design (the constraint you cannot work around)

Verified by live tests against this Slack workspace:

- Only Workflow Builder `/triggers/...` webhooks are
  available (no admin approval needed). `/services/...` incoming webhooks are
  NOT available.
- Content sent as a WFB Text **variable value** is NOT parsed as mrkdwn:
  - `*bold*` renders as literal asterisks.
  - `<https://x|Label>` has its label stripped to a bare, unfurling URL.
- Therefore rich formatting CANNOT come from the pipeline. It must be TYPED into
  the "Send a message" step's composer, with only plain data injected as
  variables.

So the pipeline (`news_digest.py` -> `.news_slack_payload_<date>.txt`, POSTed by
`post_slack.py`) sends a FLAT JSON object of named string variables. The
workflow's message step supplies all the formatting.

## The 15 variables the pipeline sends (declare ALL of these)

The payload is a flat JSON object. The webhook maps each top-level key to a
workflow variable of type **Text**. Decision: show the TOP 3 items; each item
contributes 4 data fields, plus 3 overhead variables. 3 + (3 x 4) = **15**.

Declare exactly these 15 variables, all data type **Text**:

```
date
summary
digest
item1_headline
item1_source
item1_url
item1_why
item2_headline
item2_source
item2_url
item2_why
item3_headline
item3_source
item3_url
item3_why
```

What each holds:

- `date` - the run date, `YYYY-MM-DD`.
- `summary` - e.g. `3 top picks; 1 affects-facts. 92 more in the full digest.`
  (or a "no new items" sentence on an empty day). The old separate `more`
  variable is folded into this line.
- `digest` - pointer to the full markdown digest, e.g.
  `news_digests/2026-08-13.md`.
- `item{i}_headline` - the item's plain headline. When the item may change a
  rulebook fact, the string is prefixed inline with `[AFFECTS FACTS] ` (the old
  separate `item{i}_flag` variable is folded in here, so no extra variable).
- `item{i}_source` - the publisher display name (e.g. `Federal Register`).
- `item{i}_url` - the raw article URL (used by the workflow's typed hyperlink).
- `item{i}_why` - one-sentence "why it matters".

Values are plain, single-line text (newlines are collapsed). There is no mrkdwn
and no `<url|label>` link syntax in any value - the composer frame supplies all
formatting.

## Fewer-than-3-items note (read this)

The variable set is a FIXED 3 item slots. If a run has fewer than 3 new items,
the unused slots are sent as EMPTY strings (every field exists but is blank), so
the workflow variables ALWAYS exist and the webhook never errors on a missing
key. The typed frame for an empty slot renders as a blank/near-empty block. This
is acceptable - most days have 3 or more items - but be aware the message may
show empty item blocks on a light news day. (WFB's "Send a message" step has no
per-line conditional, so empty slots just render blank.)

## How the TOP 3 items are chosen (LLM judgment, with a mechanical fallback)

`news_digest.py` fills `item1..3` using `select_top_picks`:

- If any items in the fetch's `news_results.json` carry `top_pick_rank`
  (integer 1, 2, or 3), those are honored in order: rank 1 -> item1, rank 2 ->
  item2, rank 3 -> item3. Any empty slot (a gap, or a tie where two items claim
  the same rank) is filled from the mechanical `rank_sort_key` order, skipping
  items already picked.
- If NO item carries `top_pick_rank`, the harness falls back entirely to the
  mechanical top 3. Existing news-results files with no `top_pick_rank` keep
  working unchanged.

`top_pick_rank` is set by the Claude-assisted fetch session (Step 1), not by the
mechanical harness. To have the fetch name the day's top picks, add this exact
line to the daily fetch prompt:

> Additionally, mark exactly THREE items with `top_pick_rank`: 1, 2, 3 in
> decreasing order of significance for an EB-1/2/3 or H-1B applicant today - use
> real judgment, not just importance/tier.

The full markdown digest still lists EVERY new item regardless of `top_pick_rank`
- the ranking only controls which 3 items surface in the Slack message.

## Step 1 - Create the workflow from a webhook

1. In Slack, click your workspace name -> **Tools** -> **Workflow Builder**.
2. Click **New workflow**. Give it a name, e.g. `Green Card News Digest`.
3. For the trigger, choose **From a webhook**.

(If you are replacing an older workflow, create a NEW one and delete the old one
after the new one works - the old one has the wrong variables.)

## Step 2 - Set Up Variables on the webhook trigger

1. On the webhook trigger, open **Set Up Variables** (also labeled "Define
   variables sent to the workflow").
2. Add EACH of the 15 variables listed above. For every one:
   - **Key**: the exact name (e.g. `item1_headline`). Names are case-sensitive
     and must match exactly.
   - **Data type**: **Text** for all 15.
3. Save. Slack shows an example `curl` and the webhook URL - keep this URL for
   Step 4.

Tip: to make Slack auto-populate the variable list, you can paste a sample body
into the webhook setup if your Slack version supports "generate from sample".
Generate one sample body locally with:

```
python3 automation/news_digest.py --news-results automation/news_results_example.json \
  --ledger /tmp/gc_ledger.json --out /tmp/gc_digests
cat automation/.news_slack_payload_*.txt
```

(Then delete the temp files and the `.news_slack_payload_*.txt` afterward.)

## Step 3 - Type the rich frame in the "Send a message" step

Add a step: **Send a message to a channel** (choose yourself/your DM or the
channel you want). Then TYPE the following into the message composer, inserting
variables where shown. Use the composer toolbar for bold; insert a variable with
the **`{}` / Insert variable** button (shown here as `{{name}}`).

Type this layout:

1. Bold title line - turn on bold (toolbar or Cmd/Ctrl+B), type
   `Immigration News Digest - ` then insert `{{date}}`, then turn bold off.
2. New line: insert `{{summary}}`.
3. Blank line.
4. For each item 1..3, type this block (shown for item 1; repeat for 2 and 3
   with `item2_*`, `item3_*`):
   - Bold on, insert `{{item1_headline}}`, bold off. (This already includes the
     `[AFFECTS FACTS] ` prefix inline when the item may change a rulebook fact,
     so you do NOT need a separate flag variable.)
   - New line: type `Source: ` then insert the SOURCE AS A HYPERLINK - see the
     "KEY EXPERIMENT" box below.
   - New line: type `Why: ` then insert `{{item1_why}}`.
   - Blank line.
5. After the three item blocks: type `Full digest: ` then insert `{{digest}}`.

You can use the composer's numbered-list button for the item blocks if you
prefer automatic `1.`, `2.`, `3.` numbering, or just type the numbers yourself.

### KEY EXPERIMENT - a hyperlink whose TEXT and URL are both variables

For each item's Source line, try to create a hyperlink where:

- the link **text** is the `{{itemN_source}}` variable, and
- the link **URL** is the `{{itemN_url}}` variable.

To do it:

1. Type/place `{{itemN_source}}` and select it.
2. Click the composer's **link** button (or press **Cmd/Ctrl+Shift+U**).
3. In the link dialog, the **Text** field should hold the `{{itemN_source}}`
   variable. In the **URL / Link** field, try to INSERT the `{{itemN_url}}`
   variable.

**REPORT which of these happens:**

- If the URL field ACCEPTS a variable (`{{itemN_url}}`): you get clean, labeled,
  clickable links - the publisher name is the link text and the real article URL
  is the destination. This is the win. Use it for all three items.
- If the URL field REJECTS variables (only accepts a static, typed URL):
  fall back to showing just `{{itemN_source}}` as plain bold text (no link) on
  the Source line, and rely on `{{digest}}` / the full markdown digest for the
  actual links. Do NOT try to paste `{{itemN_url}}` as visible text elsewhere -
  a bare URL variable value unfurls into a preview card, which is the messy
  behavior we are avoiding.

This is the one thing that can only be determined by doing it in Slack's UI. It
is the make-or-break step for clean links; everything else is deterministic.

## Step 4 - Update the GitHub secret with the new webhook URL

Creating a new workflow issues a NEW `/triggers/...` webhook URL. The pipeline
reads the URL from the `SLACK_WEBHOOK_URL` environment variable (in CI, a GitHub
secret).

1. Copy the new webhook URL from the trigger's setup screen.
2. In the GitHub repo: **Settings -> Secrets and variables -> Actions**, edit the
   `SLACK_WEBHOOK_URL` secret and paste the new URL.
3. If you run locally, `export SLACK_WEBHOOK_URL='https://hooks.slack.com/triggers/...'`.

The URL is a secret - never commit it.

## Step 5 - Publish and test

1. Publish the workflow in Workflow Builder.
2. Test the pipeline end to end without touching production data:

   ```
   python3 automation/news_digest.py --news-results automation/news_results_example.json \
     --ledger /tmp/gc_ledger.json --out /tmp/gc_digests
   python3 automation/post_slack.py --payload automation/.news_slack_payload_*.txt --dry-run
   ```

   The `--dry-run` prints the exact JSON body that would be POSTed. Confirm it is
   a flat dict of the 15 named variables with plain-text values, and that the
   items are the ones the fetch marked with `top_pick_rank` (item1 = the fee
   rule, carrying the `[AFFECTS FACTS] ` prefix, in the example file).
3. To actually post once the workflow is live, drop `--dry-run` (with
   `SLACK_WEBHOOK_URL` set). Check the message renders with your typed frame.
4. Clean up the temp files afterward:

   ```
   rm -f automation/.news_slack_payload_*.txt
   rm -rf /tmp/gc_ledger.json /tmp/gc_digests
   ```

## Note on the dedup ledger (seeing a full 3-item test)

`news_digest.py` dedups each item against a persistent "seen" ledger, so items
already reported on a prior day are skipped and won't reappear. If you want a
test run that surfaces a full 3 items, point at a throwaway ledger (as above,
`--ledger /tmp/gc_ledger.json`) so nothing is pre-seen. You do NOT need to touch
the real `automation/news_seen_ledger.json`. (If you ever did want to reset the
real ledger, it is a one-liner - `echo '{"seen": []}' > automation/news_seen_ledger.json`
- but that is not required for testing and is not recommended casually.)
