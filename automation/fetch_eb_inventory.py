#!/usr/bin/env python3
"""Parse the USCIS employment-based I-485 inventory workbook into eb_inventory.json.

WHAT THIS DATA IS
    USCIS publishes a monthly workbook counting **pending Form I-485 applications**
    in the employment-based preference categories, broken out by country of
    chargeability and by the month/year of the priority date. Cover page:
        https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data
        (topic filter "Employment Based", topic_id[]=33682)

    It answers exactly one question, and USCIS says so in the workbook's own
    "How to Read This Report" sheet: every application listed with a priority date
    earlier than yours is ahead of you in the adjustment-of-status queue.

WHAT IT IS NOT (read this before believing any number derived from it)
    The workbook counts only people who have ALREADY FILED an I-485. USCIS states
    plainly that it excludes anyone with a pending or approved I-140 who has not yet
    filed, and excludes the Department of State consular queue and everything sitting
    at DOL. For a retrogressed category like EB-2 India, most of the real queue has
    not been able to file at all, so these counts are a FLOOR on the people ahead of
    you, never the whole line. Nothing downstream may present them as a total.

WHY THERE IS NO AUTOMATIC DOWNLOAD
    uscis.gov sits behind the same Cloudflare bot wall documented in
    BULLETIN_PDF_FINDINGS.md, so a scripted client gets a 403 challenge page rather
    than the file. This script therefore takes a locally downloaded workbook, the same
    human-in-the-loop pattern the Visa Bulletin PDF flow uses. It optionally tries
    archive.org, which is the only network path the automation is allowed to use.

    To refresh: open the cover page in a browser, download the newest
    "employment-based inventory" .xlsx, then run
        python3 automation/fetch_eb_inventory.py <path-to.xlsx>

TWO PARSING TRAPS THIS SCRIPT HANDLES (both verified against the August 2026 file)
    1. The year columns are NOT the same on every sheet. Five sheets are labelled
       "Prior Years, 2017 ... 2026", but the "India (EB2 EB3)" sheet is labelled
       "Prior Years, 2006 ... 2015", because Indian EB-2/EB-3 priority dates run
       further back than the workbook's 10-year window. Reading that sheet with the
       other sheets' labels misdates every Indian EB-2 record by 11 years. So the
       header row is read per sheet, never assumed.
    2. "D" is a suppressed small count, not zero and not missing. The workbook never
       defines it, but across 1,201 numeric cells in the August 2026 file the smallest
       non-zero value anywhere is exactly 11, and there are 1,234 "D" cells. Values 1
       through 10 never appear. So each "D" is somewhere in 1..10, and the honest
       treatment is a bounded range rather than a point estimate. This script emits
       the known sum and the suppressed-cell count separately so consumers can show
       the band; it never silently substitutes a guess.

HOW THE WORKBOOK IS READ
    openpyxl is preferred and is installed in automation/.venv (Homebrew's Python is
    PEP 668 externally-managed, so it cannot go in the system site-packages). Run:
        automation/.venv/bin/python3 automation/fetch_eb_inventory.py <path-to.xlsx>

    A stdlib fallback is kept for when openpyxl is absent, because an .xlsx is just a
    zip of XML and the standard library can read it directly. That keeps the script
    runnable with a bare `python3` on any machine. Both readers are checked against each
    other by --compare-readers, which must report identical output.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_PATH = os.path.join(REPO, "eb_inventory.json")

COVER_URL = ("https://www.uscis.gov/tools/reports-and-studies/immigration-and-citizenship-data"
             "?topic_id%5B%5D=33682")

USER_AGENT = ("green-card-monitor/2.0 (personal learning project; employment-based "
              "I-485 inventory; contact via repo)")

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS)}

# Sheet name -> the country key the site already uses (see vb_history.json).
SHEET_COUNTRY = {
    "Rest of the World": "ROW",
    "China": "China",
    "India (EB1 EW3 EB4 CRW EB5)": "India",
    "India (EB2 EB3)": "India",
    "Mexico": "Mexico",
    "Philippines": "Philippines",
}

# Category code found in the "Preference Category" label -> site category key.
# The four EB5 set-aside rows all roll up into EB-5, which is how the Visa Bulletin
# tiers the site already models are shaped. EW3 and CRW stay separate because they
# are genuinely different queues with their own cutoffs.
CAT_MAP = {"EB1": "EB-1", "EB2": "EB-2", "EB3": "EB-3", "EB4": "EB-4",
           "EB5": "EB-5", "EW3": "EW3", "CRW": "CRW"}

SUPPRESSED = "D"


try:
    import openpyxl
except ImportError:  # fall back to the stdlib zip reader below
    openpyxl = None


def read_workbook_openpyxl(path):
    """Return {sheet_name: [row, ...]} using openpyxl, cells coerced to strings.

    read_only + data_only so formulas come back as cached values and a large workbook
    streams rather than loading whole. Every cell is normalised to a string so both
    readers hand parse() exactly the same shape: ints must not arrive as 1234.0, or the
    "D" versus number discrimination downstream would see "1234.0" and reject it.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {}
    try:
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = []
                for v in row:
                    if v is None:
                        cells.append("")
                    elif isinstance(v, bool):
                        cells.append("TRUE" if v else "FALSE")
                    elif isinstance(v, float) and v.is_integer():
                        cells.append(str(int(v)))
                    else:
                        cells.append(str(v).strip() if isinstance(v, str) else str(v))
                rows.append(cells)
            out[ws.title] = rows
    finally:
        wb.close()
    return out


