#!/usr/bin/env python3
"""
bulletin_pdf_fetch.py — build Visa Bulletin PDF URLs, and parse a Visa Bulletin
PDF into the tool's rulebook `bulletin.categories` shape.

WHAT THIS IS (and the honest boundary)
--------------------------------------
Aashay found the bulletin is published as a direct PDF at a predictable URL:
  https://travel.state.gov/content/dam/visas/Bulletins/visabulletin_<Month><Year>.pdf

The URL PATTERN is real and useful, BUT the endpoint is NOT firewall-free.
Verified 2026-08-18: travel.state.gov serves this PDF behind Cloudflare bot
management (`server: cloudflare`, `__cf_bm` cookie). A scripted client — curl,
Python urllib, courteous UA, or even a browser User-Agent — gets HTTP 403 and an
HTML challenge page, NOT the PDF. It only downloads in a real browser because the
browser passes Cloudflare's JS challenge.

Therefore:
  * AUTO-FETCH FROM CI / A SCRIPT DOES NOT WORK and is not attempted here.
    (Defeating a federal site's bot wall with stealth/TLS-spoof tooling is out of
    bounds — we do not do it.)
  * The workflow that DOES work: a human opens the PDF URL in their browser
    (Cloudflare passes), saves the PDF, then runs `--parse <file.pdf>` locally to
    turn it into rulebook JSON — no manual transcription. `pdftotext -layout`
    (poppler) does the heavy lifting.

So this module gives you two things:
  1. `latest_bulletin_urls(today)` — the newest-first candidate URLs, for the
     paste-in card's one-hop "open the PDF" link (replaces the 3-hop site nav).
  2. `parse_pdf(path)` — parse a locally-downloaded bulletin PDF into the
     rulebook `bulletin.categories` structure (EB-1/2/3 x 5 countries,
     final_action_date + date_for_filing).

Dependency: `pdftotext` (poppler-utils). On macOS: `brew install poppler`.
Verified present at /opt/homebrew/bin/pdftotext (v26.07.0) on 2026-08-18.

stdlib only (subprocess, re, datetime, json, argparse, sys, pathlib) + external
`pdftotext` binary. No pip packages.
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

BASE = "https://travel.state.gov/content/dam/visas/Bulletins/visabulletin_%s%d.pdf"

# The five country columns the tool tracks. This is the OUTPUT set, not an assumption
# about the table's layout - see COLUMN_MARKERS.
COUNTRY_COLUMNS = ["ROW", "China", "India", "Mexico", "Philippines"]

# Column detection markers.
#
# WHY THIS IS NOT A FIXED LIST OF FIVE POSITIONS (a real bug that used to live here):
# the employment table does NOT always have five country columns. Bulletins from the
# EB-4 backlog years carry a sixth, "EL SALVADOR GUATEMALA HONDURAS" - verified present
# in January 2023 and gone again by September 2023. The old code zipped the first five
# tokens onto [ROW, China, India, Mexico, Philippines], so for those months it read
# El Salvador's date as India's, India's as Mexico's, and Mexico's as the Philippines'.
# Every value was a real date, just attached to the wrong country, which is invisible
# to a reader and would have quietly poisoned the charts.
#
# So the columns present are DETECTED from the header text and ordered by where they
# actually sit on the page. "ElSalvador" is detected purely so it can be counted and
# then dropped; the tool has no series for it.
COLUMN_MARKERS = [
    # The rest-of-world column, "All Chargeability Areas Except Those Listed", is stacked
    # over several header lines and WHERE THE LINE BREAKS FALL MOVES BETWEEN EDITIONS.
    # Three real layouts, all verified against local PDFs:
    #   Oct 2025:  "All Chargeability" / "Areas Except"  / "Those Listed"
    #   Sep 2026:  "All" / "Chargeability" / "Areas Except" / "Those Listed"
    #   Apr 2024:  "All Charge-" / "ability Areas" / "Except Those" / "Listed"
    # So even the WORD is hyphenated across lines in some editions. Any single fixed
    # phrase misses at least one layout, and a missed column meant the table came back
    # with four columns instead of five, which dropped every row for token-count
    # mismatch. Match any fragment unique to this column instead.
    ("ROW", re.compile(r"Chargeability|Charge-|ability\s+Areas|Areas\s+Except"
                       r"|Except\s+Those|Those\s+Listed", re.I)),
    ("China", re.compile(r"CHINA", re.I)),
    ("ElSalvador", re.compile(r"EL\s+SALVADOR", re.I)),
    ("India", re.compile(r"\bINDIA\b", re.I)),
    ("Mexico", re.compile(r"\bMEXICO\b", re.I)),
    ("Philippines", re.compile(r"PHILIPPIN", re.I)),
    # Vietnam had its own column through the 2019-2022 bulletins because of EB-5, giving
    # those editions SEVEN country columns. Detected purely so the count is right and the
    # remaining columns line up; like ElSalvador it is then dropped, since the tool has no
    # Vietnam series. Without it every row in those years was skipped for token-count
    # mismatch and the parser silently produced nothing for three years of bulletins.
    ("Vietnam", re.compile(r"VIETNAM", re.I)),
]

# Bulletin preference label -> tool category.
# EB-4 and EB-5 were missing, which is why vb_history.json could not be refreshed from
# a PDF at all: the heatmap draws five rows and this only produced three.
# Deliberately EXCLUDED: "Other Workers" (a sub-row of EB-3), "Certain Religious
# Workers" (a sub-row of EB-4), and the three EB-5 set-asides created by the 2022 RIA
# (Rural / High Unemployment / Infrastructure). Those are separate reserved pools, not
# the main preference queue the site charts.
PREF_TO_CATEGORY = {"1st": "EB-1", "2nd": "EB-2", "3rd": "EB-3",
                    "4th": "EB-4", "5th": "EB-5"}


# ---------------------------------------------------------------------------
# URL construction + date logic (pure string work, no network)
# ---------------------------------------------------------------------------
def bulletin_url(month_index, year):
    """month_index is 1-12."""
    return BASE % (MONTHS[month_index - 1], year)


def latest_bulletin_urls(today=None):
    """Return newest-first [(url, label), ...] candidates.

    State publishes the bulletin for month N around the 9th of month N-1, so the
    newest bulletin that exists is usually NEXT calendar month; if that isn't
    posted yet, the current month is the newest. Caller tries them in order (in a
    browser) and uses the first that resolves.
    """
    today = today or datetime.date.today()
    y, m = today.year, today.month
    nm_m = 1 if m == 12 else m + 1
    nm_y = y + 1 if m == 12 else y
    return [
        (bulletin_url(nm_m, nm_y), "%s %d (next month)" % (MONTHS[nm_m - 1], nm_y)),
        (bulletin_url(m, y), "%s %d (current month)" % (MONTHS[m - 1], y)),
    ]


# ---------------------------------------------------------------------------
# Date-token parsing
# ---------------------------------------------------------------------------
_MON3 = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
         "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_DDMONYY = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})$")


def parse_date_token(tok):
    """'01JAN14' -> '2014-01-01'; 'C' -> 'CURRENT'; 'U' -> None (unavailable)."""
    t = tok.strip().upper()
    if t in ("C", "CURRENT"):
        return "CURRENT"
    if t in ("U", "UNAVAILABLE", "UNAUTHORIZED"):
        return None
    m = _DDMONYY.match(t)
    if m:
        dd, mon, yy = m.group(1), m.group(2), m.group(3)
        if mon in _MON3:
            year = 2000 + int(yy)  # bulletins are all 2000s
            return "%04d-%02d-%02d" % (year, _MON3[mon], int(dd))
    return None  # unrecognized -> treat as no data


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------
def pdf_to_text(path):
    """Run `pdftotext -layout` (column-preserving) and return the text."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise SystemExit("pdftotext not found. Install poppler (brew install poppler).")
    if out.returncode != 0:
        raise SystemExit("pdftotext failed: %s" % out.stderr[:500])
    return out.stdout


