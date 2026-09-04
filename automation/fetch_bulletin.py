#!/usr/bin/env python3
"""
fetch_bulletin.py - the FACTS snapshot fetcher (monthly-ish assist for the facts flow).

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
This is a HUMAN-REVIEW ASSIST for the MONTHLY bulletin-facts flow (RUNBOOK.md ->
diff_proposal.py -> apply_proposal.py -> deploy.sh). It gathers the latest month's
EB-1/EB-2/EB-3 Final Action + Dates for Filing values for the tracked countries
(India, China, ROW, Mexico, Philippines) and writes a bulletin_snapshot.json for a
human to eyeball. It NEVER writes rulebook.json and is NOT auto-apply-eligible.

WHY A 3-SOURCE QUORUM (the honest source-trust story)
-----------------------------------------------------
No live, machine-readable OFFICIAL feed of the Visa Bulletin exists. travel.state.gov
is Cloudflare/bot-walled (403 to scripts and headless browsers). So the legitimate
automated approximation is to triangulate across THREE independent, legitimate,
public-domain-data sources and only trust a value when they agree:

  1. mixseomin/visa-bulletin-history (PRIMARY). A community GitHub mirror that carries
     BOTH charts (Final Action Dates AND Dates for Filing) for every month, as raw
     JSON + CSV over HTTPS (HTTP 200, no auth). It is a community mirror, not an
     authority - which is exactly why we cross-check it against two others.

  2. DavidBellamy/visa_dates (CROSS-CHECK). A separate community dataset of Final
     Action Dates only, one CSV per country. It is corroboration, not required: its
     last commit can lag by months, so it is frequently STALE. When its latest
     visa_bulletin_date is behind the target month, we mark it "stale" and proceed
     on the other two rather than fail.

  3. Wayback Machine of the OFFICIAL travel.state.gov page (GROUND-TRUTH BACKSTOP).
     The Internet Archive's public copy of the real government page. It is the only
     leg that traces back to the official source, but it lags ~3-4 weeks (the Archive
     crawls the page some time after DOS publishes), and archive.org aggressively
     rate-limits (HTTP 429). So Wayback usually only has the PREVIOUS month's official
     page, and often is unreachable this run. Its role is to CONFIRM last month's
     mirror data matched the official page - not to carry the current month. We make
     at most a couple of archive.org calls, catch 429/timeouts, and on failure mark
     Wayback "unavailable this run" WITHOUT failing the whole fetch.

QUORUM LOGIC
------------
For each (category, country, chart) cell we compare the value across whichever
sources have it:
  - >=2 sources AGREE  -> confidence "high",   agreement "N-source"
  - sources DISAGREE   -> confidence "low",    discrepancy: true (ALL values kept)
  - only 1 source has it -> confidence "medium", single-source
We never silently pick one source when they disagree.

CROSS-CHECK vs rulebook.json (READ-ONLY)
----------------------------------------
For each cell we also compare the quorum value to the CURRENT rulebook.json value and
list any differences in rulebook_discrepancies[] for human review. This file NEVER
writes rulebook.json. The snapshot feeds diff_proposal.py only AFTER human review.

USCIS PROCESSING TIMES ARE NOT HERE
-----------------------------------
USCIS I-140/I-485 processing times are a SEPARATE, non-automated field. egov.uscis.gov
is bot-walled (403) and api.uscis.gov/processing-times is a real official API but
OAuth-gated (401 without a Bearer token). The legitimate path is a one-time API
credential request via the USCIS developer program - see automation/USCIS_PROCESSING_TIMES.md.
Until then the tool LINKS OUT to egov.uscis.gov and that field stays non-automated.
This fetcher intentionally does not touch it.

Personal-learning project. NOT legal advice, NOT official guidance. All three
sources here are legitimate: public-domain government data mirrors + the Internet
Archive of the official government page.

Usage:
  python3 fetch_bulletin.py [--out bulletin_snapshot.json] [--month YYYY-MM] [--verbose]

stdlib only: urllib, json, csv, io, datetime, argparse, re, hashlib, pathlib, sys.
"""

import argparse
import csv
import datetime
import io
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Descriptive User-Agent: normal client courtesy so archive.org / GitHub can identify
# the caller. This is NOT evasion of any bot wall - we only ever hit sources that
# answer a plain client with HTTP 200 (or 429, which we respect).
USER_AGENT = ("green-card-monitor/2.0 (personal learning project; visa-bulletin "
              "facts assist)")
