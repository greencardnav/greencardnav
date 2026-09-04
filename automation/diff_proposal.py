#!/usr/bin/env python3
"""
diff_proposal.py - the MECHANICAL half of the green card tool's monthly freshness workflow.

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
The monthly data-freshness workflow has two halves with an HONEST, hard boundary:

  1. THE FETCH STEP (Claude-assisted, NOT pure-cron).
     travel.state.gov and uscis.gov are Cloudflare-walled: they 403 both plain
     scripts AND headless browsers. The only working path is Claude's WebFetch
     tool against tier-2 law-firm aggregators, and a cron has no access to that.
     So a human/Claude session gathers the numbers and writes a fetch-results
     JSON conforming to fetch_results_schema.json. A cron CANNOT do this.

  2. THE MECHANICAL STEPS (pure Python stdlib, fully automatable) - THIS SCRIPT.
     It CONSUMES the fetch-results JSON. It never scrapes anything. It diffs the
     findings against rulebook.json, enforces the SOP safety rules in code,
     categorizes every change, and writes a dated markdown proposal plus a
     machine-readable "apply set" that apply_proposal.py later consumes.

This script NEVER writes rulebook.json. It only proposes. Human approval + a
separate apply step (apply_proposal.py --commit) are required to change data.

SAFETY RULES ENFORCED IN CODE (from freshness_agent_sop.md):
  - confidence:low findings are rejected from the auto-merge set (could-not-verify).
  - verified:false -> true is only proposed when the confirming finding is tier 1.
  - fields whose source is auto_fetchable:false (uscis-processing-times) are skipped.
  - out-of-scope subtrees (meta.*, wrong_calls_to_avoid, ac21.*, msa_reference.*,
    perm_restart_triggers.*, strategies.*, CFR/INA/case cites)
    are never proposed for change.

Usage:
  python3 diff_proposal.py --fetch-results <path> [--rulebook <path>]
                           [--sources <path>] [--out <proposals_dir>]
                           [--date YYYY-MM-DD]

stdlib only: json, datetime, pathlib, argparse, sys, re
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# ---------------------------------------------------------------------------
# Out-of-scope subtrees. Any finding whose field_path falls under one of these
# is rejected outright - the freshness agent must never touch these (SOP Phase 0).
# meta.last_verified is set automatically on apply, never proposed by a finding.
# ---------------------------------------------------------------------------
OUT_OF_SCOPE_PREFIXES = (
    "meta.",
    "wrong_calls_to_avoid",
    "ac21.",
    "msa_reference.",
    "perm_restart_triggers.",
    "strategies.",
    "locations.",
    "i485.eligibility_rule",
    "perm.priority_date_rule",
    "perm.qualifying_experience_rule",
)
# Any field_path containing a citation-ish segment is out of scope (CFR / INA / case).
CITE_SEGMENT_RE = re.compile(r"(^|\.)(cite|cite_case|cite_regulation|cite_regulation_h1b|"
                             r"priority_date_cite|shape)(\.|$)")

# Path segments that make a change "expected" (normal monthly drift) when it moves.
EXPECTED_LEAF_FIELDS = {"final_action_date", "date_for_filing",
                        "current_queue_note", "status_note", "as_of",
                        "chart_note"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_path(obj, dotted):
    """Return (exists, value) for a dot path into a nested dict. Keys may
    contain hyphens (e.g. 'EB-2'). Only dict traversal is supported; that
    matches every in-scope field_path (array fields are handled separately)."""
    cur = obj
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return (False, None)
    return (True, cur)


def parent_path(dotted):
    """The dotted path of the parent object, or None if top-level."""
    if "." not in dotted:
        return None
    return dotted.rsplit(".", 1)[0]


def get_parent_verified(rulebook, dotted):
    """If the finding's PARENT record carries a 'verified' flag, return its
    boolean value; else return None (no flag present)."""
    pp = parent_path(dotted)
    if pp is None:
        return None
    exists, parent = get_path(rulebook, pp)
    if exists and isinstance(parent, dict) and "verified" in parent:
        return bool(parent["verified"])
    return None


def build_auto_fetchable_false_set(sources):
    """Collect the exact set of field paths covered by any source marked
    auto_fetchable:false. Those fields are HUMAN-ONLY (SOP): the harness must
    never propose a change to them - it links the user out instead."""
    protected = set()
    tiers = sources.get("tiers", {})
    for tier_list in tiers.values():
        for src in tier_list:
            if src.get("auto_fetchable") is False:
                for cov in src.get("covers", []):
                    protected.add(cov)
    return protected


def is_out_of_scope(field_path):
    if any(field_path.startswith(p) for p in OUT_OF_SCOPE_PREFIXES):
        return True
    if CITE_SEGMENT_RE.search(field_path):
        return True
    return False


def is_expected_field(field_path):
    leaf = field_path.rsplit(".", 1)[-1]
    if leaf in EXPECTED_LEAF_FIELDS:
        return True
    if field_path == "bulletin.as_of":
        return True
    return False


def values_equal(a, b):
    """Compare a found value to a rulebook value. Lists compared element-wise;
    everything else by ==. null == null is True."""
    if isinstance(a, list) and isinstance(b, list):
        return a == b
    return a == b


def categorize(rulebook, protected_paths, finding):
    """Return a dict describing the finding's disposition.

    disposition keys:
      category    - one of: no_change, expected_change, unexpected_change,
                    verification_transition, new_coverage
      status      - one of: eligible, rejected, skipped
      eligible    - bool (goes into the apply set)
      flip_verified - bool (verification_transition only)
      reason      - human-readable note
      current_value / found_value
    """
    fp = finding["field_path"]
    found = finding.get("found_value")
    conf = finding.get("confidence")
    tier = finding.get("tier")

    base = {
        "field_path": fp,
        "found_value": found,
        "confidence": conf,
        "tier": tier,
        "sources": finding.get("sources", []),
        "notes": finding.get("notes", ""),
        "current_value": None,
        "category": None,
        "status": "eligible",
        "eligible": False,
        "flip_verified": False,
        "reason": "",
    }

    # 1. Out-of-scope guard (never touch these subtrees).
    if is_out_of_scope(fp):
        base["status"] = "rejected"
        base["category"] = "out_of_scope"
        base["reason"] = ("Field is in an out-of-scope subtree (meta / citations / "
                          "statutory / process rules). The freshness agent must not touch it.")
        return base

    # 2. auto_fetchable:false guard (human-only sources, e.g. uscis-processing-times).
    if fp in protected_paths:
        base["status"] = "skipped"
        base["category"] = "auto_fetchable_false"
        base["reason"] = ("Source is marked auto_fetchable:false (Cloudflare human-verification "
                          "wall). Skipped by design - the tool links the user out to the live page.")
        return base

    exists, current = get_path(rulebook, fp)
    base["current_value"] = current

    # 3. Low-confidence guard (SOP 2.2: reject, list under could-not-verify).
    if conf == "low":
        base["status"] = "rejected"
        base["category"] = "low_confidence"
        base["reason"] = ("Low confidence (single tier-2 source or ambiguous parse). "
                          "Rejected from auto-merge per SOP 2.2.")
        return base

    parent_verified = get_parent_verified(rulebook, fp)

    # 4. no_change.
    if exists and values_equal(found, current):
        base["category"] = "no_change"
        base["status"] = "eligible"
        base["eligible"] = False  # nothing to write; last_verified refresh only
        base["reason"] = "New value matches current value. Refresh last_verified only."
        return base

    # 5. Contradiction of a verified:true / CFR-cited field -> hard unexpected flag.
    if parent_verified is True and exists and not values_equal(found, current):
        base["category"] = "unexpected_change"
        base["status"] = "eligible"
        base["eligible"] = False  # hard-flag, never auto-merge
        base["reason"] = ("HARD FLAG: value differs from a field marked verified:true. "
                          "A verified value should not move without human review. "
                          "Requires written justification before any apply.")
        return base

    # 6. verification_transition: parent verified:false and a tier-1 source confirms.
    if parent_verified is False and tier == 1:
        base["category"] = "verification_transition"
        base["status"] = "eligible"
        base["eligible"] = True
        base["flip_verified"] = True
        base["reason"] = ("Tier-1 source confirms a value on a verified:false record. "
                          "Fill value AND flip verified:false -> true.")
        return base

    # 7. new_coverage: field currently null or absent, and a real value found.
    if (not exists or current is None) and found is not None:
        base["category"] = "new_coverage"
        base["status"] = "eligible"
        base["eligible"] = True
        if parent_verified is False:
            base["reason"] = ("Field was null/absent; filling with tier-%s value. "
                              "verified flag stays false (not a tier-1 confirmation)." % tier)
        else:
            base["reason"] = "Field was null/absent; filling with new value."
        return base

    # 8. expected_change: a bulletin date / queue note / status note that moved.
    if is_expected_field(fp):
        base["category"] = "expected_change"
        base["status"] = "eligible"
        base["eligible"] = True
        if parent_verified is False:
            base["reason"] = ("Bulletin/queue field moved (normal monthly drift). "
                              "verified flag stays false (tier-%s, not tier-1)." % tier)
        else:
            base["reason"] = "Bulletin/queue field moved (normal monthly drift)."
        return base

    # 9. Anything else that changed -> unexpected (needs justification).
    base["category"] = "unexpected_change"
    base["status"] = "eligible"
    base["eligible"] = False
    base["reason"] = ("A field that should not drift on a monthly cadence changed "
                      "(e.g. processing time, audit rate, fee). Requires written "
                      "justification before any apply.")
    return base


def fmt_val(v):
    if v is None:
        return "null"
    if isinstance(v, str):
        return v
    return json.dumps(v)


def build_markdown(run_date, rulebook, sources, fetch_results, dispositions,
                   fallback_date_used):
    fr = fetch_results
    counts = {k: 0 for k in ("no_change", "expected_change", "unexpected_change",
                             "verification_transition", "new_coverage",
                             "low_confidence", "auto_fetchable_false", "out_of_scope")}
    for d in dispositions:
        counts[d["category"]] = counts.get(d["category"], 0) + 1

    hard_flags = counts["unexpected_change"]
    rejected_low = counts["low_confidence"]
    skipped = counts["auto_fetchable_false"]
    oos = counts["out_of_scope"]

    lines = []
    lines.append("# Freshness Proposal - %s" % run_date)
    lines.append("")
    lines.append("## Run metadata")
    lines.append("- run_date: %s%s" % (run_date,
                 " (FALLBACK: derived from wall clock - no run_date/--date supplied)"
                 if fallback_date_used else ""))
    lines.append("- rulebook_version: %s" % rulebook.get("meta", {}).get("version", "?"))
    lines.append("- sources_version: %s" % sources.get("meta", {}).get("version", "?"))
    lines.append("- bulletin_month_found: %s" % fr.get("bulletin_month_found", "?"))
    lines.append("- fetched_by: %s" % fr.get("fetched_by", "(unspecified)"))
    lines.append("- findings_in_fetch_results: %d" % len(fr.get("findings", [])))
    lines.append("- DRAFT FOR HUMAN REVIEW - nothing applied to rulebook.json by this step.")
    if fr.get("fetch_notes"):
        lines.append("- fetch_notes: %s" % fr["fetch_notes"])
    lines.append("")

    lines.append("## Summary")
    lines.append("- no_change: %d fields" % counts["no_change"])
    lines.append("- expected_change: %d fields" % counts["expected_change"])
    lines.append("- unexpected_change: %d fields (HARD-FLAGGED - see below)" % hard_flags)
    lines.append("- verification_transition: %d fields (tier-1 confirmed, flag flips)"
                 % counts["verification_transition"])
    lines.append("- new_coverage: %d fields eligible" % counts["new_coverage"])
    lines.append("- rejected (low confidence): %d fields" % rejected_low)
    lines.append("- skipped (auto_fetchable:false): %d fields" % skipped)
    lines.append("- rejected (out of scope): %d fields" % oos)
    lines.append("")

    # ---- Verification section (does the fetch confirm what the rulebook holds?) ----
    lines.append("## Verification")
    lines.append("")
    lines.append("How each finding compares to the current rulebook value:")
    lines.append("")
    lines.append("| field_path | rulebook value | found value | agree? | confidence | tier | sources |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in dispositions:
        agree = "AGREE" if d["category"] == "no_change" else "differs"
        lines.append("| `%s` | %s | %s | %s | %s | %s | %s |" % (
            d["field_path"], fmt_val(d["current_value"]), fmt_val(d["found_value"]),
            agree, d["confidence"], d["tier"], ", ".join(d["sources"])))
    lines.append("")

    def section(title, cats, with_reason=True):
        lines.append("## %s" % title)
        rows = [d for d in dispositions if d["category"] in cats]
        if not rows:
            lines.append("")
            lines.append("_None._")
            lines.append("")
            return
        lines.append("")
        for d in rows:
            src = ", ".join(d["sources"])
            base = ("- `%s` - before: %s - after: %s - confidence: %s - tier: %s - source: %s"
                    % (d["field_path"], fmt_val(d["current_value"]),
                       fmt_val(d["found_value"]), d["confidence"], d["tier"], src))
            lines.append(base)
            if d.get("notes"):
                lines.append("  - snippet/notes: %s" % d["notes"])
            if with_reason:
                lines.append("  - disposition: %s" % d["reason"])
        lines.append("")

    lines.append("## Proposed changes by category")
    lines.append("")
    section("no_change", ["no_change"])
    section("expected_change", ["expected_change"])
    section("unexpected_change (HARD FLAG - written justification required)",
            ["unexpected_change"])
    section("verification_transition (verified:false -> true, tier-1 only)",
            ["verification_transition"])
    section("new_coverage", ["new_coverage"])

    # ---- Could-not-verify ----
    lines.append("## Could-not-verify")
    lines.append("")
    cnv = [d for d in dispositions
           if d["category"] in ("low_confidence", "auto_fetchable_false", "out_of_scope")]
    if not cnv:
        lines.append("_None._")
    else:
        for d in cnv:
            lines.append("- `%s` (%s): %s" % (d["field_path"], d["category"], d["reason"]))
            if d.get("notes"):
                lines.append("  - notes: %s" % d["notes"])
    lines.append("")

    # ---- Fetch log ----
    lines.append("## Fetch log")
    lines.append("")
    lines.append("| # | field_path | sources | tier | confidence | found value |")
    lines.append("|---|---|---|---|---|---|")
    for i, f in enumerate(fr.get("findings", []), 1):
        lines.append("| %d | `%s` | %s | %s | %s | %s |" % (
            i, f.get("field_path", "?"), ", ".join(f.get("sources", [])),
            f.get("tier", "?"), f.get("confidence", "?"), fmt_val(f.get("found_value"))))
    lines.append("")

    # ---- Apply set (machine-readable) ----
    changes = []
    for d in dispositions:
        if d["eligible"]:
            changes.append({
                "field_path": d["field_path"],
                "new_value": d["found_value"],
                "confidence": d["confidence"],
                "category": d["category"],
                "flip_verified": d["flip_verified"],
            })
    apply_set = {
        "run_date": run_date,
        "rulebook_version": rulebook.get("meta", {}).get("version", "?"),
        "generated_by": "diff_proposal.py",
        "note": ("Machine-readable apply set consumed by apply_proposal.py. Only "
                 "changes that passed ALL safety gates are listed. Hard-flagged "
                 "unexpected_change, low-confidence, out-of-scope, and "
                 "auto_fetchable:false items are intentionally excluded."),
        "changes": changes,
    }

    lines.append("## Apply set (machine-readable)")
    lines.append("")
    lines.append("This fenced block is what `apply_proposal.py` parses. Do not hand-edit "
                 "unless you understand the schema. Every entry passed all SOP safety gates.")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(apply_set, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")

    # ---- Recommended patch ----
    lines.append("## Recommended patch (for human review - DO NOT auto-apply)")
    lines.append("")
    lines.append("On approval, run the apply step (dry-run first, then --commit):")
    lines.append("")
    lines.append("```")
    lines.append("python3 automation/apply_proposal.py --proposal freshness_proposals/%s.md"
                 % run_date)
    lines.append("# review the printed diff, then:")
    lines.append("python3 automation/apply_proposal.py --proposal freshness_proposals/%s.md --commit"
                 % run_date)
    lines.append("```")
    lines.append("")
    lines.append("Guarantees enforced by the apply step:")
    lines.append("- Only the apply-set changes above are written; nothing else moves.")
    lines.append("- `meta.last_verified` is set to %s; `meta.version` patch-bumped." % run_date)
    lines.append("- `wrong_calls_to_avoid[]`, `meta.not_in_scope[]`, `meta.primary_sources[]`, "
                 "`meta.secondary_sources[]` are preserved byte-for-byte.")
    lines.append("- `verified:false -> true` flips only where a tier-1 finding authorized it.")
    lines.append("- The inlined JSON in index.html is re-synced from rulebook.json.")
    lines.append("")

    summary_counts = {
        "no_change": counts["no_change"],
        "expected_change": counts["expected_change"],
        "unexpected_change": hard_flags,
        "verification_transition": counts["verification_transition"],
        "new_coverage_eligible": counts["new_coverage"],
        "rejected_low_confidence": rejected_low,
        "skipped_auto_fetchable_false": skipped,
        "rejected_out_of_scope": oos,
        "apply_set_changes": len(changes),
    }
    return "\n".join(lines), summary_counts


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Diff a fetch-results JSON against rulebook.json and write a "
                    "dated freshness proposal (mechanical step; consumes fetch "
                    "results, never scrapes).")
    ap.add_argument("--fetch-results", required=True,
                    help="Path to the fetch-results JSON (see fetch_results_schema.json).")
    ap.add_argument("--rulebook", default=str(REPO / "rulebook.json"),
                    help="Path to rulebook.json (default: repo rulebook.json).")
    ap.add_argument("--sources", default=str(REPO / "sources.json"),
                    help="Path to sources.json (default: repo sources.json).")
    ap.add_argument("--out", default=str(REPO / "freshness_proposals"),
                    help="Proposals output directory (default: freshness_proposals/).")
    ap.add_argument("--date", default=None,
                    help="Canonical run date YYYY-MM-DD. Overrides run_date in the "
                         "fetch-results file. Never use wall clock implicitly.")
    args = ap.parse_args(argv)

    fetch_results = load_json(args.fetch_results)
    rulebook = load_json(args.rulebook)
    sources = load_json(args.sources)

    # Resolve the canonical run date: --date > fetch_results.run_date > wall-clock fallback.
    fallback_date_used = False
    if args.date:
        run_date = args.date
    elif fetch_results.get("run_date"):
        run_date = fetch_results["run_date"]
    else:
        run_date = datetime.date.today().isoformat()
        fallback_date_used = True

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", run_date):
        sys.stderr.write("ERROR: run_date must be YYYY-MM-DD, got %r\n" % run_date)
        return 2

    protected_paths = build_auto_fetchable_false_set(sources)

    dispositions = [categorize(rulebook, protected_paths, f)
                    for f in fetch_results.get("findings", [])]

    md, summary = build_markdown(run_date, rulebook, sources, fetch_results,
                                 dispositions, fallback_date_used)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("%s.md" % run_date)
    # SOP 4.1: if the file exists, append a run-timestamp suffix rather than overwrite.
    if out_path.exists():
        stamp = datetime.datetime.now().strftime("%H%M%S")
        out_path = out_dir / ("%s_%s.md" % (run_date, stamp))
    out_path.write_text(md, encoding="utf-8")

    print("Freshness proposal written: %s" % out_path)
    print("  no_change:                %d" % summary["no_change"])
    print("  expected_change:          %d" % summary["expected_change"])
    print("  unexpected_change:        %d  (HARD FLAG - review before any apply)"
          % summary["unexpected_change"])
    print("  verification_transition:  %d  (tier-1, flips verified flag)"
          % summary["verification_transition"])
    print("  new_coverage eligible:    %d" % summary["new_coverage_eligible"])
    print("  rejected (low conf):      %d" % summary["rejected_low_confidence"])
    print("  skipped (auto_fetchable:false): %d" % summary["skipped_auto_fetchable_false"])
    print("  rejected (out of scope):  %d" % summary["rejected_out_of_scope"])
    print("  apply-set changes:        %d" % summary["apply_set_changes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
