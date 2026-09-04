#!/usr/bin/env python3
"""
pdf_to_fetch_results.py — turn a parsed official Visa Bulletin PDF into a
fetch_results_schema.json snapshot, deterministically and with NO LLM.

This is the bridge that lets the Wayback/PDF path feed the EXISTING mechanical
pipeline (diff_proposal.py -> apply_proposal.py) instead of a Claude/WebFetch
Step-1. It shells out to bulletin_pdf_fetch.py --parse (pdftotext + regex) for
the numbers, then emits one finding per EB-1/2/3 x 5-country x {final_action_date,
date_for_filing} cell.

Because the source is the OFFICIAL DoS bulletin PDF (read from archive.org's
capture, not scraped/evaded), every finding is tier 1, confidence "high".
diff_proposal.py then categorizes each cell as no_change / expected_change /
new_coverage vs the current rulebook, exactly as it would for a Claude fetch.

No LLM. stdlib + a subprocess call to the existing parser. No Cloudflare bypass.

Personal-learning project. NOT legal advice, NOT official guidance.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATS = ["EB-1", "EB-2", "EB-3"]
COUNTRIES = ["India", "China", "ROW", "Mexico", "Philippines"]
FIELDS = ["final_action_date", "date_for_filing"]


def parse_pdf(pdf_path):
    """Run the existing deterministic parser and return its categories dict."""
    out = subprocess.check_output(
        [sys.executable, str(HERE / "bulletin_pdf_fetch.py"), "--parse", pdf_path])
    return json.loads(out)


def build(pdf_path, bulletin_month, run_date):
    cats = parse_pdf(pdf_path)
    findings = []
    for cat in CATS:
        for country in COUNTRIES:
            cell = cats.get(cat, {}).get(country)
            if not isinstance(cell, dict):
                continue  # cell not present in the bulletin for this cat/country
            for field in FIELDS:
                if field not in cell:
                    continue
                findings.append({
                    "field_path": "bulletin.categories.%s.%s.%s" % (cat, country, field),
                    "found_value": cell[field],   # date string | "CURRENT" | null (Unavailable)
                    "sources": ["dos-visa-bulletin-pdf-wayback"],
                    "tier": 1,
                    "confidence": "high",
                    "notes": "Official DoS Visa Bulletin PDF for %s, read from the archive.org capture and parsed deterministically (bulletin_pdf_fetch.py). No LLM, no scraping/evasion." % bulletin_month,
                })
    return {
        "run_date": run_date,
        "bulletin_month_found": bulletin_month,
        "fetched_by": "wayback-pdf-parse (deterministic, no LLM)",
        "fetch_notes": "Numbers from the official DoS bulletin PDF captured by the Internet Archive (Wayback Machine) and parsed with pdftotext+regex. tier 1 / high confidence. travel.state.gov itself was never fetched or bypassed.",
        "findings": findings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert a parsed Visa Bulletin PDF into a fetch_results snapshot (no LLM).")
    ap.add_argument("--pdf", required=True, help="Path to the Visa Bulletin PDF (e.g. a Wayback-fetched copy).")
    ap.add_argument("--bulletin-month", required=True, help="Bulletin month, YYYY-MM (e.g. 2026-09).")
    ap.add_argument("--run-date", required=True, help="Canonical run date, YYYY-MM-DD.")
    ap.add_argument("--out", required=True, help="Output fetch_results JSON path.")
    args = ap.parse_args(argv)
    try:
        fr = build(args.pdf, args.bulletin_month, args.run_date)
    except Exception as e:
        sys.stderr.write("pdf_to_fetch_results error: %s\n" % e)
        return 2
    if not fr["findings"]:
        sys.stderr.write("No findings parsed from PDF — refusing to write an empty snapshot.\n")
        return 3
    Path(args.out).write_text(json.dumps(fr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s (%d findings, bulletin %s)" % (args.out, len(fr["findings"]), args.bulletin_month))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
