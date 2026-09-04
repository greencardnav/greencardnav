#!/usr/bin/env python3
"""
fetch_vb_history.py - fill and extend vb_history.json from ARCHIVED OFFICIAL bulletins.

WHY THIS EXISTS
---------------
vb_history.json drives every chart in History & Trends on tools.html: the cutoff
line chart, the month-over-month velocity chart, the retrogression heatmap and the
EB-2/EB-3 crossover chart. Nothing wrote it. It was hand-built, and it drifted in
two ways that a reader can SEE on the page:

  1. Every one of the 25 series was missing the same twelve months, Oct 2022 through
     Sep 2023 - the whole of fiscal year 2023. The heatmap's x-axis jumped straight
     from 2022 to 2024 and the line chart drew a year that never happened, because
     the two neighbouring months were joined by a straight segment.
  2. The tail lagged the rest of the site. rulebook.json carried the September 2026
     bulletin while these series stopped at August 2026, so the same page showed two
     different "latest" months.

Both were misses, not gaps in the public record: State publishes a bulletin every
month and the Internet Archive has them.

WHY THE WAYBACK MACHINE AND NOT travel.state.gov
------------------------------------------------
travel.state.gov is behind Cloudflare bot management. A script gets HTTP 403 and a
JS challenge, and defeating a federal site's bot wall is out of bounds. RUNBOOK.md
therefore forbids fetching it from automation. The Internet Archive's copy of the
SAME official government page is public, scriptable, and traces back to the official
source, so that is what this reads. Values are the government's own, one hop removed.

Rate limits are real: archive.org returns 429 under load. This paces itself, retries
with backoff, and would rather stop early with a partial, verified result than hammer
the Archive.

TWO LAYOUT TRAPS THIS HANDLES (both verified against real archived pages)
------------------------------------------------------------------------
  * COLUMN COUNT VARIES. The January 2023 bulletin has SIX country columns because it
    carries an "EL SALVADOR GUATEMALA HONDURAS" column; September 2023 onward has five.
    So columns are mapped BY HEADER TEXT, never by position. Position-mapping over a
    fixed five would silently read El Salvador's dates as India's - plausible numbers,
    wrong country, invisible to a reader. (automation/bulletin_pdf_fetch.py had exactly
    that bug; see the note there.)
  * OCTOBER THROUGH DECEMBER ARE FILED UNDER THE NEXT YEAR. The bulletin for October
    2022 lives at /visa-bulletin/2023/visa-bulletin-for-october-2022.html, because the
    site organises by FISCAL year. Asking for /2022/ returns nothing archived, which
    reads as "not available" when the page is in fact right there.

USAGE
    python3 automation/fetch_vb_history.py --check          # report gaps, write nothing
    python3 automation/fetch_vb_history.py --fill           # dry run: fetch + show
    python3 automation/fetch_vb_history.py --fill --commit  # write vb_history.json
    python3 automation/fetch_vb_history.py --month 2026-09 --commit   # one month
    python3 automation/fetch_vb_history.py --verify         # structural audit only

SAFETY
    Dry run by default. Never overwrites a month that already exists unless
    --overwrite is passed; instead it DIFFS against what is there and reports any
    disagreement, because a silent overwrite is how you lose a hand-verified value.
    Writes only after the merged result passes the same audit --verify runs.

stdlib only. No pip packages.
"""

import argparse
import datetime
import gzip
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HISTORY = os.path.join(REPO, "vb_history.json")
RULEBOOK = os.path.join(REPO, "rulebook.json")

UA = "gcnav-history-backfill/1.0 (personal learning project; archived public records)"

MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]

CATEGORIES = ["EB-1", "EB-2", "EB-3", "EB-4", "EB-5"]
COUNTRIES = ["ROW", "China", "India", "Mexico", "Philippines"]

# Row label -> category. Matched against the row's first cell, lowercased.
# "other workers" and "certain religious workers" are deliberately NOT mapped: they
# are sub-rows of EB-3 and EB-4, and the site's series track the main preference.
# EB-5 is the UNRESERVED row; the Rural / High Unemployment / Infrastructure
# set-asides created by the 2022 RIA are separate reserved pools, not the main queue.
ROW_LABEL_RULES = [
    ("EB-1", re.compile(r"^1st\b")),
    ("EB-2", re.compile(r"^2nd\b")),
    ("EB-3", re.compile(r"^3rd\b")),
    ("EB-4", re.compile(r"^4th\b")),
    ("EB-5", re.compile(r"^5th\s+unreserved")),
    ("EB-5", re.compile(r"^5th\s*$")),            # older bulletins used a bare "5th"
]