# The two employment-based tables, in order: slice between the A heading and the B
# heading (Final Action), and from the B heading to the family/diversity section
# (Dates for Filing).
_HEAD_A = re.compile(r"FINAL ACTION DATES FOR EMPLOYMENT", re.I)
_HEAD_B = re.compile(r"DATES FOR FILING OF EMPLOYMENT", re.I)

# A value token: a date like 01NOV22, or C (current), or U (unavailable).
_TOKEN = re.compile(r"(?<![A-Za-z0-9])(\d{1,2}[A-Z]{3}\d{2}|C|U)(?![A-Za-z0-9])")

# The row label sits at the start of the line. Anchored so the sub-rows never win:
# "Other Workers" follows 3rd, "Certain Religious Workers" follows 4th, and the three
# "5th Set Aside" pools follow "5th Unreserved".
_LABEL = re.compile(r"^\s*(1st|2nd|3rd|4th|5th)\b", re.I)
_LABEL_SKIP = re.compile(
    r"^\s*(Other\s+Workers|Certain|Religious|Workers|\(including|"
    r"5th\s+Set\s+Aside|5th\s*$)", re.I)


# Rows that carried a recognised preference label but an unusable token count. Populated
# by _rows_from_slice and surfaced by parse_pdf, so a caller can tell "this month has no
# EB-2 row" apart from "this month's EB-2 row was unreadable".
SKIPPED = []


def _column_order(lines, first_data_idx):
    """Which country columns this table has, left to right.

    Reads the header block (every line above the first data row), records the
    horizontal offset of each country marker, and sorts by offset. `pdftotext -layout`
    preserves column positions, so offset order IS visual order. A single header column
    is stacked over several lines ("All / Chargeability / Areas Except / Those Listed"),
    so each marker is taken at its leftmost occurrence anywhere in the block.
    """
    # Scan only the lines immediately above the first data row, not everything since the
    # section heading. The prose paragraph that precedes each table ("...'C' means
    # current...") starts at column 0, so if any marker ever matched inside it the
    # detected offset would be 0 and the column ORDER would be wrong - which is the one
    # failure mode that produces plausible-looking wrong answers rather than a clean skip.
    window = lines[max(0, first_data_idx - 12):first_data_idx]
    offsets = {}
    for line in window:
        for name, pat in COLUMN_MARKERS:
            m = pat.search(line)
            if m and (name not in offsets or m.start() < offsets[name]):
                offsets[name] = m.start()
    return [n for n, _ in sorted(offsets.items(), key=lambda kv: kv[1])]