TIMEOUT_SECONDS = 20
WAYBACK_TIMEOUT_SECONDS = 15

# Canonical dimensions we track.
CATEGORIES = ["EB1", "EB2", "EB3"]
COUNTRIES = ["India", "China", "ROW", "Mexico", "Philippines"]
CHARTS = ["final", "filing"]

# --- Source 1: mixseomin (PRIMARY, both charts) ---------------------------------
MIX_JSON = "https://raw.githubusercontent.com/mixseomin/visa-bulletin-history/main/data/history.json"
MIX_CSV = "https://raw.githubusercontent.com/mixseomin/visa-bulletin-history/main/csv/visa-bulletin-priority-dates.csv"

# --- Source 2: DavidBellamy (CROSS-CHECK, Final Action only, per-country CSV) ----
# Verified live 2026-08-10: files live under data/ on the main branch.
DB_BASE = "https://raw.githubusercontent.com/DavidBellamy/visa_dates/{branch}/data/{country}_visa_backlog_timecourse.csv"
DB_BRANCHES = ["main", "master"]
DB_COUNTRY_FILES = {
    "India": "india", "China": "china", "Mexico": "mexico",
    "Philippines": "philippines", "ROW": "row",
}

# --- Source 3: Wayback of the OFFICIAL travel.state.gov page (BACKSTOP) ----------
WAYBACK_AVAIL = "http://archive.org/wayback/available?url={url}"
OFFICIAL_URL_TMPL = ("travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/"
                     "{year}/visa-bulletin-for-{monthname}-{year}.html")

# The mixseomin mirror labels employment categories either as the ordinal Visa-Bulletin
# form ("1st"/"2nd"/"3rd") or an "EB1"/"EB2"/"EB3" form. Map both onto EB1/EB2/EB3.
# Anything else (family F1/F2A..., EB4/EB5 set-asides, "Other Workers") is out of scope.
CATEGORY_ALIASES = {
    "EB1": "EB1", "EB-1": "EB1", "1ST": "EB1", "1": "EB1", "FIRST": "EB1",
    "EB2": "EB2", "EB-2": "EB2", "2ND": "EB2", "2": "EB2", "SECOND": "EB2",
    "EB3": "EB3", "EB-3": "EB3", "3RD": "EB3", "3": "EB3", "THIRD": "EB3",
}

# mixseomin / official column country labels -> canonical country.
COUNTRY_ALIASES = {
    "WORLDWIDE": "ROW", "ROW": "ROW",
    "ALLCHARGEABILITYAREASEXCEPTTHOSELISTED": "ROW",
    "ALLCHARGEABILITYAREAS": "ROW",
    "CHINA": "China", "CHINAMAINLANDBORN": "China", "CHINA-MAINLANDBORN": "China",
    "INDIA": "India",
    "MEXICO": "Mexico",
    "PHILIPPINES": "Philippines",
}

MONTH_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
MONTH_NAME = {v: k for k, v in MONTH_NUM.items()}
MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7,
    "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


