# Freshness Agent SOP

Runbook for the agent (or Aashay running it manually) that keeps `rulebook.json` current. Personal-learning tool — not immigration advice, not official guidance.

Companion files:
- `rulebook.json` — the rulebook this agent updates.
- `sources.json` — trusted-source registry with per-field coverage.

---

## Phase 0 — Scope decision

The agent updates **only** fields whose upstream data moves on a monthly cadence.

### In scope

The agent MAY touch these `rulebook.json` paths:

- `bulletin.as_of`
- `bulletin.chart_note`
- `bulletin.categories.<EB-1|EB-2|EB-3>.<India|China|ROW>.final_action_date`
- `bulletin.categories.<EB-1|EB-2|EB-3>.<India|China|ROW>.date_for_filing`
- `bulletin.categories.<EB-1|EB-2|EB-3>.<India|China|ROW>.status_note`
- `bulletin.twelve_month_lookback_eb2_india[]`
- `i140.regular_processing_months`
- `i140.premium_processing.duration_business_days`
- `i140.premium_processing.fee_usd`
- `i485.stages[id=biometrics].duration_after_filing_months`
- `i485.stages[id=interview_and_approval].duration_after_biometrics_months`
- `i485.total_duration_months`
- `perm.total_duration_months`
- `perm.stages[id=pwd].duration_months`
- `perm.stages[id=pwd].current_queue_note`
- `perm.stages[id=pwd].as_of`
- `perm.stages[id=labor_market_test].duration_months`
- `perm.stages[id=eta9089_review].duration_months`
- `perm.stages[id=eta9089_review].current_queue_note`
- `perm.stages[id=eta9089_review].as_of`
- `perm.audit.rate_percent`
- `perm.audit.additional_duration_months`
- `wait_estimates.bands.*` — only when the underlying bulletin position moves enough to change the band; wait-band edits require explicit tier-2 citation and Phase-4 human approval.

### Out of scope — the agent MUST NOT touch these

- Anything under `meta.*` except `meta.last_verified` on approved updates.
- `meta.not_in_scope[]`, `meta.disclaimer`, `meta.primary_sources[]`, `meta.secondary_sources[]`.
- Any field citing a CFR section (`perm.cite`, `perm.priority_date_cite`, `perm_restart_triggers.triggers[].cite_regulation`, `perm_restart_triggers.triggers[].cite_regulation_h1b`, etc.).
- Any field citing INA (e.g. `strategies.cross_chargeability.cite`).
- Any field citing a case (`perm_restart_triggers.triggers[].cite_case`, `strategies.eb2_niw.cite`).
- `ac21.*` — statutory provisions do not drift monthly.
- `msa_reference.*` — Census MSA delineations are revised on a multi-year cadence and require a full-rulebook review event.
- `perm_restart_triggers.*` — regulatory triggers, not queue positions.
- `perm_restart_triggers.internal_transfer_rule` — process guidance; changes come from the maintainer, not from the freshness agent.
- `strategies.*.cite` and `strategies.*.shape` — statutory / doctrinal content.
- `wrong_calls_to_avoid[]` — permanent record of past errors. **Never overwrite. Never remove entries.** New entries are added by Aashay only.

### Verification flags — special handling

Fields marked `"verified": false` in `rulebook.json` are eligible for a **verification transition** (Phase 3) when a tier-1 source confirms the value. The agent MAY propose flipping `"verified": false` to `"verified": true` — but only when the confirming source is tier 1. Do not remove the `"verified"` key entirely; flip its value.

---

## Phase 1 — Fetch

For each in-scope field, look up its authoritative source(s) in `sources.json` via the `covers` array.

### 1.1 Fetch order

1. **Tier 1 first.** Attempt the primary source listed for the field.
2. **On failure (HTTP 403, 404, 5xx, timeout, or parse failure), fall back to tier 2.** For DOS Visa Bulletin fields specifically, `travel.state.gov` 403-blocks direct fetch is expected — go straight to tier 2 without treating tier 1 as an outage.
3. **Never trust a single tier-2 source alone.** When tier 1 is unavailable, fetch the field from at least two tier-2 aggregators listed under `covers` and require agreement.
4. **Tier 3 is never authoritative.** Do not use tier 3 in Phase 1. Tier 3 is only for Phase-2 sanity checks after a value has been extracted.

### 1.2 Logging

For every fetch attempt, log:
- `field_path`
- `source_id` (from `sources.json`)
- `url`
- `http_status`
- `fetched_at` (ISO 8601 UTC)
- `raw_excerpt` (the surrounding sentence, list item, or table row containing the value — up to ~500 chars)

Persist the log alongside the proposal (Phase 4).

### 1.3 Pass criteria