def _rows_from_slice(text_slice):
    """Return ({category: {country: raw_token}}, column_order) for one table.

    Tokens are matched to countries by COUNT against the detected header order, never
    against a hardcoded five. A row whose token count disagrees with the number of
    detected columns is SKIPPED rather than guessed at: a silently mis-aligned row is
    worse than a missing one, because every value still looks like a valid date.
    """
    lines = [ln.rstrip() for ln in text_slice.splitlines()]
    first_data = None
    for i, ln in enumerate(lines):
        if _LABEL.match(ln) and not _LABEL_SKIP.match(ln) and _TOKEN.search(ln):
            first_data = i
            break
    if first_data is None:
        return {}, []

    order = _column_order(lines, first_data)
    if not order:
        return {}, []

    found = {}
    for ln in lines[first_data:]:
        if _LABEL_SKIP.match(ln):
            continue
        m = _LABEL.match(ln)
        if not m:
            continue
        cat = PREF_TO_CATEGORY.get(m.group(1).lower())
        if not cat or cat in found:  # first occurrence only
            continue
        toks = _TOKEN.findall(ln[m.end():])
        if len(toks) != len(order):
            # Skipping is correct - a mis-aligned row would still look like valid dates -
            # but it must not be SILENT, or a typo in the source turns into a quietly
            # missing month. Real example: the October 2025 bulletin PDF misprints
            # Mexico's second-preference date as "15UL24" instead of "15JUL24", which is
            # unparseable, so that row yields 4 tokens against 5 columns. We report it and
            # decline to guess which month "UL" meant.
            SKIPPED.append({"category": cat, "expected": len(order),
                            "found": len(toks), "line": ln.strip()[:120]})
            continue
        found[cat] = dict(zip(order, toks))
    return found, order


def parse_pdf(path):
    """Parse a downloaded bulletin PDF -> rulebook `bulletin.categories` dict.

    Returns {"EB-1": {"India": {"final_action_date":..,"date_for_filing":..}, ...}, ...}
    for EB-1 through EB-5 x the five tracked countries, with ISO dates, "CURRENT", or
    None (unavailable / not published). Also returns "_columns", the column order each
    table was detected to have, so a caller can see whether a sixth country column was
    present rather than having to trust that it was handled.
    """
    del SKIPPED[:]          # per-call, so a caller sees only this PDF's problems
    text = pdf_to_text(path)
    a_start = _HEAD_A.search(text)
    b_start = _HEAD_B.search(text)
    if not a_start or not b_start:
        raise SystemExit("Could not locate the A/B employment-based table headings "
                         "in the PDF text. Layout may have changed.")
    a_slice = text[a_start.end():b_start.start()]
    # Bound the B slice at the family-based / diversity sections, so their tables
    # cannot leak preference rows into the employment result.
    tail = text[b_start.end():]
    stop = re.search(r"(?:DIVERSITY|FINAL ACTION DATES FOR FAMILY|"
                     r"DATES FOR FILING FAMILY)", tail, re.I)
    b_slice = tail[:stop.start()] if stop else tail

    fad, fad_cols = _rows_from_slice(a_slice)   # final action dates
    dff, dff_cols = _rows_from_slice(b_slice)   # dates for filing

    result = {}
    for cat in ("EB-1", "EB-2", "EB-3", "EB-4", "EB-5"):
        result[cat] = {}
        fad_row = fad.get(cat) or {}
        dff_row = dff.get(cat) or {}
        for country in COUNTRY_COLUMNS:
            ftok = fad_row.get(country)
            dtok = dff_row.get(country)
            result[cat][country] = {
                "final_action_date": parse_date_token(ftok) if ftok else None,
                "date_for_filing": parse_date_token(dtok) if dtok else None,
            }
    result["_columns"] = {"final_action": fad_cols, "dates_for_filing": dff_cols}
    result["_unreadable_rows"] = list(SKIPPED)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--urls", action="store_true",
                    help="Print the newest-first candidate bulletin PDF URLs and exit.")
    ap.add_argument("--parse", metavar="PDF",
                    help="Parse a locally-downloaded bulletin PDF into rulebook JSON.")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="Override 'today' for --urls (testing).")
    args = ap.parse_args()

    if args.urls:
        today = (datetime.date.fromisoformat(args.date) if args.date
                 else datetime.date.today())
        for url, label in latest_bulletin_urls(today):
            print("%-28s %s" % (label, url))
        return

    if args.parse:
        data = parse_pdf(Path(args.parse))
        print(json.dumps(data, indent=2))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
