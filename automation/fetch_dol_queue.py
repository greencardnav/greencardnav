#!/usr/bin/env python3
"""
fetch_dol_queue.py - answers ONE question: where is the DOL queue right now?

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
Standalone weekly fetcher, in the same shape as fetch_feeds.py: it talks to ONE
source that was verified to serve a plain stdlib client, parses numbers
deterministically, and writes a small committed JSON artifact
(automation/dol_queue.json) that the static site reads with no backend. It does
NOT touch rulebook.json, faq.html, or the search index, and it has no LLM step.

The site references flag.dol.gov 28 times but ingested zero numbers from it. This
closes that gap. Everything it emits comes from ONE page:

    https://flag.dol.gov/processingtimes

which is the U.S. Department of Labor, Office of Foreign Labor Certification
(OFLC) processing-times page. It answers the three things people actually hunt
for:

  1. WHICH MONTH OF PERM APPLICATIONS IS DOL ADJUDICATING?
     From the "PERM Processing Times" table: the priority-date month currently in
     Analyst Review, in Audit Review, and in Reconsideration.
  2. THE SAME FOR PREVAILING WAGE DETERMINATIONS (ETA-9141).
     From the "Prevailing Wage Determination Processing Times" table: the receipt
     month being worked, split by OEWS vs non-OEWS wage source, for the PERM /
     H-1B / H-2B / CW-1 queues, plus Redeterminations and Center Director Reviews.
  3. A QUEUE / BACKLOG FIGURE.
     From the per-queue "Remaining Requests" tables: pending ETA-9141 requests
     broken out by receipt month, and their total.

Plus "Average Number of Days to Process PERM Applications" (calendar days), which
is the closest thing DOL publishes to an end-to-end PERM timeline.

WHY flag.dol.gov DIRECTLY, AND WHY THAT IS NOT A BYPASS
-------------------------------------------------------
RUNBOOK.md forbids fetching the Cloudflare-walled origins: uscis.gov and
travel.state.gov 403 a scripted client, so those go through archive.org instead.
flag.dol.gov is NOT in that category. Verified 2026-09-02: a plain urllib client
with an honest User-Agent gets HTTP 200 and the full 160 KB page, with or without
a UA header - there is no challenge to defeat. flag.dol.gov/robots.txt allows
/processingtimes (it disallows only /core/, /profiles/, /admin/, /search/,
/user/*, /node/add/, /comment/reply/, /filter/tips, /README.txt, /web.config) and
sets no Crawl-delay. One GET per week is well inside courtesy.

We still never spoof a browser. If the direct read ever fails, the fallback is
the Wayback Machine (archive.org CDX + snapshot, gzip-aware), the same
legitimate-public-mirror route wayback_fetch.py uses for the bulletin PDF - not a
stealth client.

HONEST BOUNDARY (read this)
---------------------------
* There is NO JSON endpoint behind this page. Verified: the only
  application/json on it is Drupal's own settings blob (path/pluralDelimiter/
  suppressDeprecationErrors/user - no data), and the page contains no /api/,
  no views_ajax, and no .json / .csv / .xlsx link. The numbers live in 14 plain
  server-rendered HTML <table> elements. So this is an HTML parse by necessity,
  not by choice.
* The parse is anchored on STABLE TEXT, never on table position: the section's
  <strong> title, the <caption>, and the column-header text. If DOL reorders,
  renames, or drops a section, the affected field becomes null with a recorded
  reason instead of silently picking up the wrong table. A parser that guessed
  "the 6th table" would happily publish an H-2B number as a PERM number.
* NOTHING IS EVER FABRICATED. Every figure is either read off the page or emitted
  as null with a human-readable reason in `notes`. A gauge showing an invented
  month is worse than no gauge.
* DOL's OWN as-of dates are per-section and can lag badly. Observed 2026-09-02:
  the PERM table was as of 2026-08-28 (5 days old) while the prevailing-wage
  table was still as of 2026-06-30 - about two months stale, despite the page's
  own schedule promising a monthly PWD update. Both `as_of` dates are emitted
  verbatim so the page can show the real age. Do NOT present a stale figure as
  today's queue.
* The H-2A, H-2B and CW-1 application-processing sections (NOA/NOD issuance,
  per-filing-window case counts, CW-1 case types) are deliberately NOT parsed.
  They are seasonal / territorial nonimmigrant programs, out of scope for an
  employment-based green card site. The PWD tables DO include the H-1B / H-2B /
  CW-1 wage queues, because they are rows of the same PERM table.
* This is a MIRROR, not an authority. DOL's page is the record. The
  `source_note` string exists to be displayed verbatim next to the numbers.
* Age is NOT precomputed here. `as_of_age_days` would change every day even when
  upstream did not, which would defeat idempotency (see below). The front end
  computes age from `as_of` against today.

IDEMPOTENCY
-----------
Running twice against unchanged upstream data produces a BYTE-IDENTICAL file, so
the weekly job never commits noise. Mechanism: `content_digest` is a sha256 over
the canonical JSON of the payload EXCLUDING the timestamp fields. On write, if the
file already on disk carries the same digest, its existing `fetched_at` is
preserved and the file is rewritten identically. So `fetched_at` means "when this
exact content was FIRST observed", not "when the job last ran". The record of
"last checked" is the workflow run history, deliberately not this file.

FAILURE BEHAVIOUR
-----------------
Field-level parse failure -> null + a reason in `notes`, everything else still
written. Total fetch failure (direct AND Wayback) -> the existing file is left
UNTOUCHED and the run exits non-zero, so the site keeps serving the last known
good numbers (with their real age) rather than blanking the gauge.

Exit codes: 0 = wrote (or confirmed unchanged). 3 = could not fetch the page at
all, existing file left alone. 4 = fetched but not one figure parsed.

Usage:
  python3 automation/fetch_dol_queue.py [--out automation/dol_queue.json]
                                        [--html-file PATH] [--now ISO8601]
                                        [--no-wayback] [--verbose]

stdlib only: urllib.request, json, re, html, gzip, hashlib, datetime, argparse,
pathlib, sys.

Personal-learning project. NOT legal advice, NOT official guidance.
"""