- **Pass:** at least one tier-1 fetch succeeded, OR at least two tier-2 fetches succeeded with agreement.
- **Fail:** all tier-1 attempts failed AND fewer than two tier-2 sources returned usable data. On fail, record `retry_at = fetched_at + 24h` and skip the field for this run. Do NOT emit a Phase-4 proposal for it.

---

## Phase 2 — Parse

Extract the numeric or date value from each successful fetch plus a source snippet.

### 2.1 Confidence labels

Every parse gets exactly one label:

- **`high`** — structured data (table cell, JSON field, labeled list item) with an exact value match. Example: DOS bulletin HTML table cell reading `01AUG14`.
- **`medium`** — regex over prose, likely correct but not table-structured. Example: Fragomen alert saying "The Final Action Date for EB-2 India advances to August 1, 2014."
- **`low`** — value inferred, computed, or extracted from ambiguous language. Example: "roughly 4 to 5 months" for a numeric duration.

### 2.2 Reject low-confidence

`low` parses are **rejected**. Do not propose them. Log the reject reason and move on. If a field only ever parses at `low`, that is a sign the source has changed shape — flag it in the Phase-4 proposal under `source_stale_flags`, but do not attempt to auto-fix `sources.json`.

### 2.3 Precision preservation

- If the source says "roughly 4-5 months", store the range `[4, 5]`. **Never** invent single-value precision (e.g. `4.3`) from a range.
- If the source says "typically 8-12 years", store the range. Do not average.
- If the source uses `"CURRENT"` or `"UNAVAILABLE"` / `"U"` as textual sentinels, preserve them verbatim (matching the existing rulebook convention where `null` denotes unavailable and `"CURRENT"` denotes current).

### 2.4 Pass criteria

Per-field pass: at least one `high` parse OR two `medium` parses in agreement across independent sources.

---

## Phase 3 — Diff

For each field with a passing parse, compare the new value to the current value in `rulebook.json`. Categorize.

### 3.1 Categories

- **`no_change`** — new value matches current value. Action: refresh `last_verified` timestamp on approval, nothing else.
- **`expected_change`** — the field is a bulletin date (final_action_date or date_for_filing) or a queue-position note, and it moved forward or retrogressed. Normal monthly behavior.
- **`unexpected_change`** — a field that should not have moved did. Examples:
  - An I-140 regular processing time jumped or dropped by more than 3 months in a single cycle.
  - A PERM audit rate changed.
  - A premium processing fee changed outside a known Federal Register rule cycle.
  - Anything in the "out of scope" list appears to have changed (should never happen if Phase 0 is followed; if it does, flag hard).
  Every `unexpected_change` requires a written justification in the Phase-4 proposal.
- **`verification_transition`** — a field previously carrying `"verified": false` now has a tier-1-confirmed value. Note the source and propose flipping the flag to `true`.

### 3.2 Aggregation

- `no_change` items are counted, not enumerated. A single line in the proposal: `no_change: 42 fields refreshed`.
- `expected_change`, `unexpected_change`, and `verification_transition` items are enumerated one per line with before / after / source.

### 3.3 Pass criteria

None — this phase always completes. Its output feeds Phase 4.

---

## Phase 4 — Propose

Write a diff document. **Never modify `rulebook.json` directly in this phase.**

### 4.1 File path

`~/green_card_tool/freshness_proposals/YYYY-MM-DD.md`

One proposal per run. If the file exists, append a run-timestamp suffix rather than overwriting.

### 4.2 Structure

```
# Freshness Proposal — YYYY-MM-DD

## Run metadata
- run_started_at: ISO 8601 UTC
- run_completed_at: ISO 8601 UTC
- rulebook_version: <meta.version from rulebook.json>
- sources_version: <meta.version from sources.json>

## Summary
- no_change: N fields
- expected_change: N fields
- unexpected_change: N fields (see below)
- verification_transition: N fields
- source_stale_flags: N sources (see below)
- skipped: N fields (fetch or parse failure — see below)

## Expected changes
For each: `field_path` — before: X — after: Y — source: <source_id> (<url>) — snippet: "..."

## Unexpected changes
For each: `field_path` — before: X — after: Y — source: <source_id> (<url>) — snippet: "..." — justification required: <why the agent believes this is real, not a parse artifact>

## Verification transitions
For each: `field_path` — before: `"verified": false`, value: X — after: `"verified": true`, value: Y — confirming source: <tier-1 source_id> (<url>)

## Source stale flags
For each source where the agent could not parse a fetched page (repeated `low` confidence, HTML shape change, 404): source_id — url — symptom.

## Skipped
For each field that failed Phase 1 fetch or Phase 2 parse: field_path — reason — retry_at.

## Fetch log
Full Phase-1 log (field_path, source_id, http_status, fetched_at, raw_excerpt).
```

### 4.3 Pass criteria

Proposal file written and readable. Agent halts here awaiting human approval.