def read_workbook_stdlib(path):
    """Return {sheet_name: [row, ...]} where each row is a list of cell strings."""
    z = zipfile.ZipFile(path)
    names = z.namelist()

    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))

    sheet_names = [s.get("name") for s in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet")]
    sheet_parts = sorted(
        [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)],
        key=lambda x: int(re.search(r"(\d+)", x).group(1)),
    )

    out = {}
    for i, part in enumerate(sheet_parts):
        rows = []
        for row in ET.fromstring(z.read(part)).iter(NS + "row"):
            cells = []
            for c in row.findall(NS + "c"):
                v = c.find(NS + "v")
                if c.get("t") == "s" and v is not None:
                    cells.append(shared[int(v.text)])
                else:
                    cells.append(v.text if v is not None else "")
            rows.append(cells)
        out[sheet_names[i] if i < len(sheet_names) else part] = rows
    return out


def read_workbook(path, reader=None):
    """Read the workbook with openpyxl when available, else the stdlib zip reader."""
    if reader == "stdlib" or (reader is None and openpyxl is None):
        return read_workbook_stdlib(path)
    return read_workbook_openpyxl(path)


def find_header(rows):
    """Locate the header row and return (index, [year_label, ...]).

    Trap 1 lives here: the year labels are read from the sheet being parsed, never
    copied from another sheet.
    """
    for i, r in enumerate(rows[:12]):
        if r and r[0] == "Country Of Chargeability":
            years = [c.replace("Priority Date Year - ", "").strip() for c in r[4:] if c]
            return i, years
    raise ValueError("no header row found (expected a cell 'Country Of Chargeability')")


def as_of_from(rows):
    """Pull the 'As of <date>' line the workbook stamps in its third row."""
    for r in rows[:6]:
        for c in r:
            m = re.search(r"As of\s+(\w+ \d{1,2}, \d{4})", c or "")
            if m:
                return m.group(1)
    return None


def parse(book):
    """Build the series map keyed 'CAT|COUNTRY'."""
    series = {}
    as_of = None
    prior_years_only = set()

    for sheet, rows in book.items():
        country = SHEET_COUNTRY.get(sheet)
        if country is None:
            continue  # "How to Read This Report" and anything new we don't model
        as_of = as_of or as_of_from(rows)
        hdr_i, years = find_header(rows)

        for r in rows[hdr_i + 1:]:
            if len(r) < 5 or not r[1] or not r[1].startswith("Employment"):
                continue
            codes = re.findall(r"\(([A-Z0-9]+)\)", r[1])
            cat = CAT_MAP.get(codes[-1]) if codes else None
            if cat is None:
                continue
            status = r[2] or ""
            month = r[3] or ""
            if month not in MONTH_NUM:
                continue

            key = cat + "|" + country
            s = series.setdefault(key, {
                "category": cat, "country": country, "sheets": [],
                "known": 0, "suppressed_cells": 0,
                "by_status": {}, "cells": {}, "prior_years": {"known": 0, "suppressed_cells": 0},
            })
            if sheet not in s["sheets"]:
                s["sheets"].append(sheet)
            st = s["by_status"].setdefault(status, {"known": 0, "suppressed_cells": 0})

            for j, year in enumerate(years):
                raw = r[4 + j] if (4 + j) < len(r) else ""
                if raw == "":
                    continue
                # "Prior Years" is an open-ended bucket with no month resolution we can
                # trust, so it is kept separate rather than pretending to be a date.
                bucket = None if not re.fullmatch(r"\d{4}", year) else year
                if bucket is None:
                    prior_years_only.add(key)
                    tgt = s["prior_years"]
                else:
                    tgt = None

                if raw == SUPPRESSED:
                    s["suppressed_cells"] += 1
                    st["suppressed_cells"] += 1
                    if tgt is not None:
                        tgt["suppressed_cells"] += 1
                    else:
                        pd = "%s-%02d" % (bucket, MONTH_NUM[month])
                        c = s["cells"].setdefault(pd, {"n": 0, "d": 0})
                        c["d"] += 1
                    continue

                if not re.fullmatch(r"-?\d+", raw):
                    continue
                n = int(raw)
                s["known"] += n
                st["known"] += n
                if tgt is not None:
                    tgt["known"] += n
                elif n:
                    pd = "%s-%02d" % (bucket, MONTH_NUM[month])
                    c = s["cells"].setdefault(pd, {"n": 0, "d": 0})
                    c["n"] += n

    # Flatten cells to a sorted list and drop empties.
    for key, s in series.items():
        s["cells"] = [
            dict(pd=pd, **{k: v for k, v in c.items() if v})
            for pd, c in sorted(s["cells"].items())
            if c["n"] or c["d"]
        ]
        s["by_status"] = {k: v for k, v in s["by_status"].items()
                          if v["known"] or v["suppressed_cells"]}
    return series, as_of