import argparse
import datetime
import gzip
import hashlib
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

SOURCE_URL = "https://flag.dol.gov/processingtimes"

# Descriptive User-Agent = client courtesy (identify the client + purpose), NOT
# evasion. Same posture as fetch_feeds.py: we never spoof a browser and never
# defeat a challenge. flag.dol.gov does not present one.
USER_AGENT = ("GreenCardNavigator-DOLQueue/1.0 "
              "(personal educational project; read-only)")
TIMEOUT_SECONDS = 30

# Wayback fallback, used ONLY if the direct read fails. Same public-mirror route
# as wayback_fetch.py. The CDX query asks for the last few distinct-content
# 200-status captures; `id_` on the snapshot URL returns the captured bytes
# without archive.org's toolbar rewriting.
CDX_API = "http://web.archive.org/cdx/search/cdx"
WAYBACK_SNAPSHOT = "http://web.archive.org/web/%sid_/%s"
# archive.org's CDX index is routinely far slower than the origin it mirrors
# (measured: a 30s timeout was not enough), so the fallback gets its own, longer
# budget. This never delays the normal path — it is only reached if the direct
# read already failed.
WAYBACK_TIMEOUT_SECONDS = 120

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Cell values DOL uses to mean "nothing here". Treated as null, never as zero -
# "--" in a Remaining Requests column is not the number 0.
_EMPTY_CELL_VALUES = frozenset(["", "--", "-", "n/a", "na", "none", "tbd"])

# The wage queues that appear as rows of the prevailing-wage tables. Order is
# fixed so output is stable regardless of DOL's row order.
PWD_QUEUES = ("PERM", "H-1B", "H-2B", "CW-1")

# The three PERM review stages DOL publishes a priority-date month for. Keys are
# our stable field names; values are the label text to match on the page.
PERM_STAGES = (
    ("analyst_review", "analyst review"),
    ("audit_review", "audit review"),
    ("reconsideration", "reconsideration"),
)