---

## Phase 5 — Approve and apply

Human reviews the proposal. Only on **explicit approval** does the agent write to `rulebook.json`.

### 5.1 Approval semantics

- Approval is per-run (approve the whole proposal) or per-field (approve some, reject others). The agent supports both via an approval file the human writes at `freshness_proposals/YYYY-MM-DD.approved.md` listing approved field paths, OR a plain "approve all" instruction from Aashay in-session.
- Rejected fields are not applied. They remain unchanged in `rulebook.json`. The proposal file remains on disk as the audit trail.

### 5.2 Apply rules

For each approved change:

1. Write the new value to the field.
2. Update the field's parent record — or a nearby `last_verified` marker — with today's date. Where the schema does not carry a per-field timestamp, update the containing section's status_note or the top-level `meta.last_verified` on the final apply step.
3. On `verification_transition`, flip `"verified": false` to `"verified": true`. Do not remove the `"verified"` key.
4. Update `meta.last_verified` on the top of `rulebook.json` to today's date once all approved changes are applied.
5. If the approval covers a change to a bulletin category, also append an entry to `bulletin.twelve_month_lookback_eb2_india[]` if the change is for EB-2 India (and prune entries older than 12 months to keep the array bounded).

### 5.3 Post-apply invariants

- `wrong_calls_to_avoid[]` is byte-for-byte identical to its pre-run state.
- `meta.not_in_scope[]`, `meta.primary_sources[]`, `meta.secondary_sources[]` are unchanged.
- Every `"verified": false` flag not touched by a verification transition remains `false`.
- No CFR / INA / case citation string was modified.

### 5.4 Pass criteria

`git diff rulebook.json` shows only approved-field changes plus the `meta.last_verified` bump. If any invariant above is violated, revert the apply and file a hard flag for human review.

---

## Cadence

- **Monthly, the 8th of each month at 09:00 America/Los_Angeles.** DOS releases the Visa Bulletin for month N around the 9th of month N-1, so the 8th is the last quiet day; running then catches the prior month's release cycle without racing the new one.
- **Ad-hoc trigger:** "check field X" — refresh a single field on demand. Runs Phases 1-4 for that field only; still requires human approval before apply.

---

## Safety rails and hard rules

- **Never fully automatic.** Every write to `rulebook.json` gates on human approval. The agent proposes; the human disposes.
- **Never trust tier 3 as primary.** Tier 3 is sanity-check only. Never author a rulebook change from a tier-3 source.
- **Never invent precision.** Ranges stay ranges. "Roughly N" stays a range or gets rejected as `low` confidence. Never fabricate a decimal.
- **`wrong_calls_to_avoid` is permanent.** Never edit, never remove, never reorder. New entries are added by Aashay only.
- **`"verified": false` flags are conservative.** Only flip to `true` when a tier-1 source confirms. A tier-2 confirmation is not sufficient.
- **`sources.json` is human-maintained.** If a source URL 404s, the site redesigns, or parsing repeatedly fails, the agent flags it under `source_stale_flags` in the proposal. It does NOT attempt to auto-fix `sources.json`.
- **Every claim carries a citation.** Every proposed change references the source_id, URL, and raw snippet. No exceptions.

---

## Failure modes

- **DOS `travel.state.gov` returns 403.** Expected. Fall back to tier-2 aggregators and require agreement across at least two. Log the 403 in the fetch log but do not treat as an incident.
- **Aggregators have not yet published the new bulletin.** Fewer than two tier-2 sources have month N's bulletin. Skip the affected fields, log `retry_at = now + 24h`, and re-run those fields the next day. Do not partially update.
- **Bulletin format has changed** (new column, renamed category, restructured table). Parsing fails for multiple fields with `low` confidence. Agent stops touching bulletin fields, files a "manual review needed" note in the proposal under `source_stale_flags`, and does not guess. Aashay resolves.
- **Two tier-2 aggregators disagree** on a value when tier 1 is unavailable. Categorize as `unexpected_change` requiring human resolution. Include both values and both sources in the proposal.
- **A field that should be static (e.g. an AC21 provision, a CFR citation) appears to have changed.** Treat as an `unexpected_change` requiring hard justification. The agent may have crossed a scope boundary — check Phase 0 exclusions before proposing anything.
- **Source URL 404.** Log under `source_stale_flags`. Do NOT modify `sources.json`. Aashay updates the registry.

---

## Open questions the agent MUST NOT decide on its own

- Whether to add a new source to `sources.json`.
- Whether to add a new field to `rulebook.json`.
- Whether to remove a `"verified": false` flag using tier-2 evidence alone.
- Whether to accept a low-confidence parse "just this once."
- Whether a wait-band estimate should shift in response to a single monthly retrogression.

All of the above route to Aashay.