# --------------------------------------------------------------------------------
# HTTP helpers (each caller wraps in try/except; a dead source never kills the run)
# --------------------------------------------------------------------------------
def http_get(url, timeout=TIMEOUT_SECONDS):
    """GET returning (status_code, bytes). Raises on network error / timeout; the
    caller decides how to degrade. A 429 comes back as (429, body) via HTTPError."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:  # 404, 429, etc. - a real HTTP status
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, body


def normalize_category(raw):
    if raw is None:
        return None
    key = str(raw).strip().upper().replace(" ", "")
    return CATEGORY_ALIASES.get(key)


def normalize_country(raw):
    if raw is None:
        return None
    key = str(raw).strip().upper().replace(" ", "")
    return COUNTRY_ALIASES.get(key)


def month_key(year, month):
    """Return (year_int, month_int) from possibly-string parts."""
    try:
        y = int(year)
    except (TypeError, ValueError):
        y = 0
    m = month
    if isinstance(m, str):
        mm = MONTH_NUM.get(m.strip().lower())
        if mm is None:
            try:
                mm = int(m)
            except ValueError:
                mm = 0
        m = mm
    try:
        m = int(m)
    except (TypeError, ValueError):
        m = 0
    return (y, m)


def norm_value(value):
    """Normalize any source's priority-date cell into the rulebook convention:
    'C'/'CURRENT' -> 'CURRENT'; 'U'/''/None -> None (unavailable); ISO date -> first
    10 chars; a DDMMMYY token (official page) -> ISO. Anything else -> trimmed str."""
    if value is None:
        return None
    v = str(value).strip()
    if v == "" or v.upper() in ("U", "N/A", "UNAVAILABLE"):
        return None
    if v.upper() in ("C", "CURRENT"):
        return "CURRENT"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    # DDMMMYY (e.g. 15JAN15) as used on the official page.
    m = re.match(r"^(\d{1,2})([A-Za-z]{3})(\d{2,4})$", v)
    if m:
        day = int(m.group(1))
        mon = MONTH_ABBR.get(m.group(2).upper())
        yr = int(m.group(3))
        if mon:
            if yr < 100:
                yr += 2000
            return "%04d-%02d-%02d" % (yr, mon, day)
    return v


# --------------------------------------------------------------------------------
# Source 1: mixseomin (PRIMARY - both charts via CSV, JSON fallback)
# --------------------------------------------------------------------------------
def fetch_mixseomin(target_ym, verbose=False):
    """Return (status_str, month_label, cells, note). cells is a dict keyed by
    (cat, country, chart) -> normalized value (key present => source covers cell)."""
    # Try CSV first (flat rows are unambiguous), then JSON.
    for url, kind in ((MIX_CSV, "csv"), (MIX_JSON, "json")):
        try:
            code, raw = http_get(url)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                sys.stderr.write("[mixseomin] %s error: %s\n" % (kind, exc))
            continue
        if code != 200 or not raw:
            if verbose:
                sys.stderr.write("[mixseomin] %s HTTP %s\n" % (kind, code))
            continue
        try:
            if kind == "csv":
                rows = _parse_mix_csv(raw)
            else:
                rows = _flatten_mix_json(raw)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                sys.stderr.write("[mixseomin] %s parse error: %s\n" % (kind, exc))
            continue
        if not rows:
            continue
        month_label, cells = _select_mix_month(rows, target_ym)
        if cells:
            return "ok", month_label, cells, "source=%s" % kind
    return "unavailable", None, {}, "mirror unreachable/unparseable (tried CSV+JSON)"


def _parse_mix_csv(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for r in reader:
        out.append({(k or "").strip().lower(): (v or "").strip()
                    for k, v in r.items()})
    return out


def _flatten_mix_json(raw_bytes):
    """The JSON shape is a list of month objects with tables.{chart}.{cat}.{country}.
    Flatten to the same row dicts the CSV path produces."""
    obj = json.loads(raw_bytes.decode("utf-8"))
    rows = []
    if not isinstance(obj, list):
        return rows
    for entry in obj:
        if not isinstance(entry, dict):
            continue
        year = entry.get("year")
        month = entry.get("month")
        tables = entry.get("tables", {})
        if not isinstance(tables, dict):
            continue
        for chart, cats in tables.items():
            if not isinstance(cats, dict):
                continue
            for cat, countries in cats.items():
                if not isinstance(countries, dict):
                    continue
                for country, val in countries.items():
                    rows.append({"year": year, "month": month, "chart": chart,
                                 "category": cat, "country": country,
                                 "priority_date": "" if val is None else str(val)})
    return rows


def _select_mix_month(rows, target_ym):
    def rk(r):
        return month_key(r.get("year"), r.get("month"))
    valid = [r for r in rows if rk(r) != (0, 0)]
    if not valid:
        return None, {}
    if target_ym:
        sel = [r for r in valid if rk(r) == target_ym]
        if sel:
            chosen = target_ym
        else:
            chosen = max(rk(r) for r in valid)
            sel = [r for r in valid if rk(r) == chosen]
    else:
        chosen = max(rk(r) for r in valid)
        sel = [r for r in valid if rk(r) == chosen]
    label = "%04d-%02d" % (chosen[0], chosen[1])
    cells = {}
    for r in sel:
        chart_raw = (r.get("chart") or "").lower()
        if "employment" not in chart_raw:
            continue  # skip family_* charts
        if "final" in chart_raw:
            chart = "final"
        elif "filing" in chart_raw:
            chart = "filing"
        else:
            continue
        cat = normalize_category(r.get("category"))
        if cat is None:
            continue
        country = normalize_country(r.get("country"))
        if country is None:
            continue
        cells[(cat, country, chart)] = norm_value(r.get("priority_date"))
    return label, cells


# --------------------------------------------------------------------------------
# Source 2: DavidBellamy (CROSS-CHECK - Final Action Dates only, per-country CSV)
# --------------------------------------------------------------------------------
def fetch_davidbellamy(target_ym, verbose=False):
    """Return (status_str, latest_label, cells, note). Final-action-only. Marks itself
    'stale' when its newest visa_bulletin_date is behind the target month, and
    'unavailable' when every country file 404s. Never fatal."""
    cells = {}
    latest_overall = None
    n_ok = 0
    n_404 = 0
    for country, slug in DB_COUNTRY_FILES.items():
        raw = None
        for branch in DB_BRANCHES:
            url = DB_BASE.format(branch=branch, country=slug)
            try:
                code, body = http_get(url)
            except Exception as exc:  # noqa: BLE001
                if verbose:
                    sys.stderr.write("[davidbellamy] %s error: %s\n" % (country, exc))
                continue
            if code == 200 and body:
                raw = body
                break
            if code == 404:
                n_404 += 1
        if raw is None:
            continue
        try:
            latest_row, latest_ym = _db_latest_row(raw)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                sys.stderr.write("[davidbellamy] %s parse error: %s\n" % (country, exc))
            continue
        if latest_ym is None:
            continue
        n_ok += 1
        if latest_overall is None or latest_ym > latest_overall:
            latest_overall = latest_ym
        # Only contribute a value if this file actually carries the target month.
        want = target_ym if target_ym else latest_ym
        target_row = _db_row_for_month(raw, want)
        for lvl, cat in (("1", "EB1"), ("2", "EB2"), ("3", "EB3")):
            val = (target_row or {}).get(lvl)
            if val is not None:
                cells[(cat, country, "final")] = norm_value(val)

    if n_ok == 0:
        return "unavailable", None, {}, "all country files 404/unreachable (%d 404s)" % n_404

    latest_label = "%04d-%02d" % latest_overall if latest_overall else None
    # Staleness: newest data older than the target month => corroboration only, mark stale.
    if target_ym and latest_overall and latest_overall < target_ym:
        note = ("newest visa_bulletin_date %s is behind target %04d-%02d; "
                "treating as STALE corroboration only (contributed no target-month cells)"
                % (latest_label, target_ym[0], target_ym[1]))
        return "stale", latest_label, {}, note
    if not cells:
        return "stale", latest_label, {}, ("no rows for target month; latest is %s"
                                           % latest_label)
    return "ok", latest_label, cells, "final-action-dates only; latest=%s" % latest_label


def _db_iter_rows(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _db_latest_row(raw_bytes):
    """Return (row_for_latest_date, (y,m)) for the newest non-empty visa_bulletin_date."""
    latest_ym = None
    for r in _db_iter_rows(raw_bytes):
        d = (r.get("visa_bulletin_date") or "").strip()
        m = re.match(r"^(\d{4})-(\d{2})", d)
        if m:
            ym = (int(m.group(1)), int(m.group(2)))
            if latest_ym is None or ym > latest_ym:
                latest_ym = ym
    return None, latest_ym


def _db_row_for_month(raw_bytes, target_ym):
    """Return {EB_level: final_action_date} for the given (y,m), or None if absent."""
    out = {}
    for r in _db_iter_rows(raw_bytes):
        d = (r.get("visa_bulletin_date") or "").strip()
        m = re.match(r"^(\d{4})-(\d{2})", d)
        if not m:
            continue
        if (int(m.group(1)), int(m.group(2))) != target_ym:
            continue
        lvl = (r.get("eb_level") or r.get("EB_level") or "").strip()
        fad = (r.get("final_action_dates") or "").strip()
        if lvl:
            out[lvl] = fad if fad else None
    return out or None


# --------------------------------------------------------------------------------
# Source 3: Wayback of the OFFICIAL travel.state.gov page (BACKSTOP, may 429)
# --------------------------------------------------------------------------------
class _VBTableParser(HTMLParser):
    """Collects an ordered stream of ('text', str) and ('table', rows) items so we
    can attribute each EB table to Final Action vs Dates for Filing by the heading
    text immediately preceding it. rows is a list of cell-text lists."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self._depth_table = 0
        self._cur_rows = None
        self._cur_row = None
        self._cur_cell = None
        self._text_buf = []

    def _flush_text(self):
        txt = " ".join(t.strip() for t in self._text_buf if t.strip())
        if txt:
            self.items.append(("text", txt))
        self._text_buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._flush_text()
            self._depth_table += 1
            if self._depth_table == 1:
                self._cur_rows = []
        elif tag == "tr" and self._depth_table >= 1:
            self._cur_row = []
        elif tag in ("td", "th") and self._depth_table >= 1:
            self._cur_cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self._depth_table >= 1:
            self._depth_table -= 1
            if self._depth_table == 0 and self._cur_rows is not None:
                self.items.append(("table", self._cur_rows))
                self._cur_rows = None
        elif tag == "tr" and self._depth_table >= 1 and self._cur_row is not None:
            if self._cur_rows is not None:
                self._cur_rows.append(self._cur_row)
            self._cur_row = None
        elif tag in ("td", "th") and self._depth_table >= 1 and self._cur_cell is not None:
            cell = " ".join(t.strip() for t in self._cur_cell if t.strip())
            if self._cur_row is not None:
                self._cur_row.append(cell)
            self._cur_cell = None

    def handle_data(self, data):
        if self._cur_cell is not None:
            self._cur_cell.append(data)
        elif self._depth_table == 0:
            self._text_buf.append(data)


