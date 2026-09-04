#!/usr/bin/env python3
"""
refresh_bulletin_meta.py — advance the month-specific rulebook metadata that
apply_proposal.py does NOT touch, deterministically and with NO LLM.

apply_proposal.py writes the cutoff apply-set + bumps meta.version /
meta.last_verified. It does NOT advance:
  - bulletin.as_of              (drives the "Bulletin data: <month>" badge)
  - bulletin.chart_note         (the "which chart to file I-485 under" line)
  - twelve_month_lookback_eb2_india (the EB-2 India FAD history strip)
  - meta.bulletin_verified_source   (provenance string)

This helper closes that gap for the automated no-movement/new-coverage path.
It is intended to run AFTER apply_proposal.py --commit in the auto workflow, so
the file is already in indent-2 form (this writes indent-2 too, no reformat).

CHART_NOTE: the "which chart" determination is a USCIS-website fact not present
in the bulletin PDF, and (verified 2026-08-26) the USCIS When-to-File page is not
in the Wayback Machine. In the auto path (no cutoff movement), a chart FLIP is
very unlikely (flips track FY resets, which move cutoffs -> human-review path).
So we CARRY THE EXISTING CHART DETERMINATION FORWARD and only advance the month
word, and the workflow's Slack note says the determination was not re-verified.

No LLM. stdlib + a subprocess parse of the PDF for the EB-2 India lookback value.

Personal-learning project. NOT legal advice, NOT official guidance.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def month_label(ym):
    y, m = ym.split("-")
    return "%s %s" % (MONTHS[int(m)], y)


def parse_pdf(pdf_path):
    out = subprocess.check_output(
        [sys.executable, str(HERE / "bulletin_pdf_fetch.py"), "--parse", pdf_path])
    return json.loads(out)


def rulebook_js(rb, existing_js_text):
    """Rebuild rulebook.js reusing the exact header bytes from the current file."""
    marker = "window.__RULEBOOK__ = "
    header = existing_js_text[:existing_js_text.index(marker) + len(marker)]
    return header + json.dumps(rb, separators=(",", ":"), ensure_ascii=False) + ";\n"


def refresh(rb, pdf_cats, bulletin_month):
    """Mutate rb in place; return a list of human-readable change descriptions."""
    changes = []
    b = rb["bulletin"]

    # 1. as_of
    if b.get("as_of") != bulletin_month:
        changes.append("as_of: %s -> %s" % (b.get("as_of"), bulletin_month))
        b["as_of"] = bulletin_month

    # 2. chart_note — carry the chart determination forward, advance the month.
    note = b.get("chart_note", "")
    chart = "Final Action Dates"
    mchart = re.search(r"honors (Final Action Dates|Dates for Filing) chart", note)
    if mchart:
        chart = mchart.group(1)
    new_note = ("USCIS honors %s chart for I-485 filing in %s. Users on the Date "
                "for Filing chart cannot file I-485 this month." % (chart, month_label(bulletin_month)))
    if note != new_note:
        changes.append("chart_note month -> %s (chart '%s' carried forward, not re-verified)"
                       % (month_label(bulletin_month), chart))
        b["chart_note"] = new_note

    # 3. EB-2 India lookback: append this month's FAD if not already present.
    lb = b.get("twelve_month_lookback_eb2_india")
    if isinstance(lb, list):
        if not lb or lb[-1].get("month") != bulletin_month:
            eb2_india = (pdf_cats.get("EB-2", {}).get("India") or {}).get("final_action_date", "MISSING")
            if eb2_india != "MISSING":
                entry = {"month": bulletin_month, "final_action_date": eb2_india}
                if eb2_india is None:
                    entry["note"] = "Unavailable"
                lb.append(entry)
                changes.append("lookback: appended %s (EB-2 India FAD=%r)" % (bulletin_month, eb2_india))

    # 4. provenance note
    src = ("State Department Visa Bulletin for %s, auto-refreshed %s from the "
           "official DoS PDF captured by the Internet Archive (Wayback Machine) and "
           "parsed deterministically (no LLM, no scraping). No cutoff movement on any "
           "verified cell this run (movements are held for human review). The USCIS "
           "'which chart' determination was carried forward from the prior month, not "
           "re-verified this run — confirm at uscis.gov/visabulletininfo if a chart flip "
           "is suspected." % (month_label(bulletin_month), rb["meta"].get("last_verified", "")))
    if rb["meta"].get("bulletin_verified_source") != src:
        changes.append("bulletin_verified_source -> auto-refresh note for %s" % month_label(bulletin_month))
        rb["meta"]["bulletin_verified_source"] = src

    return changes


def main(argv=None):
    ap = argparse.ArgumentParser(description="Advance month-specific rulebook metadata (no LLM). Dry-run unless --commit.")
    ap.add_argument("--pdf", required=True, help="Path to the bulletin PDF (for the EB-2 India lookback value).")
    ap.add_argument("--bulletin-month", required=True, help="Bulletin month, YYYY-MM.")
    ap.add_argument("--rulebook", default=str(REPO / "rulebook.json"))
    ap.add_argument("--rulebook-js", default=str(REPO / "rulebook.js"))
    ap.add_argument("--commit", action="store_true", help="Write changes (default: dry-run).")
    args = ap.parse_args(argv)

    try:
        rb = json.loads(Path(args.rulebook).read_text(encoding="utf-8"))
        cats = parse_pdf(args.pdf)
    except Exception as e:
        sys.stderr.write("refresh_bulletin_meta error: %s\n" % e)
        return 2

    changes = refresh(rb, cats, args.bulletin_month)
    if not changes:
        print("No metadata changes needed (already current for %s)." % args.bulletin_month)
        return 0
    print("Metadata changes for %s:" % args.bulletin_month)
    for c in changes:
        print("  - " + c)

    if not args.commit:
        print("\n(dry-run; re-run with --commit to write)")
        return 0

    js_existing = Path(args.rulebook_js).read_text(encoding="utf-8")
    Path(args.rulebook).write_text(json.dumps(rb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.rulebook_js).write_text(rulebook_js(rb, js_existing), encoding="utf-8")
    # validate rulebook.js round-trips
    js = Path(args.rulebook_js).read_text(encoding="utf-8")
    marker = "window.__RULEBOOK__ = "
    back = json.loads(js[js.index(marker) + len(marker):].rstrip().rstrip(";"))
    assert back == rb, "rulebook.js payload mismatch after write"
    print("\nWROTE rulebook.json + rulebook.js.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