def log(msg, verbose):
    if verbose:
        sys.stderr.write("[fetch_dol_queue] %s\n" % msg)


def http_get(url, verbose, timeout=TIMEOUT_SECONDS):
    """GET a URL with a descriptive UA and a short timeout. Returns bytes.
    Raises on any failure so the caller can fall back or record the reason."""
    log("GET %s" % url, verbose)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        # Ask for identity so we are not handed a gzip stream we then have to
        # sniff. Wayback ignores this, which is why decode_body() still checks.
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def decode_body(raw):
    """Bytes -> text. Raw Wayback snapshots are sometimes served gzipped
    regardless of the request headers, so sniff the gzip magic number first."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Fetch: direct first, Wayback only as a fallback.
# ---------------------------------------------------------------------------
def fetch_wayback(url, verbose):
    """Return (text, snapshot_timestamp) for the most recent distinct-content
    200 capture of `url`, or (None, None). Public mirror, no bypass."""
    q = "%s?%s" % (CDX_API, urllib.parse.urlencode({
        "url": url,
        "output": "json",
        "fl": "timestamp,digest",
        "filter": "statuscode:200",
        "collapse": "digest",
        "limit": "-5",          # the newest 5, newest last
    }))
    rows = json.loads(decode_body(
        http_get(q, verbose, timeout=WAYBACK_TIMEOUT_SECONDS)))
    # First row is the header ["timestamp","digest"]; drop it.
    stamps = [r[0] for r in rows[1:] if r and r[0]]
    if not stamps:
        return None, None
    for ts in reversed(stamps):     # newest first
        try:
            body = decode_body(http_get(WAYBACK_SNAPSHOT % (ts, url), verbose,
                                        timeout=WAYBACK_TIMEOUT_SECONDS))
        except Exception as exc:  # noqa: BLE001 - try the next-older capture
            log("wayback snapshot %s failed: %s" % (ts, exc), verbose)
            continue
        if len(body) > 5000:        # a truncated/error capture is not usable
            return body, ts
    return None, None


def fetch_page(html_file, allow_wayback, verbose):
    """Return (text, provenance_dict). Raises RuntimeError if nothing worked."""
    if html_file:
        text = Path(html_file).read_text(encoding="utf-8", errors="replace")
        return text, {"path": "local-file", "detail": str(html_file)}

    try:
        text = decode_body(http_get(SOURCE_URL, verbose))
        return text, {"path": "direct", "detail": SOURCE_URL}
    except Exception as exc:  # noqa: BLE001 - fall back, never hammer or spoof
        log("direct fetch FAILED (%s)" % exc, verbose)
        direct_error = str(exc)

    if not allow_wayback:
        raise RuntimeError("direct fetch failed (%s) and --no-wayback was set"
                           % direct_error)
    try:
        text, ts = fetch_wayback(SOURCE_URL, verbose)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("direct fetch failed (%s); Wayback also failed (%s)"
                           % (direct_error, exc))
    if not text:
        raise RuntimeError("direct fetch failed (%s); no usable Wayback capture"
                           % direct_error)
    return text, {"path": "wayback", "detail":
                  "archive.org capture %s of %s" % (ts, SOURCE_URL),
                  "snapshot_timestamp": ts}


# ---------------------------------------------------------------------------
# Minimal, dependency-free HTML table reader. Only what this page needs.
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"</(?:p|div|li|br)\s*>|<br\s*/?>", re.I)


def cell_text(fragment):
    """Tag-stripped, entity-decoded, whitespace-collapsed text of one cell.
    Block-level ends become newlines FIRST, because the Redeterminations and
    Center Director Reviews cells pack several labelled values into one <td> as
    separate <p> elements - collapsing those blindly would fuse
    'H-1B: April 2026' and 'PERM: April 2026' into one unreadable string."""
    s = _BLOCK_END_RE.sub("\n", fragment or "")
    s = _TAG_RE.sub("", s)
    s = html_mod.unescape(s).replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def flat_text(fragment):
    """Like cell_text but on one line (for captions and header cells)."""
    return " ".join(cell_text(fragment).split())


def parse_tables(page_html):
    """Return a list of dicts: {offset, caption, headers[], rows[[cell,...]]}.

    `headers` is every <th> in the table flattened to one line (the page uses
    two header rows on the Remaining Requests tables: a colspan-2 queue name,
    then the real column labels). `rows` is every <tr> that contains a <td>."""
    tables = []
    for m in re.finditer(r"<table\b.*?</table>", page_html, re.S | re.I):
        block = m.group(0)
        cap_m = re.search(r"<caption\b[^>]*>(.*?)</caption>", block, re.S | re.I)
        headers = [flat_text(h) for h in
                   re.findall(r"<th\b[^>]*>(.*?)</th>", block, re.S | re.I)]
        rows = []
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", block, re.S | re.I):
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S | re.I)
            if cells:
                rows.append([cell_text(c) for c in cells])
        tables.append({
            "offset": m.start(),
            "caption": flat_text(cap_m.group(1)) if cap_m else "",
            "headers": headers,
            "rows": rows,
        })
    return tables


def find_table(tables, *, caption_prefix=None, needs_headers=None):
    """First table matching a caption prefix and/or required header substrings.
    Anchored on DOL's own text, never on table index - see HONEST BOUNDARY."""
    for t in tables:
        if caption_prefix:
            if not t["caption"].lower().startswith(caption_prefix.lower()):
                continue
        if needs_headers:
            joined = " | ".join(t["headers"]).lower()
            if not all(h.lower() in joined for h in needs_headers):
                continue
        return t
    return None