def fetch_wayback(target_ym, verbose=False):
    """Best-effort, courteous, at-most-a-couple-of-calls read of the OFFICIAL page via
    the Internet Archive. Returns (status_str, snapshot_label, cells, note). NEVER
    fatal: 429/timeout/parse-failure all degrade to unavailable/rate-limited."""
    if not target_ym:
        return "skipped", None, {}, "no target month resolved; Wayback skipped"
    # Query current target month; if absent, fall back to the previous month (the
    # Archive typically only has last month's page due to the ~3-4 week crawl lag).
    candidates = [target_ym]
    py, pm = target_ym
    prev = (py - 1, 12) if pm == 1 else (py, pm - 1)
    candidates.append(prev)

    calls = 0
    for ym in candidates:
        if calls >= 2:  # hard courtesy cap on archive.org calls this run
            break
        official = OFFICIAL_URL_TMPL.format(year=ym[0], monthname=MONTH_NAME[ym[1]])
        avail = WAYBACK_AVAIL.format(url=official)
        calls += 1
        try:
            code, body = http_get(avail, timeout=WAYBACK_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - timeout/network
            if verbose:
                sys.stderr.write("[wayback] avail error: %s\n" % exc)
            return "unavailable", None, {}, "availability API timeout/error: %s" % exc
        if code == 429:
            return "rate-limited", None, {}, ("archive.org returned 429 (expected; the "
                                              "IP is rate-limited). Wayback skipped this "
                                              "run - it is a backstop, not required.")
        if code != 200 or not body:
            if verbose:
                sys.stderr.write("[wayback] avail HTTP %s for %04d-%02d\n"
                                 % (code, ym[0], ym[1]))
            continue
        try:
            meta = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        closest = (meta.get("archived_snapshots", {}) or {}).get("closest", {})
        if not closest or closest.get("status") not in ("200", 200) or not closest.get("timestamp"):
            continue
        ts = closest["timestamp"]
        # Raw archived HTML (id_ suffix returns the original bytes, not the AI banner).
        raw_url = "http://web.archive.org/web/%sid_/%s" % (ts, official)
        if calls >= 2:
            return ("unavailable", None, {},
                    "found snapshot for %04d-%02d but hit the 2-call courtesy cap "
                    "before fetching HTML" % (ym[0], ym[1]))
        calls += 1
        try:
            code, html = http_get(raw_url, timeout=WAYBACK_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001
            return "unavailable", None, {}, "archived-HTML fetch timeout/error: %s" % exc
        if code == 429:
            return "rate-limited", None, {}, "429 on archived-HTML fetch; Wayback skipped"
        if code != 200 or not html:
            continue
        try:
            cells = _parse_official_html(html)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                sys.stderr.write("[wayback] parse error: %s\n" % exc)
            return "unavailable", None, {}, "archived HTML parse failed: %s" % exc
        label = "%04d-%02d" % (ym[0], ym[1])
        if cells:
            note = ("parsed official archived page (snapshot %s) for %s. Backstop lags "
                    "~3-4 weeks, so this usually confirms the PREVIOUS month." % (ts, label))
            return "ok", label, cells, note
        return "unavailable", label, {}, "snapshot found but no EB tables parsed"
    return "unavailable", None, {}, "no usable archived snapshot for target or prior month"


def _parse_official_html(html_bytes):
    """Extract EB1/EB2/EB3 x country x {final,filing} from the archived official page."""
    text = html_bytes.decode("utf-8", errors="replace")
    p = _VBTableParser()
    p.feed(text)
    cells = {}
    last_heading = ""
    for kind, payload in p.items:
        if kind == "text":
            up = payload.upper()
            if "EMPLOYMENT" in up and "FINAL ACTION" in up:
                last_heading = "final"
            elif "EMPLOYMENT" in up and ("DATES FOR FILING" in up or "FILING OF EMPLOYMENT" in up):
                last_heading = "filing"
            continue
        # kind == "table"
        rows = payload
        # An EB employment table's data rows start with a category label 1st/2nd/3rd.
        col_country = _detect_country_columns(rows)
        if col_country is None or last_heading not in ("final", "filing"):
            continue
        for row in rows:
            if not row:
                continue
            cat = normalize_category(row[0])
            if cat is None:
                continue
            for col_idx, country in col_country.items():
                if col_idx < len(row):
                    cells[(cat, country, last_heading)] = norm_value(row[col_idx])
    return cells


def _detect_country_columns(rows):
    """Find the header row mapping column index -> canonical country. Returns None if
    this table is not an employment preference table."""
    for row in rows:
        mapping = {}
        for idx, cell in enumerate(row):
            c = normalize_country(cell)
            if c is not None:
                mapping[idx] = c
        # A real EB table header carries ROW + at least India and one more country.
        if "India" in mapping.values() and len(mapping) >= 3:
            return mapping
    return None


# --------------------------------------------------------------------------------
# Quorum + rulebook cross-check
# --------------------------------------------------------------------------------
def build_quorum(sources):
    """sources: list of (source_id, cells_dict). Returns per-cell quorum results."""
    out = {}
    for cat in CATEGORIES:
        for country in COUNTRIES:
            for chart in CHARTS:
                key = (cat, country, chart)
                contributions = {}
                for sid, cells in sources:
                    if key in cells:
                        contributions[sid] = cells[key]
                if not contributions:
                    continue
                # Group sources by value (None means unavailable, a real datum).
                by_value = {}
                for sid, val in contributions.items():
                    vk = "\x00NULL" if val is None else val
                    by_value.setdefault(vk, []).append(sid)
                n_sources = len(contributions)
                n_distinct = len(by_value)
                cell = {
                    "category": cat, "country": country, "chart": chart,
                    "sources": {sid: contributions[sid] for sid in contributions},
                }
                if n_distinct == 1:
                    # All agree.
                    the_val = next(iter(contributions.values()))
                    if n_sources >= 2:
                        cell.update(value=the_val, confidence="high",
                                    agreement="%d-source" % n_sources,
                                    discrepancy=False)
                    else:
                        cell.update(value=the_val, confidence="medium",
                                    agreement="single-source", discrepancy=False)
                else:
                    # Disagreement - never silently pick one.
                    cell.update(value=None, confidence="low",
                                agreement="disagreement", discrepancy=True,
                                differing_values={
                                    ("UNAVAILABLE" if vk == "\x00NULL" else vk): sids
                                    for vk, sids in by_value.items()})
                out[key] = cell
    return out


RB_CAT = {"EB1": "EB-1", "EB2": "EB-2", "EB3": "EB-3"}
RB_CHART_FIELD = {"final": "final_action_date", "filing": "date_for_filing"}


def read_rulebook(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "could not read rulebook.json: %s" % exc


def rulebook_cell(rb, cat, country, chart):
    """Return (value, present_bool) for the rulebook cell, or (None, False) if the cell
    is not modeled in rulebook.json (e.g. EB-1 has no ROW entry)."""
    cats = rb.get("bulletin", {}).get("categories", {})
    c = cats.get(RB_CAT[cat], {}).get(country)
    if not isinstance(c, dict):
        return None, False
    field = RB_CHART_FIELD[chart]
    if field not in c:
        return None, False
    return c.get(field), True


def cross_check_rulebook(rb, quorum):
    """List rulebook_discrepancies[]: cells where the quorum value differs from the
    current rulebook value. Skips low-confidence (disagreement) cells - nothing to
    compare against - and cells the rulebook does not model."""
    out = []
    for key in sorted(quorum.keys()):
        q = quorum[key]
        if q.get("discrepancy"):
            continue  # no single quorum value to compare
        cat, country, chart = key
        rb_val, present = rulebook_cell(rb, cat, country, chart)
        if not present:
            continue
        q_val = q.get("value")
        if q_val != rb_val:
            out.append({
                "cell": "%s %s %s" % (RB_CAT[cat], country, RB_CHART_FIELD[chart]),
                "category": RB_CAT[cat], "country": country,
                "chart_field": RB_CHART_FIELD[chart],
                "rulebook_value": rb_val,
                "quorum_value": q_val,
                "quorum_confidence": q.get("confidence"),
                "sources": q.get("sources"),
                "note": ("Quorum differs from current rulebook.json. Human must verify "
                         "against travel.state.gov before any change. This file does NOT "
                         "write rulebook.json."),
            })
    return out


# --------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="3-source-quorum Visa Bulletin FACTS snapshot for human review. "
                    "Triangulates two public-domain community mirrors + the Internet "
                    "Archive of the official travel.state.gov page. NOT a live official "
                    "feed; NOT auto-apply-eligible; NEVER writes rulebook.json. "
                    "Personal-learning tool, not legal advice.")
    ap.add_argument("--out", default=str(HERE / "bulletin_snapshot.json"),
                    help="Output path for the snapshot JSON.")
    ap.add_argument("--month", default=None,
                    help="Target bulletin month YYYY-MM (default: primary mirror's latest).")
    ap.add_argument("--rulebook", default=str(REPO / "rulebook.json"),
                    help="Path to rulebook.json for the read-only cross-check.")
    ap.add_argument("--verbose", action="store_true", help="Verbose diagnostics to stderr.")
    args = ap.parse_args(argv)

    if args.month and not re.match(r"^\d{4}-\d{2}$", args.month):
        sys.stderr.write("ERROR: --month must be YYYY-MM, got %r\n" % args.month)
        return 2

    target_ym = None
    fetched_at = None
    target_note = None
    if args.month:
        ty, tm = args.month.split("-")
        target_ym = (int(ty), int(tm))
        fetched_at = args.month
        target_note = "explicit --month"

    # --- Fetch all three sources; any one failing does NOT kill the run ---
    mix_status, mix_label, mix_cells, mix_note = fetch_mixseomin(target_ym, args.verbose)

    # If no explicit month, anchor the run on the primary mirror's latest month
    # (a LABELED fallback - never a silent now()).
    if target_ym is None:
        if mix_label:
            ly, lm = mix_label.split("-")
            target_ym = (int(ly), int(lm))
            fetched_at = mix_label
            target_note = "fallback: primary mirror (mixseomin) latest month"
        else:
            fetched_at = "unresolved"
            target_note = ("no --month and primary mirror unavailable; month unresolved")

    db_status, db_label, db_cells, db_note = fetch_davidbellamy(target_ym, args.verbose)
    wb_status, wb_label, wb_cells, wb_note = fetch_wayback(target_ym, args.verbose)

    source_status = {
        "mixseomin": {
            "id": "github:mixseomin/visa-bulletin-history",
            "role": "primary (both charts)",
            "status": mix_status, "month_found": mix_label, "note": mix_note,
            "cells_contributed": len(mix_cells),
        },
        "davidbellamy": {
            "id": "github:DavidBellamy/visa_dates",
            "role": "cross-check (Final Action Dates only)",
            "status": db_status, "latest_month": db_label, "note": db_note,
            "cells_contributed": len(db_cells),
        },
        "wayback_official": {
            "id": "web.archive.org of travel.state.gov Visa Bulletin",
            "role": "ground-truth backstop (lags ~3-4 weeks; archive.org rate-limits)",
            "status": wb_status, "snapshot_month": wb_label, "note": wb_note,
            "cells_contributed": len(wb_cells),
        },
    }

    # --- Quorum ---
    contributing = [(sid, cells) for sid, cells in
                    (("mixseomin", mix_cells), ("davidbellamy", db_cells),
                     ("wayback_official", wb_cells)) if cells]
    quorum = build_quorum(contributing)

    # --- Rulebook cross-check (READ-ONLY) ---
    rb, rb_err = read_rulebook(args.rulebook)
    rulebook_discrepancies = []
    if rb is None:
        rulebook_discrepancies.append({"cell": "(rulebook)", "note": rb_err})
    else:
        rulebook_discrepancies = cross_check_rulebook(rb, quorum)

    # --- Summaries ---
    agree_cells = [q for q in quorum.values() if not q.get("discrepancy")
                   and q.get("confidence") == "high"]
    single_cells = [q for q in quorum.values() if q.get("confidence") == "medium"]
    disagree_cells = [q for q in quorum.values() if q.get("discrepancy")]

    # Serialize quorum with string keys for JSON.
    quorum_out = []
    for key in sorted(quorum.keys()):
        quorum_out.append(quorum[key])

    out = {
        "artifact": "bulletin_snapshot",
        "artifact_kind": ("HUMAN-REVIEW review artifact - a SUPERSET of the "
                          "fetch_results_schema.json facts fragment. It carries "
                          "per-source status, per-cell quorum, and rulebook "
                          "discrepancies in addition to the run_date/bulletin_month/"
                          "findings a fetch-results file would carry. It is NOT a "
                          "drop-in fetch_results file; a human hand-authors that after "
                          "reviewing this."),
        "source_trust": ("No live OFFICIAL machine-readable feed exists (travel.state.gov "
                         "is bot-walled). This is the legitimate automated approximation: "
                         "TWO independent public-domain community mirrors + the Internet "
                         "Archive of the official government page, trusted only on quorum. "
                         "These are unofficial mirrors plus a lagged official-archive "
                         "backstop - NOT a live official feed. All changes are HUMAN-GATED "
                         "before any rulebook.json edit (see RUNBOOK.md); this file never "
                         "writes rulebook.json and is not auto-apply-eligible."),
        "uscis_processing_times": ("NOT fetched here. Separate non-automated field behind "
                                   "an OAuth-gated official API - see USCIS_PROCESSING_TIMES.md."),
        "fetched_at": fetched_at,
        "fetched_at_note": target_note,
        "run_date": datetime.date.today().isoformat(),
        "bulletin_month_found": mix_label or (
            "%04d-%02d" % target_ym if target_ym else None),
        "requested_month": args.month,
        "source_status": source_status,
        "quorum": quorum_out,
        "rulebook_discrepancies": rulebook_discrepancies,
        "summary": {
            "cells_high_confidence_agree": len(agree_cells),
            "cells_single_source_medium": len(single_cells),
            "cells_in_disagreement": len(disagree_cells),
            "rulebook_discrepancies": len(rulebook_discrepancies),
        },
    }

    Path(args.out).write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- stdout summary ----
    print("=" * 74)
    print("fetch_bulletin.py - 3-source-quorum Visa Bulletin FACTS snapshot")
    print("=" * 74)
    print("Target month:      %s  (%s)" % (fetched_at, target_note))
    print("")
    print("Per-source status:")
    print("  mixseomin (primary) : %-12s cells=%d  %s"
          % (mix_status, len(mix_cells), mix_note))
    print("  davidbellamy (xchk) : %-12s cells=%d  %s"
          % (db_status, len(db_cells), db_note))
    print("  wayback (backstop)  : %-12s cells=%d  %s"
          % (wb_status, len(wb_cells), wb_note))
    print("")
    print("Quorum:")
    print("  %d cells with >=2-source AGREEMENT (high confidence)" % len(agree_cells))
    print("  %d cells single-source (medium confidence)" % len(single_cells))
    print("  %d cells in DISAGREEMENT (low confidence, all values kept)"
          % len(disagree_cells))
    if disagree_cells:
        for q in disagree_cells:
            print("    - %s %s %s: %s" % (RB_CAT[q["category"]], q["country"],
                                          q["chart"], q.get("differing_values")))
    print("")
    if rulebook_discrepancies:
        print("Rulebook discrepancies (%d) - HUMAN REVIEW REQUIRED:"
              % len(rulebook_discrepancies))
        for d in rulebook_discrepancies:
            if "quorum_value" in d:
                print("  - %s: rulebook=%r quorum=%r (%s)"
                      % (d["cell"], d["rulebook_value"], d["quorum_value"],
                         d["quorum_confidence"]))
            else:
                print("  - %s" % d.get("note"))
    else:
        print("No rulebook discrepancies against agreed/single-source quorum cells.")
    print("")
    print("Snapshot: %s" % args.out)
    print("NOTE: unofficial mirrors + lagged official-archive backstop, trusted only on "
          "quorum. NOT a live official feed. Human-gated before any rulebook.json edit; "
          "this file never writes rulebook.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