# Header cell text -> canonical country. Checked in order; first match wins, so the
# more specific patterns come first.
HEADER_RULES = [
    ("China", re.compile(r"china", re.I)),
    ("India", re.compile(r"india", re.I)),
    ("Mexico", re.compile(r"mexico", re.I)),
    ("Philippines", re.compile(r"philippin", re.I)),
    # "All Chargeability Areas Except Those Listed" is the rest-of-world column.
    ("ROW", re.compile(r"all\s+chargeability", re.I)),
]

_MON3 = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
         "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_DDMONYY = re.compile(r"^\s*(\d{1,2})\s*([A-Z]{3})\s*(\d{2})\s*$", re.I)


# ---------------------------------------------------------------------------
# month helpers
# ---------------------------------------------------------------------------
def ym_str(y, m):
    return "%04d-%02d" % (y, m)


def parse_ym(s):
    y, m = s.split("-")
    return int(y), int(m)


def month_range(a, b):
    """Inclusive list of YYYY-MM from a to b."""
    y, m = parse_ym(a)
    by, bm = parse_ym(b)
    out = []
    while (y, m) <= (by, bm):
        out.append(ym_str(y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def prev_month(s):
    y, m = parse_ym(s)
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return ym_str(y, m)


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------
class Fetcher(object):
    """Polite HTTP with gzip handling, retry/backoff, and a hard request budget.

    archive.org rate-limits aggressively. Exceeding the budget stops the run rather
    than retrying forever: a partial, verified backfill is a fine outcome, and the
    script is resumable because it re-derives the gap list from the file each time.
    """

    def __init__(self, budget=400, pause=1.6, verbose=False):
        self.budget = budget
        self.pause = pause
        self.verbose = verbose
        self.used = 0
        self.last = 0.0

    def get(self, url, timeout=90, tries=3):
        if self.used >= self.budget:
            raise RuntimeError("request budget of %d exhausted" % self.budget)
        delay = self.pause
        for attempt in range(1, tries + 1):
            gap = time.time() - self.last
            if gap < self.pause:
                time.sleep(self.pause - gap)
            self.used += 1
            self.last = time.time()
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "gzip",
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            })
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < tries:
                    if self.verbose:
                        sys.stderr.write("    HTTP %s, backing off %.0fs\n" % (e.code, delay * 3))
                    time.sleep(delay * 3)
                    delay *= 2
                    continue
                raise
            except Exception:
                if attempt < tries:
                    time.sleep(delay * 2)
                    delay *= 2
                    continue
                raise
        raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# official URL + wayback lookup
# ---------------------------------------------------------------------------
def official_url(ym):
    """The official bulletin page URL for a YYYY-MM.

    NOTE the fiscal-year directory: October, November and December are filed under
    the FOLLOWING calendar year, because the site organises by fiscal year. Getting
    this wrong makes those three months look unarchived when they are not.
    """
    y, m = parse_ym(ym)
    diry = y + 1 if m >= 10 else y
    return ("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/"
            "%d/visa-bulletin-for-%s-%d.html" % (diry, MONTH_NAMES[m - 1], y))


def rows_from_pdf(path):
    """Read a locally-downloaded bulletin PDF into the same rows shape as a fetch.

    This is the route for the CURRENT month. The Internet Archive lags publication by
    roughly three to four weeks, so the newest bulletin is reliably NOT archived yet -
    verified: September 2026 has no snapshot while every FY2023 month has several. A
    human can open the PDF (Cloudflare passes in a real browser), save it, and this
    turns it into history rows with no transcription.
    """
    sys.path.insert(0, HERE)
    import bulletin_pdf_fetch as pdf

    parsed = pdf.parse_pdf(path)
    cols = parsed.pop("_columns", {})
    for bad in parsed.pop("_unreadable_rows", []):
        sys.stderr.write("  WARNING unreadable %s row (%d tokens for %d columns): %s\n"
                         % (bad["category"], bad["found"], bad["expected"], bad["line"]))
    rows = {}
    for cat in CATEGORIES:
        cell = parsed.get(cat) or {}
        for country in COUNTRIES:
            v = cell.get(country) or {}
            rows["%s|%s" % (cat, country)] = {
                "fad": v.get("final_action_date"),
                "dff": v.get("date_for_filing"),
            }
    # Refuse a parse that produced nothing usable rather than writing a month of nulls,
    # which would look like a real "Unavailable" everywhere on the heatmap.
    if not any(v["fad"] is not None or v["dff"] is not None for v in rows.values()):
        raise RuntimeError("parsed no usable values from %s (columns seen: %s)"
                           % (path, cols))
    return rows, cols