# ---------------------------------------------------------------------------
# Value normalizers. Every one returns None rather than a guess.
# ---------------------------------------------------------------------------
def is_empty_cell(raw):
    return (raw or "").strip().strip(".").lower() in _EMPTY_CELL_VALUES


def norm_month(raw):
    """'November 2025' -> '2025-11'. Returns None for '--', 'N/A', or anything
    that is not a recognizable Month YYYY. Never guesses a month."""
    if not raw or is_empty_cell(raw):
        return None
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{4})\b", raw)
    if not m:
        return None
    month = MONTHS.get(m.group(1).lower())
    if month is None:
        # Accept 3-letter abbreviations ('Sep 2026') by prefix match.
        pref = m.group(1).lower()[:3]
        matches = [v for k, v in MONTHS.items() if k.startswith(pref)]
        if len(matches) != 1:
            return None
        month = matches[0]
    year = int(m.group(2))
    if not (1990 <= year <= 2100):
        return None
    return "%04d-%02d" % (year, month)


def norm_int(raw):
    """'14,386' -> 14386. '--' / 'N/A' / '' -> None (never 0)."""
    if not raw or is_empty_cell(raw):
        return None
    m = re.search(r"-?\d[\d,]*", raw)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def norm_date(raw):
    """'8/28/2026' or '08/29/2026' -> '2026-08-28'. None if unparseable."""
    if not raw:
        return None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", raw)
    if not m:
        return None
    mo, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime.date(year, mo, day).isoformat()
    except ValueError:
        return None


def month_label(iso_month):
    """'2025-11' -> 'November 2025', for display without re-parsing in JS."""
    if not iso_month:
        return None
    try:
        y, m = iso_month.split("-")
        return "%s %s" % (datetime.date(int(y), int(m), 1).strftime("%B"), y)
    except (ValueError, TypeError):
        return None


def month_field(raw, notes, field_name):
    """Build the {iso, label, raw} triple every month figure uses, recording a
    reason in `notes` when the page had no usable value."""
    iso = norm_month(raw)
    if iso is None:
        notes.append("%s is null: DOL published %r, which is not a "
                     "'Month YYYY' value." % (field_name, (raw or "").strip()))
    return {"month": iso, "month_label": month_label(iso),
            "raw": (raw or "").strip() or None}


# ---------------------------------------------------------------------------
# Section extractors. Each is independently guarded: one dead section leaves the
# others intact, exactly like the per-source try/except in fetch_feeds.py.
# ---------------------------------------------------------------------------
_PWD_ASOF_RE = re.compile(
    r"Prevailing\s+Wage\s+Determination\s+Processing\s+Times.{0,200}?"
    r"\(\s*as of\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*\)",
    re.S | re.I)


