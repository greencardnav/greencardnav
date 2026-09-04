#!/usr/bin/env python3
"""
apply_proposal.py - the APPLY half of the green card tool's monthly freshness workflow.

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
The workflow splits into a Claude-assisted FETCH step (which produces a
fetch-results JSON, because travel.state.gov / uscis.gov are Cloudflare-walled
and a cron cannot scrape them) and MECHANICAL steps (pure Python stdlib).
diff_proposal.py already ran and wrote a dated proposal markdown containing a
machine-readable "apply set" fenced json block. THIS script is the last
mechanical step: it parses that apply set and, ONLY with an explicit --commit,
writes the approved changes into rulebook.json and regenerates rulebook.js
(the shared data file the live multi-page site actually reads via
window.__RULEBOOK__). If a legacy inlined <script id="rulebook"> block still
exists in index.html it is also re-synced; after the 5-page split that block is
gone, so the index re-sync is skipped when absent (not an error).

HUMAN-REVIEW GATE
-----------------
--dry-run is the DEFAULT. Without --commit this script prints a unified diff of
every change it WOULD make and stops. Nothing is written. You must pass --commit
to actually modify files. This is the "human disposes" gate from the SOP.

SAFETY GUARANTEES (enforced in code):
  - Only apply-set field paths are written. Nothing else moves.
  - verified:false -> true flips ONLY where the apply set's flip_verified is true
    (which diff_proposal.py only sets on tier-1 findings).
  - meta.last_verified set to the proposal date; meta.version semver-patch-bumped.
  - wrong_calls_to_avoid[], meta.not_in_scope[], meta.primary_sources[],
    meta.secondary_sources[] are asserted byte-for-byte unchanged post-apply.
  - rulebook.json, rulebook.js, and (if present) the index.html inline block are
    validated as parseable JSON at the end; on any failure, all touched files are
    restored from an in-memory backup and the script exits non-zero.

Usage:
  python3 apply_proposal.py --proposal <path> [--rulebook <path>]
                            [--index <index.html path>] [--commit]

(--dry-run is default; --commit required to write. stdlib only.)
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

PRESERVE_PATHS = [
    "wrong_calls_to_avoid",
    "meta.not_in_scope",
    "meta.primary_sources",
    "meta.secondary_sources",
]

RULEBOOK_SCRIPT_OPEN = '<script type="application/json" id="rulebook">'
RULEBOOK_SCRIPT_CLOSE = "</script>"

# rulebook.js is the shared data file every page loads (window.__RULEBOOK__).
# The header must match the existing file byte-for-byte so the diff stays clean.
RULEBOOK_JS_HEADER = (
    "/* Shared rulebook data — single source consumed by app.js on every page.\n"
    "   Regenerate from index/rulebook.json if the rulebook changes. */\n"
    "window.__RULEBOOK__ = "
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def extract_apply_set(proposal_text):
    """Find the apply-set fenced json block. It is the ```json block whose parsed
    object has a 'changes' key and 'generated_by' == 'diff_proposal.py'. There is
    typically one such block per proposal."""
    blocks = re.findall(r"```json\s*\n(.*?)\n```", proposal_text, re.DOTALL)
    for b in blocks:
        try:
            obj = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "changes" in obj:
            return obj
    return None


def get_path(obj, dotted):
    cur = obj
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return (False, None)
    return (True, cur)


def set_path(obj, dotted, value):
    """Set a dot path, creating intermediate dicts only for the final missing key
    (new_coverage adds a leaf on an existing parent). Returns (ok, message)."""
    segs = dotted.split(".")
    cur = obj
    for seg in segs[:-1]:
        if isinstance(cur, dict) and seg in cur and isinstance(cur[seg], dict):
            cur = cur[seg]
        else:
            return (False, "parent path missing or not a dict at %r" % seg)
    if not isinstance(cur, dict):
        return (False, "parent is not a dict")
    cur[segs[-1]] = value
    return (True, "ok")


def parent_dict(obj, dotted):
    """Return the parent dict of a dotted leaf path, or None."""
    if "." not in dotted:
        return obj if isinstance(obj, dict) else None
    pp, _ = dotted.rsplit(".", 1)
    exists, parent = get_path(obj, pp)
    return parent if exists and isinstance(parent, dict) else None


def bump_patch(version):
    """Semver patch bump. '0.2.0' -> '0.2.1'. Non-semver -> append '.1'."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version.strip())
    if not m:
        return version + ".1"
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return "%d.%d.%d" % (major, minor, patch + 1)


def snapshot_preserved(rulebook):
    snap = {}
    for p in PRESERVE_PATHS:
        exists, val = get_path(rulebook, p)
        snap[p] = json.dumps(val, sort_keys=True, ensure_ascii=False) if exists else None
    return snap


def rulebook_to_pretty(rulebook):
    return json.dumps(rulebook, indent=2, ensure_ascii=False) + "\n"


def rulebook_to_min(rulebook):
    return json.dumps(rulebook, separators=(",", ":"), ensure_ascii=False)


def resync_index(index_text, rulebook):
    """Replace the payload line inside the <script id="rulebook"> block with the
    minified rulebook. Returns (new_text, ok, message)."""
    open_idx = index_text.find(RULEBOOK_SCRIPT_OPEN)
    if open_idx == -1:
        return (index_text, False, "could not find rulebook <script> open tag")
    after_open = open_idx + len(RULEBOOK_SCRIPT_OPEN)
    close_idx = index_text.find(RULEBOOK_SCRIPT_CLOSE, after_open)
    if close_idx == -1:
        return (index_text, False, "could not find </script> close tag after rulebook block")
    minified = rulebook_to_min(rulebook)
    new_payload = "\n" + minified + "\n"
    new_text = index_text[:after_open] + new_payload + index_text[close_idx:]
    return (new_text, True, "ok")


def read_index_rulebook(index_text):
    open_idx = index_text.find(RULEBOOK_SCRIPT_OPEN)
    if open_idx == -1:
        return None
    after_open = open_idx + len(RULEBOOK_SCRIPT_OPEN)
    close_idx = index_text.find(RULEBOOK_SCRIPT_CLOSE, after_open)
    if close_idx == -1:
        return None
    return index_text[after_open:close_idx].strip()


def rulebook_to_js(rulebook):
    """Serialize the rulebook as the shared rulebook.js file the live pages read:
    the exact header comment + `window.__RULEBOOK__ = <minified>;` + trailing newline."""
    return RULEBOOK_JS_HEADER + rulebook_to_min(rulebook) + ";\n"


def read_rulebook_js_payload(js_text):
    """Extract the JSON payload from a rulebook.js file (strip the header prefix and
    the trailing `;`). Returns the JSON string, or None if the shape is unexpected."""
    if not js_text.startswith(RULEBOOK_JS_HEADER):
        return None
    tail = js_text[len(RULEBOOK_JS_HEADER):].rstrip()
    if not tail.endswith(";"):
        return None
    return tail[:-1]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Apply a freshness proposal's apply-set to rulebook.json and "
                    "re-sync index.html. DRY-RUN by default; --commit to write.")
    ap.add_argument("--proposal", required=True, help="Path to the dated proposal markdown.")
    ap.add_argument("--rulebook", default=str(REPO / "rulebook.json"),
                    help="Path to rulebook.json (default: repo rulebook.json).")
    ap.add_argument("--index", default=str(REPO / "index.html"),
                    help="Path to index.html (default: repo index.html).")
    ap.add_argument("--rulebook-js", default=str(REPO / "rulebook.js"),
                    help="Path to rulebook.js, the shared data file the live pages "
                         "load (default: repo rulebook.js).")
    ap.add_argument("--commit", action="store_true",
                    help="Actually write changes. Without this flag, dry-run only.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Explicit dry-run (default behavior; ignored if --commit absent).")
    args = ap.parse_args(argv)

    commit = args.commit
    proposal_text = Path(args.proposal).read_text(encoding="utf-8")
    apply_set = extract_apply_set(proposal_text)
    if apply_set is None:
        sys.stderr.write("ERROR: no apply-set json block found in %s\n" % args.proposal)
        return 2

    run_date = apply_set.get("run_date")
    changes = apply_set.get("changes", [])
    if not run_date or not re.match(r"^\d{4}-\d{2}-\d{2}$", run_date):
        sys.stderr.write("ERROR: apply set missing a valid run_date.\n")
        return 2

    rulebook_path = Path(args.rulebook)
    index_path = Path(args.index)
    rulebook_js_path = Path(args.rulebook_js)
    rulebook_orig_text = rulebook_path.read_text(encoding="utf-8")
    index_orig_text = index_path.read_text(encoding="utf-8") if index_path.exists() else None
    rulebook_js_orig_text = rulebook_js_path.read_text(encoding="utf-8") if rulebook_js_path.exists() else None
    rulebook = json.loads(rulebook_orig_text)

    preserved_before = snapshot_preserved(rulebook)

    # Apply the changes in memory.
    applied = []
    for ch in changes:
        fp = ch["field_path"]
        new_val = ch["new_value"]
        exists, old_val = get_path(rulebook, fp)
        ok, msg = set_path(rulebook, fp, new_val)
        if not ok:
            sys.stderr.write("ERROR: cannot set %s: %s\n" % (fp, msg))
            return 2
        note = "%s: %s -> %s" % (fp, json.dumps(old_val, ensure_ascii=False) if exists else "(absent)",
                                 json.dumps(new_val, ensure_ascii=False))
        applied.append(note)
        # Handle verified:false -> true flip on the parent record.
        if ch.get("flip_verified"):
            pd = parent_dict(rulebook, fp)
            if pd is not None and pd.get("verified") is False:
                pd["verified"] = True
                applied.append("%s (parent).verified: false -> true" % fp)

    # meta bumps.
    meta = rulebook.setdefault("meta", {})
    old_version = meta.get("version", "0.0.0")
    new_version = bump_patch(old_version)
    old_lv = meta.get("last_verified")
    meta["version"] = new_version
    meta["last_verified"] = run_date
    applied.append("meta.version: %s -> %s" % (old_version, new_version))
    applied.append("meta.last_verified: %s -> %s" % (old_lv, run_date))

    # Assert preserved subtrees unchanged.
    preserved_after = snapshot_preserved(rulebook)
    for p in PRESERVE_PATHS:
        if preserved_before.get(p) != preserved_after.get(p):
            sys.stderr.write("ERROR: preserved subtree changed unexpectedly: %s. Aborting.\n" % p)
            return 3

    new_rulebook_text = rulebook_to_pretty(rulebook)

    # Build unified diff of rulebook.json.
    diff = difflib.unified_diff(
        rulebook_orig_text.splitlines(keepends=True),
        new_rulebook_text.splitlines(keepends=True),
        fromfile="rulebook.json (current)",
        tofile="rulebook.json (proposed)",
    )
    diff_text = "".join(diff)

    print("=" * 70)
    print("apply_proposal.py - %s" % ("COMMIT" if commit else "DRY-RUN (default)"))
    print("proposal: %s" % args.proposal)
    print("apply-set changes: %d" % len(changes))
    print("=" * 70)
    print("")
    print("Field changes that would be applied:")
    for a in applied:
        print("  - %s" % a)
    print("")
    print("Unified diff of rulebook.json:")
    print("")
    print(diff_text if diff_text.strip() else "(no textual change)")
    print("")

    if not commit:
        print("DRY-RUN complete. No files were modified.")
        print("Re-run with --commit to write rulebook.json and regenerate rulebook.js.")
        return 0

    # ---- COMMIT PATH ----
    # index.html re-sync is now OPTIONAL: after the 5-page split the inline
    # <script id="rulebook"> block is gone, so it's only touched if still present.
    index_has_block = index_orig_text is not None and RULEBOOK_SCRIPT_OPEN in index_orig_text
    new_index_text = None
    if index_has_block:
        new_index_text, ok, msg = resync_index(index_orig_text, rulebook)
        if not ok:
            sys.stderr.write("ERROR: index.html re-sync failed: %s. Aborting (no files written).\n" % msg)
            return 3

    new_rulebook_js_text = rulebook_to_js(rulebook)

    # Restore whatever we wrote, from in-memory backups.
    def restore(reason):
        rulebook_path.write_text(rulebook_orig_text, encoding="utf-8")
        if rulebook_js_orig_text is not None:
            rulebook_js_path.write_text(rulebook_js_orig_text, encoding="utf-8")
        if index_has_block and index_orig_text is not None:
            index_path.write_text(index_orig_text, encoding="utf-8")
        sys.stderr.write("ERROR: %s. Restored touched files from backup. Exiting non-zero.\n" % reason)

    # Write files.
    rulebook_path.write_text(new_rulebook_text, encoding="utf-8")
    rulebook_js_path.write_text(new_rulebook_js_text, encoding="utf-8")
    if index_has_block:
        index_path.write_text(new_index_text, encoding="utf-8")

    # Validate everything written parses as JSON. Restore on any failure.
    try:
        json.loads(rulebook_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        restore("rulebook.json failed to re-parse (%s)" % e)
        return 4

    js_payload = read_rulebook_js_payload(rulebook_js_path.read_text(encoding="utf-8"))
    if js_payload is None:
        restore("rulebook.js has unexpected shape after write (header/`;` not found)")
        return 4
    try:
        json.loads(js_payload)
    except json.JSONDecodeError as e:
        restore("rulebook.js payload failed to re-parse (%s)" % e)
        return 4

    if index_has_block:
        embedded = read_index_rulebook(index_path.read_text(encoding="utf-8"))
        if embedded is None:
            restore("could not re-locate rulebook block in index.html after write")
            return 4
        try:
            json.loads(embedded)
        except json.JSONDecodeError as e:
            restore("inlined index.html JSON failed to re-parse (%s)" % e)
            return 4

    print("COMMIT complete.")
    print("  rulebook.json updated (%d field changes + meta bump)." % len(changes))
    print("  meta.version -> %s ; meta.last_verified -> %s" % (new_version, run_date))
    print("  rulebook.js regenerated and validated (this is what the live pages read).")
    if index_has_block:
        print("  index.html inlined rulebook re-synced and validated.")
    else:
        print("  index.html has no inline rulebook block (5-page split) — skipped, as expected.")
    print("")
    print("NEXT STEP: deploy. Run:  bash automation/deploy.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