def wayback_snapshots(fetcher, url, limit=6):
    """Newest-first list of raw snapshot URLs that returned 200."""
    cdx = ("https://web.archive.org/cdx/search/cdx?url=%s&output=json&limit=%d"
           "&filter=statuscode:200&collapse=digest"
           % (urllib.parse.quote(url, safe=""), limit))
    try:
        rows = json.loads(fetcher.get(cdx, timeout=60))
    except Exception as exc:
        raise RuntimeError("CDX lookup failed: %s" % exc)
    if len(rows) < 2:
        return []
    stamps = [r[1] for r in rows[1:]]
    # `id_` asks the Archive for the ORIGINAL bytes with no injected toolbar, which
    # keeps the markup identical to what the government served.
    return ["https://web.archive.org/web/%sid_/%s" % (ts, url) for ts in reversed(stamps)]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def _cell_text(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment)
    t = htmllib.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _tables(page):
    for tb in re.findall(r"<table[^>]*>.*?</table>", page, re.S | re.I):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S | re.I)
        grid = []
        for r in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)
            if cells:
                grid.append([_cell_text(c) for c in cells])
        if grid:
            yield grid


def _is_employment_table(grid):
    firsts = [row[0].strip().lower() for row in grid if row]
    return any(f.startswith("1st") for f in firsts) and \
           any(f.startswith("2nd") for f in firsts)


def _column_map(header_row):
    """Map column INDEX -> canonical country, using the header text.

    Never positional. The El Salvador/Guatemala/Honduras column appears in some
    months and not others, so a fixed offset silently shifts every country right.
    Unrecognised columns (like that one) are simply left out of the map.
    """
    colmap = {}
    for idx, cell in enumerate(header_row):
        if idx == 0:
            continue  # the row-label column
        for country, pat in HEADER_RULES:
            if pat.search(cell):
                if country not in colmap.values():
                    colmap[idx] = country
                break
    return colmap


def _category_for(label):
    lab = label.strip().lower()
    for cat, pat in ROW_LABEL_RULES:
        if pat.search(lab):
            return cat
    return None


def token_to_value(tok):
    """Bulletin cell -> the shape vb_history.json uses.

    "C" -> "CURRENT"   (no backlog)
    "U" -> None        (unavailable: no cutoff published)
    "01NOV22" -> "2022-11-01"
    anything else -> None, treated as no data rather than guessed at.
    """
    t = (tok or "").strip().upper().replace(".", "")
    if not t:
        return None
    if t in ("C", "CURRENT"):
        return "CURRENT"
    if t in ("U", "UNAVAILABLE"):
        return None
    m = _DDMONYY.match(t)
    if m:
        dd, mon, yy = m.group(1), m.group(2).upper(), m.group(3)
        if mon in _MON3:
            return "%04d-%02d-%02d" % (2000 + int(yy), _MON3[mon], int(dd))
    return None


def parse_employment_charts(page):
    """Return {"fad": {cat: {country: value}}, "dff": {...}} from a bulletin page.

    The two employment tables appear in document order: chart A (Final Action Dates)
    then chart B (Dates for Filing). Verified against archived pages for 2023 and
    2025-2026. Sanity-checked below by the caller.
    """
    emp = [g for g in _tables(page) if _is_employment_table(g)]
    if len(emp) < 2:
        raise ValueError("found %d employment tables, expected 2" % len(emp))
    out = {}
    for name, grid in (("fad", emp[0]), ("dff", emp[1])):
        colmap = _column_map(grid[0])
        missing = [c for c in COUNTRIES if c not in colmap.values()]
        if missing:
            raise ValueError("%s table: could not locate column(s) %s in header %r"
                             % (name, missing, grid[0]))
        cats = {}
        for row in grid[1:]:
            cat = _category_for(row[0])
            if not cat or cat in cats:
                continue  # first occurrence only
            vals = {}
            for idx, country in colmap.items():
                vals[country] = token_to_value(row[idx]) if idx < len(row) else None
            cats[cat] = vals
        out[name] = cats
    return out


# ---------------------------------------------------------------------------
# history file
# ---------------------------------------------------------------------------
def load_history():
    with open(HISTORY, encoding="utf-8") as fh:
        return json.load(fh)


def series_keys():
    return ["%s|%s" % (c, k) for c in CATEGORIES for k in COUNTRIES]