def extract_prevailing_wage(page_html, tables, notes):
    """The ETA-9141 side: which receipt month each wage queue is working, plus
    Redeterminations / Center Director Reviews, plus the pending-request
    backlog per queue."""
    out = {
        "as_of": None, "as_of_raw": None,
        "queues": {}, "redeterminations": {}, "center_director_reviews": {},
        "pending_requests": {},
    }

    m = _PWD_ASOF_RE.search(page_html)
    if m:
        out["as_of_raw"] = m.group(1)
        out["as_of"] = norm_date(m.group(1))
    else:
        notes.append("prevailing_wage.as_of is null: could not find the "
                     "'Prevailing Wage Determination Processing Times "
                     "(as of ...)' heading on the page.")

    # --- receipt-date table: header text is the anchor, not position ---
    recv = find_table(tables, needs_headers=["Processing Queue",
                                             "OEWS Receipt Date"])
    if recv is None:
        notes.append("prevailing_wage.queues is empty: no table with "
                     "'Processing Queue' + 'OEWS Receipt Date' headers was "
                     "found (DOL may have restructured the page).")
    else:
        for row in recv["rows"]:
            if not row:
                continue
            label = row[0].strip()
            key = label.upper()
            if key in PWD_QUEUES:
                oews = row[1] if len(row) > 1 else ""
                non_oews = row[2] if len(row) > 2 else ""
                out["queues"][key] = {
                    "oews_receipt": month_field(
                        oews, notes, "prevailing_wage.queues.%s.oews_receipt" % key),
                    "non_oews_receipt": month_field(
                        non_oews, notes,
                        "prevailing_wage.queues.%s.non_oews_receipt" % key),
                }
            elif label.lower().startswith("redetermination"):
                out["redeterminations"] = _split_labelled_cell(
                    row[1] if len(row) > 1 else "")
            elif label.lower().startswith("center director"):
                out["center_director_reviews"] = _split_labelled_cell(
                    row[1] if len(row) > 1 else "")
        missing = [q for q in PWD_QUEUES if q not in out["queues"]]
        if missing:
            notes.append("prevailing_wage.queues is missing %s: those rows were "
                         "not present in DOL's receipt-date table."
                         % ", ".join(missing))

    # --- per-queue backlog tables: 'Remaining Requests' is the anchor ---
    for t in tables:
        joined = " | ".join(t["headers"]).lower()
        if "remaining requests" not in joined or "receipt month" not in joined:
            continue
        queue = None
        for h in t["headers"]:
            if h.strip().upper() in PWD_QUEUES:
                queue = h.strip().upper()
                break
        if queue is None:
            notes.append("A 'Remaining Requests' table was skipped: its queue "
                         "name header was not one of %s."
                         % ", ".join(PWD_QUEUES))
            continue
        by_month = []
        for row in t["rows"]:
            if len(row) < 2:
                continue
            iso = norm_month(row[0])
            if iso is None:
                continue    # a total/footnote row, not a receipt month
            by_month.append({"month": iso, "month_label": month_label(iso),
                             "remaining_requests": norm_int(row[1]),
                             "raw": row[1].strip() or None})
        counted = [e["remaining_requests"] for e in by_month
                   if e["remaining_requests"] is not None]
        # Only total when every listed month parsed - a partial sum published as
        # a total would understate the backlog, which is worse than no total.
        total = sum(counted) if by_month and len(counted) == len(by_month) else None
        if by_month and total is None:
            notes.append("prevailing_wage.pending_requests.%s.total_remaining_"
                         "requests is null: %d of %d monthly rows did not parse "
                         "as a number, so no total is published."
                         % (queue, len(by_month) - len(counted), len(by_month)))
        out["pending_requests"][queue] = {
            "by_receipt_month": by_month,
            "total_remaining_requests": total,
        }
    if not out["pending_requests"]:
        notes.append("prevailing_wage.pending_requests is empty: no "
                     "'Receipt Month' + 'Remaining Requests' table was found.")
    return out