def try_archive(url):
    """The only network path automation may use. Best effort; failure is fine."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print("  archive.org fetch failed (%s); supply a local file instead" % e, file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook", nargs="?",
                    help="path to a locally downloaded employment-based inventory .xlsx")
    ap.add_argument("--archive-url", help="a web.archive.org URL for the workbook")
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--reader", choices=["openpyxl", "stdlib"],
                    help="force one reader (default: openpyxl when importable)")
    ap.add_argument("--compare-readers", action="store_true",
                    help="parse with BOTH readers and assert the results are identical; "
                         "writes nothing. Run this after any change to either reader.")
    args = ap.parse_args()

    path = args.workbook
    tmp = None
    if not path and args.archive_url:
        blob = try_archive(args.archive_url)
        if blob is None:
            return 2
        tmp = os.path.join(HERE, "_eb_inventory_tmp.xlsx")
        with open(tmp, "wb") as f:
            f.write(blob)
        path = tmp
    if not path:
        print("Nothing to parse. uscis.gov is Cloudflare bot-walled, so download the\n"
              "workbook in a browser from:\n  %s\nthen re-run with that file path."
              % COVER_URL, file=sys.stderr)
        return 2
    if not os.path.exists(path):
        print("no such file: %s" % path, file=sys.stderr)
        return 2

    if args.compare_readers:
        if openpyxl is None:
            print("openpyxl is not importable, so there is nothing to compare against.\n"
                  "Use automation/.venv/bin/python3 (see the module docstring).",
                  file=sys.stderr)
            return 2
        a, a_as_of = parse(read_workbook(path, "openpyxl"))
        b, b_as_of = parse(read_workbook(path, "stdlib"))
        ja = json.dumps({"as_of": a_as_of, "series": a}, sort_keys=True)
        jb = json.dumps({"as_of": b_as_of, "series": b}, sort_keys=True)
        if ja == jb:
            print("readers agree: identical parse from openpyxl and the stdlib fallback")
            print("  %d series, %s known applications"
                  % (len(a), format(sum(s["known"] for s in a.values()), ",")))
            return 0
        print("READERS DISAGREE - do not trust the output until this is resolved",
              file=sys.stderr)
        print("  openpyxl: %d series / %d chars" % (len(a), len(ja)), file=sys.stderr)
        print("  stdlib:   %d series / %d chars" % (len(b), len(jb)), file=sys.stderr)
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                print("  first differing series: %s" % k, file=sys.stderr)
                print("    openpyxl known=%s  stdlib known=%s"
                      % (a.get(k, {}).get("known"), b.get(k, {}).get("known")),
                      file=sys.stderr)
                break
        return 1

    book = read_workbook(path, args.reader)
    series, as_of = parse(book)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)

    total_known = sum(s["known"] for s in series.values())
    total_d = sum(s["suppressed_cells"] for s in series.values())

    doc = {
        "as_of": as_of,
        "source_name": "USCIS pending employment-based Form I-485 inventory",
        "source_url": COVER_URL,
        "source_file": os.path.basename(path),
        "generated_by": "automation/fetch_eb_inventory.py",
        "counts": "pending Form I-485 applications, by priority date month",
        "scope_note": ("Counts only applications already filed. USCIS excludes anyone with a "
                       "pending or approved I-140 who has not yet filed an I-485, the "
                       "Department of State consular queue, and everything still at DOL. In a "
                       "retrogressed category most of the real queue has not been able to file, "
                       "so these are a floor on the people ahead of you, not the whole line."),
        "suppression": {
            "symbol": SUPPRESSED,
            "min": 1,
            "max": 10,
            "note": ("USCIS does not define 'D'. Inferred from the data: across this workbook the "
                     "smallest non-zero value anywhere is 11, so each 'D' is a suppressed count "
                     "of 1 to 10. Ranges are reported rather than a substituted guess."),
        },
        "totals": {"known": total_known, "suppressed_cells": total_d},
        "series": series,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")

    print("wrote %s" % args.out)
    print("  as of %s, %d series, %s known applications, %d suppressed cells"
          % (as_of, len(series), format(total_known, ","), total_d))
    for key in sorted(series, key=lambda k: -series[k]["known"])[:6]:
        s = series[key]
        print("    %-16s %9s known  +%3d suppressed  (%s)"
              % (key, format(s["known"], ","), s["suppressed_cells"],
                 ", ".join(sorted(s["by_status"]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