def audit(hist):
    """Structural audit. Returns (problems, info)."""
    problems, info = [], {}
    present = {}
    for key in series_keys():
        if key not in hist:
            problems.append("series %s is absent entirely" % key)
            continue
        months = [r["month"] for r in hist[key]]
        present[key] = months
        if months != sorted(months):
            problems.append("series %s is not in month order" % key)
        dupes = sorted(set(m for m in months if months.count(m) > 1))
        if dupes:
            problems.append("series %s has duplicate month(s): %s" % (key, ", ".join(dupes)))
        for r in hist[key]:
            for f in ("fad", "dff"):
                v = r.get(f)
                if not (v is None or v == "CURRENT" or
                        (isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v))):
                    problems.append("series %s month %s: %s has odd value %r"
                                    % (key, r["month"], f, v))
    if not present:
        return problems, info

    lengths = set(len(v) for v in present.values())
    if len(lengths) > 1:
        problems.append("series have differing lengths: %s" % sorted(lengths))
    lows = sorted(v[0] for v in present.values())
    highs = sorted(v[-1] for v in present.values())
    info["first"], info["last"] = lows[0], highs[-1]
    span = month_range(info["first"], info["last"])
    info["expected"] = len(span)
    gaps = set()
    for key, months in present.items():
        have = set(months)
        for m in span:
            if m not in have:
                gaps.add(m)
    info["gaps"] = sorted(gaps)
    if gaps:
        problems.append("%d month(s) missing from at least one series: %s"
                        % (len(gaps), ", ".join(sorted(gaps))))
    return problems, info


def rulebook_latest_month():
    """The bulletin month the REST of the site is already showing."""
    try:
        with open(RULEBOOK, encoding="utf-8") as fh:
            rb = json.load(fh)
        return rb.get("bulletin", {}).get("as_of")
    except Exception:
        return None


def missing_months(hist):
    """Interior gaps PLUS any month between the tail and what the rulebook shows.

    Both halves matter. An interior gap draws a year that never happened; a lagging
    tail makes one page show two different "latest" months.
    """
    _, info = audit(hist)
    out = list(info.get("gaps", []))
    last = info.get("last")
    rb = rulebook_latest_month()
    if last and rb and rb > last:
        for m in month_range(last, rb)[1:]:
            if m not in out:
                out.append(m)
    return sorted(out)