def _split_labelled_cell(raw):
    """'H-1B: April 2026\\nPERM: April 2026' -> {'H-1B': {...}, 'PERM': {...}}.
    Values that are not a Month YYYY (DOL writes 'N/A') come back as null."""
    result = {}
    for line in (raw or "").split("\n"):
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label = label.strip().upper()
        if not label:
            continue
        iso = norm_month(value)
        result[label] = {"month": iso, "month_label": month_label(iso),
                         "raw": value.strip() or None}
    return result


def extract_perm(tables, notes):
    """The PERM side: the priority-date month in each review stage, and DOL's
    published average calendar days to a determination."""
    out = {
        "as_of": None, "as_of_raw": None,
        "stages": {},
        "average_calendar_days": {},
    }

    prio = find_table(tables, caption_prefix="PERM Processing Times")
    if prio is None:
        notes.append("perm.stages is empty: no table captioned 'PERM Processing "
                     "Times' was found (DOL may have renamed the section).")
    else:
        m = re.search(r"\(\s*as of\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\s*\)",
                      prio["caption"], re.I)
        if m:
            out["as_of_raw"] = m.group(1)
            out["as_of"] = norm_date(m.group(1))
        else:
            notes.append("perm.as_of is null: the 'PERM Processing Times' "
                         "caption did not carry an '(as of M/D/YYYY)' date.")
        labelled = {}
        for row in prio["rows"]:
            if len(row) >= 2 and row[0].strip():
                labelled[row[0].strip().lower()] = row[1]
        for key, needle in PERM_STAGES:
            match = next((v for k, v in labelled.items() if needle in k), None)
            if match is None:
                notes.append("perm.stages.%s is null: no row matching %r in "
                             "DOL's PERM Processing Times table."
                             % (key, needle))
                out["stages"][key] = {"month": None, "month_label": None,
                                      "raw": None}
            else:
                out["stages"][key] = month_field(
                    match, notes, "perm.stages.%s" % key)

    avg = find_table(
        tables, caption_prefix="Average Number of Days to Process PERM")
    if avg is None:
        notes.append("perm.average_calendar_days is empty: no table captioned "
                     "'Average Number of Days to Process PERM Applications'.")
    else:
        for row in avg["rows"]:
            if len(row) < 3 or not row[0].strip():
                continue
            label = row[0].strip().lower()
            key = next((k for k, needle in PERM_STAGES if needle in label), None)
            if key is None:
                continue
            days = norm_int(row[2])
            if days is None:
                notes.append("perm.average_calendar_days.%s.calendar_days is "
                             "null: DOL published %r, not a number."
                             % (key, row[2].strip()))
            iso = norm_month(row[1])
            out["average_calendar_days"][key] = {
                "determinations_month": iso,
                "determinations_month_label": month_label(iso),
                "calendar_days": days,
                "raw": row[2].strip() or None,
            }
    return out


# ---------------------------------------------------------------------------
# source_note: built from the parsed as-of dates so it can NEVER state a date
# the data does not have. Displayed verbatim by the page.
# ---------------------------------------------------------------------------
def build_source_note(perm, pwd):
    def phrase(section, label):
        iso = section.get("as_of")
        raw = section.get("as_of_raw")
        pretty = None
        if iso:
            try:
                # "%-d" is not portable, so strip the zero-pad by hand.
                pretty = (datetime.date.fromisoformat(iso)
                          .strftime("%B %d, %Y").replace(" 0", " "))
            except ValueError:
                pretty = iso
        elif raw:
            pretty = raw
        if pretty:
            return "%s figures as published by DOL as of %s" % (label, pretty)
        return "%s figures carry no DOL as-of date" % label

    return ("Source: U.S. Department of Labor, Office of Foreign Labor "
            "Certification - Processing Times (flag.dol.gov/processingtimes). "
            "%s; %s. DOL publishes these numbers on its own schedule and its "
            "page is the authoritative record; the figures shown here are a "
            "mirror of it."
            % (phrase(perm, "PERM"),
               phrase(pwd, "prevailing wage determination (ETA-9141)")))