# ---------------------------------------------------------------------------
# fetch one month
# ---------------------------------------------------------------------------
def fetch_month(fetcher, ym, verbose=False):
    """-> ({series_key: {"fad":v,"dff":v}}, note) or raises."""
    url = official_url(ym)
    snaps = wayback_snapshots(fetcher, url)
    if not snaps:
        raise RuntimeError("no archived snapshot of %s" % url)
    last_err = None
    for snap in snaps:
        try:
            page = fetcher.get(snap)
            charts = parse_employment_charts(page)
        except Exception as exc:
            last_err = exc
            if verbose:
                sys.stderr.write("    snapshot rejected (%s)\n" % exc)
            continue
        # Sanity: the two charts must not be byte-identical across every cell. If they
        # are, we almost certainly grabbed the same table twice and the "dff" values
        # are fiction.
        if charts["fad"] == charts["dff"]:
            last_err = ValueError("both employment tables parsed identically")
            continue
        rows = {}
        for cat in CATEGORIES:
            fad_row = charts["fad"].get(cat)
            dff_row = charts["dff"].get(cat)
            if fad_row is None and dff_row is None:
                continue
            for country in COUNTRIES:
                rows["%s|%s" % (cat, country)] = {
                    "fad": (fad_row or {}).get(country),
                    "dff": (dff_row or {}).get(country),
                }
        if not rows:
            last_err = ValueError("no categories parsed")
            continue
        return rows, snap
    raise RuntimeError("all snapshots failed for %s (last: %s)" % (ym, last_err))


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------
def merge_month(hist, ym, rows, overwrite=False):
    """Insert a month in order. Returns (added, conflicts)."""
    added, conflicts = 0, []
    for key, vals in rows.items():
        series = hist.setdefault(key, [])
        idx = next((i for i, r in enumerate(series) if r["month"] == ym), None)
        entry = {"month": ym, "fad": vals["fad"], "dff": vals["dff"]}
        if idx is None:
            pos = 0
            while pos < len(series) and series[pos]["month"] < ym:
                pos += 1
            series.insert(pos, entry)
            added += 1
        else:
            cur = series[idx]
            if cur.get("fad") != entry["fad"] or cur.get("dff") != entry["dff"]:
                conflicts.append((key, ym, dict(cur), entry))
                if overwrite:
                    series[idx] = entry
    return added, conflicts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_check(hist):
    problems, info = audit(hist)
    print("vb_history.json audit")
    print("  series          : %d" % len([k for k in series_keys() if k in hist]))
    if info:
        print("  range           : %s -> %s" % (info.get("first"), info.get("last")))
        print("  months expected : %d" % info.get("expected", 0))
    rb = rulebook_latest_month()
    print("  rulebook shows  : %s" % rb)
    if rb and info.get("last") and rb > info["last"]:
        print("  TAIL LAG        : the rest of the site shows %s, these series stop at %s"
              % (rb, info["last"]))
    miss = missing_months(hist)
    if miss:
        print("\n  MISSING %d month(s):" % len(miss))
        for m in miss:
            print("      %s   %s" % (m, official_url(m)))
    else:
        print("\n  No missing months.")
    if problems:
        print("\n  problems:")
        for p in problems:
            print("    - %s" % p)
    return 1 if (problems or miss) else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report gaps and exit")
    ap.add_argument("--verify", action="store_true", help="structural audit only")
    ap.add_argument("--fill", action="store_true", help="fetch every missing month")
    ap.add_argument("--month", metavar="YYYY-MM", action="append",
                    help="fetch just this month (repeatable)")
    ap.add_argument("--commit", action="store_true", help="write the file (default: dry run)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace existing months on conflict instead of only reporting")
    ap.add_argument("--from-pdf", metavar="PDF", dest="from_pdf",
                    help="read a locally-downloaded bulletin PDF instead of the Archive "
                         "(use with --month; the newest bulletin is not archived yet)")
    ap.add_argument("--budget", type=int, default=400, help="max HTTP requests")
    ap.add_argument("--pause", type=float, default=1.6, help="seconds between requests")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    hist = load_history()

    if args.verify:
        problems, info = audit(hist)
        if problems:
            print("FAILED: %d problem(s)" % len(problems))
            for p in problems:
                print("  - %s" % p)
            return 1
        print("verified: %d series, %s -> %s, %d months each, no gaps or duplicates"
              % (len([k for k in series_keys() if k in hist]),
                 info.get("first"), info.get("last"), info.get("expected", 0)))
        return 0

    if args.check or not (args.fill or args.month):
        return cmd_check(hist)

    targets = args.month if args.month else missing_months(hist)
    if not targets:
        print("Nothing to fetch: no missing months.")
        return 0

    if args.from_pdf and len(targets) != 1:
        print("--from-pdf takes exactly one --month (a PDF is one bulletin).",
              file=sys.stderr)
        return 2

    print("%d month(s) to fetch%s\n" % (len(targets), "" if args.commit else "   (DRY RUN)"))
    fetcher = Fetcher(budget=args.budget, pause=args.pause, verbose=args.verbose)
    total_added, all_conflicts, failed = 0, [], []
    for ym in targets:
        try:
            if args.from_pdf:
                rows, cols = rows_from_pdf(args.from_pdf)
                print("  (from PDF %s; columns detected: %s)"
                      % (os.path.basename(args.from_pdf),
                         ", ".join(cols.get("final_action") or [])))
            else:
                rows, _snap = fetch_month(fetcher, ym, verbose=args.verbose)
        except Exception as exc:
            failed.append((ym, str(exc)))
            print("  %s  FAILED: %s" % (ym, exc))
            continue
        added, conflicts = merge_month(hist, ym, rows, overwrite=args.overwrite)
        total_added += added
        all_conflicts.extend(conflicts)
        sample = rows.get("EB-2|India", {})
        print("  %s  %2d series   EB-2 India fad=%s dff=%s"
              % (ym, len(rows), sample.get("fad"), sample.get("dff")))

    if all_conflicts:
        print("\n%d CONFLICT(S) with values already in the file "
              "(not written unless --overwrite):" % len(all_conflicts))
        for key, ym, cur, new in all_conflicts[:15]:
            print("    %-18s %s  have fad=%s dff=%s   archived fad=%s dff=%s"
                  % (key, ym, cur.get("fad"), cur.get("dff"), new["fad"], new["dff"]))

    print("\n%d series-month row(s) added, %d request(s) used" % (total_added, fetcher.used))
    if failed:
        print("%d month(s) failed: %s" % (len(failed), ", ".join(m for m, _ in failed)))

    if not args.commit:
        print("Dry run: nothing written. Re-run with --commit.")
        return 0
    if not total_added and not (args.overwrite and all_conflicts):
        print("Nothing to write.")
        return 0

    problems, info = audit(hist)
    if problems:
        print("\nREFUSING TO WRITE: the merged result does not pass its own audit:")
        for p in problems[:12]:
            print("  - %s" % p)
        return 1

    with open(HISTORY, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("wrote %s" % HISTORY)
    print("verified: %s -> %s, %d months per series, no gaps"
          % (info.get("first"), info.get("last"), info.get("expected", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