# ---------------------------------------------------------------------------
# Assembly + idempotent write.
# ---------------------------------------------------------------------------
def canonical_digest(payload):
    """sha256 over the payload EXCLUDING the timestamp/digest fields, so two runs
    against identical upstream data produce the same digest."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_payload(page_html, provenance, verbose):
    """Parse the page into the committed shape. Returns (payload, notes)."""
    notes = []
    tables = parse_tables(page_html)
    log("parsed %d <table> elements" % len(tables), verbose)
    if not tables:
        notes.append("No HTML tables were found on the page at all - the fetch "
                     "may have returned an error or interstitial page.")

    try:
        perm = extract_perm(tables, notes)
    except Exception as exc:  # noqa: BLE001 - one dead section must not kill the run
        log("PERM section FAILED: %s" % exc, verbose)
        notes.append("The PERM section could not be parsed at all (%s); its "
                     "fields are null." % exc)
        perm = {"as_of": None, "as_of_raw": None, "stages": {},
                "average_calendar_days": {}}

    try:
        pwd = extract_prevailing_wage(page_html, tables, notes)
    except Exception as exc:  # noqa: BLE001
        log("prevailing-wage section FAILED: %s" % exc, verbose)
        notes.append("The prevailing-wage section could not be parsed at all "
                     "(%s); its fields are null." % exc)
        pwd = {"as_of": None, "as_of_raw": None, "queues": {},
               "redeterminations": {}, "center_director_reviews": {},
               "pending_requests": {}}

    payload = {
        "schema_version": 1,
        "source_url": SOURCE_URL,
        "source_name": ("U.S. Department of Labor, Office of Foreign Labor "
                        "Certification (OFLC)"),
        "source_fetch_path": provenance,
        "source_note": build_source_note(perm, pwd),
        "perm": perm,
        "prevailing_wage": pwd,
        "notes": notes,
    }
    # A run that fetched a page but read NOTHING must be visible, not a silently
    # empty gauge. parse_ok is a coarse health flag only: it means "at least one
    # figure was read". It is NOT a promise that any particular field is
    # populated - a consumer must still check the specific field it renders.
    got_any = bool(
        any(v.get("month") for v in perm.get("stages", {}).values())
        or any(v.get("calendar_days") is not None
               for v in perm.get("average_calendar_days", {}).values())
        or any(q.get("oews_receipt", {}).get("month")
               for q in pwd.get("queues", {}).values())
        or any(p.get("total_remaining_requests") is not None
               for p in pwd.get("pending_requests", {}).values()))
    payload["parse_ok"] = got_any
    if not got_any:
        notes.append("parse_ok is false: the page was fetched but no figure at "
                     "all could be read. Treat every value here as absent, not "
                     "as zero.")
    return payload


def write_idempotent(out_path, payload, now_iso, verbose):
    """Write the artifact, preserving `fetched_at` when the content is unchanged
    so two consecutive runs on unchanged upstream data are byte-identical.
    Returns (status, content_digest) where status is 'unchanged' or 'updated'."""
    digest = canonical_digest(payload)
    fetched_at = now_iso

    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log("existing %s unreadable (%s); rewriting" % (out_path, exc), verbose)
            prior = None
        if isinstance(prior, dict) and prior.get("content_digest") == digest:
            fetched_at = prior.get("fetched_at") or now_iso
            log("content_digest unchanged; preserving fetched_at %s" % fetched_at,
                verbose)

    # Timestamp fields go LAST in the dict but are excluded from the digest, so
    # ordering here never affects idempotency.
    final = dict(payload)
    final["fetched_at"] = fetched_at
    final["content_digest"] = digest

    text = json.dumps(final, indent=2, ensure_ascii=False) + "\n"
    if out_path.exists() and out_path.read_text(encoding="utf-8") == text:
        return "unchanged", digest
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return ("unchanged" if fetched_at != now_iso else "updated"), digest


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Fetch DOL OFLC processing times (PERM adjudication month, "
                    "ETA-9141 prevailing-wage receipt month, and the pending-"
                    "request backlog) from flag.dol.gov and write a small "
                    "committed JSON the static site reads with no backend. "
                    "Never fabricates a figure: unparseable values are null "
                    "with a recorded reason. Personal-learning tool; not legal "
                    "advice.")
    ap.add_argument("--out", default=str(HERE / "dol_queue.json"),
                    help="Output path (default: automation/dol_queue.json).")
    ap.add_argument("--html-file", default=None,
                    help="Parse a local HTML file instead of fetching. For "
                         "offline testing and reproducibility checks.")
    ap.add_argument("--now", default=None,
                    help="Override the fetched_at timestamp (ISO 8601 UTC). "
                         "For deterministic tests.")
    ap.add_argument("--no-wayback", action="store_true",
                    help="Do not fall back to the archive.org capture if the "
                         "direct read fails.")
    ap.add_argument("--verbose", action="store_true",
                    help="Log each fetch and parse step to stderr.")
    args = ap.parse_args(argv)

    verbose = args.verbose
    out_path = Path(args.out)
    now_iso = args.now or (datetime.datetime.now(datetime.timezone.utc)
                           .replace(microsecond=0).isoformat()
                           .replace("+00:00", "Z"))

    try:
        page_html, provenance = fetch_page(args.html_file,
                                           not args.no_wayback, verbose)
    except Exception as exc:  # noqa: BLE001
        # Deliberately do NOT clobber a good existing file. The site keeps
        # serving the last known good numbers with their real age.
        sys.stderr.write("ERROR: could not fetch %s: %s\n" % (SOURCE_URL, exc))
        if out_path.exists():
            sys.stderr.write("Left %s untouched (last known good data "
                             "preserved).\n" % out_path)
        return 3

    payload = build_payload(page_html, provenance, verbose)
    status, digest = write_idempotent(out_path, payload, now_iso, verbose)

    # ---- stdout summary ----
    perm, pwd = payload["perm"], payload["prevailing_wage"]
    print("=" * 70)
    print("fetch_dol_queue.py - %s (%s)" % (now_iso, provenance["path"]))
    print("=" * 70)
    print("PERM (DOL as of %s):" % (perm.get("as_of") or "unknown"))
    for key, _ in PERM_STAGES:
        st = perm.get("stages", {}).get(key) or {}
        print("  %-16s priority date: %s" % (key, st.get("month_label") or "null"))
    for key, _ in PERM_STAGES:
        av = perm.get("average_calendar_days", {}).get(key)
        if av:
            print("  %-16s avg days (%s): %s"
                  % (key, av.get("determinations_month_label") or "?",
                     av.get("calendar_days") if av.get("calendar_days")
                     is not None else "null"))
    print("")
    print("Prevailing wage / ETA-9141 (DOL as of %s):"
          % (pwd.get("as_of") or "unknown"))
    for q in PWD_QUEUES:
        row = pwd.get("queues", {}).get(q)
        if not row:
            continue
        print("  %-6s OEWS receipt: %-16s non-OEWS receipt: %s"
              % (q, row["oews_receipt"]["month_label"] or "null",
                 row["non_oews_receipt"]["month_label"] or "null"))
    for q in PWD_QUEUES:
        pend = pwd.get("pending_requests", {}).get(q)
        if not pend:
            continue
        print("  %-6s pending requests: %s across %d receipt month(s)"
              % (q, pend["total_remaining_requests"]
                 if pend["total_remaining_requests"] is not None else "null",
                 len(pend["by_receipt_month"])))
    print("")
    if payload["notes"]:
        print("Notes (why a field is null / what was skipped):")
        for n in payload["notes"]:
            print("  - %s" % n)
        print("")
    print("parse_ok: %s" % payload["parse_ok"])
    print("content_digest: %s" % digest)
    print("Output: %s (%s)" % (out_path, status))
    if not payload["parse_ok"]:
        print("NOTE: nothing parsed. Wrote the artifact with null figures and "
              "reasons rather than inventing numbers.")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
