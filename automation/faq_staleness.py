#!/usr/bin/env python3
"""
faq_staleness.py - answers ONE question: which FAQ answers just went stale?

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
Stage 1 of FAQ maintenance. It needs NO Slack access, so unlike the
question-gap scan it runs fine on a GitHub Actions runner. It reads faq.html
plus automation/faq_tripwires.json and reports drift from six sources:

  1. DATES IN THE COPY - a date in the page has arrived, or lands inside the
     horizon. This is the failure mode that actually hurts: an answer reading
     "changes September 15, 2026" is silently wrong on September 16.
  2. FEDERAL REGISTER, BY RIN - a watched rulemaking has a document its
     recorded baseline does not.
  3. FEDERAL REGISTER, BY CFR PART - any rule amending a regulation the FAQ
     cites, including rulemakings nobody thought to watch. This is the net that
     catches unknown unknowns.
  4. LITIGATION - a watched federal docket has a new entry or was terminated,
     via the CourtListener search API.
  5. PRESIDENTIAL DOCUMENTS - a proclamation or executive order matching a
     watched term. These have NO RIN and amend NO CFR part, so checks 2 and 3
     are blind to them by construction, yet a proclamation under INA 212(f) can
     restrict entry outright.
  6. ARCHIVED PAGE CONTENT - a USCIS page's content digest changed, observed
     through the Wayback Machine.
  Plus the age of the dated "Last checked against primary sources on ..." stamp.

HONEST BOUNDARIES (read these)
------------------------------
* It reports; it does NOT rewrite answers. Every finding is a pointer to an
  anchor for a human to re-verify against primary sources.
* It reports THAT something changed, never WHETHER the change matters. A
  technical correction and a policy reversal look identical to a diff.
* uscis.gov and travel.state.gov are NEVER fetched directly (they are
  Cloudflare-walled; see RUNBOOK.md). Page-change detection reads archive.org's
  capture digests instead, so it detects that a page changed WITHOUT touching
  the origin - and it cannot tell a substantive edit from a nav-bar tweak.
* CourtListener's /docket-entries/ and /dockets/{id}/ endpoints require
  authentication (verified: HTTP 401 anonymous). Only /search/ answers
  anonymously, and the recap_documents it returns are a SUBSET of the docket,
  not the full history. So litigation checks are a "something moved" signal,
  not a complete docket mirror.
* Baselines only move with --update-baselines, so a report stays reproducible
  until the new state is deliberately accepted. Same propose-then-approve gate
  as diff_proposal.py / apply_proposal.py.

Repeat findings are tracked in automation/faq_staleness_ledger.json and split
into "new or escalated" vs "still open", so a long-lived ACTION does not spam
the report - but it still fails the build, because it is still unresolved.

Exit codes: 0 = ran fine. 2 = an ACTION finding exists AND --fail-on-action.

Usage:
  python3 automation/faq_staleness.py --verbose
  python3 automation/faq_staleness.py --out automation/faq_staleness_report.md
  python3 automation/faq_staleness.py --skip-network      # dates + stamp only
  python3 automation/faq_staleness.py --update-baselines  # accept observed state
"""

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

USER_AGENT = ("GreenCardNavigator-FAQStaleness/1.1 "
              "(personal educational project; read-only)")
TIMEOUT_SECONDS = 45
RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

FR_API = "https://www.federalregister.gov/api/v1/documents.json"
CL_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"
CDX_API = "http://web.archive.org/cdx/search/cdx"

# Docket entry descriptions that suggest the court actually DID something, as
# opposed to routine filings (proof of service, notice of appearance). Used only
# to raise severity - a new entry is reported either way.
_RULING_RE = re.compile(
    r"\b(order|opinion|memorandum|judgment|judgement|ruling|injunction|"
    r"restraining|stay(?:ed|ing)?|vacat\w*|remand\w*|dismiss\w*|"
    r"grant\w*|den(?:y|ied|ying)|summary judgment)\b", re.I)

# ---------------------------------------------------------------------------
# Date parsing. Three shapes, because the copy is hand-written prose and a date
# written in an unrecognised format is SILENTLY unmonitored.
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    # Abbreviations, with and without the trailing period.
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# "September 15, 2026" / "Sept. 15, 2026"
_DATE_MDY = re.compile(r"\b(" + _MONTH_ALT + r")\.?\s+(\d{1,2}),\s*(\d{4})\b", re.I)
# "15 September 2026"
_DATE_DMY = re.compile(r"\b(\d{1,2})\s+(" + _MONTH_ALT + r")\.?,?\s+(\d{4})\b", re.I)
# "2026-09-15"
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_FLAG_RE = re.compile(
    r'<div class="faq-flag (is-[a-z]+)"[^>]*>(.*?)</div>', re.S)
# Both anchor kinds, because some flags are SECTION-level: they sit after a
# section's <h2> and before its first question. Matching only q- ids would
# attribute those to the last question of the PREVIOUS section.
_ANCHOR_RE = re.compile(r'id="((?:q|mod)-[a-z0-9-]+)"')
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def log(msg, verbose):
    if verbose:
        sys.stderr.write("[faq_staleness] %s\n" % msg)


def http_text(url, verbose, retries=RETRIES, cap=8_000_000):
    """GET plain text with a byte cap. A final rule's full text can run past a
    megabyte (the F/J/I rule is ~1.2 MB), so the cap stops a pathological
    document from stalling the run."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            log("GET text (try %d/%d) %s" % (attempt, retries, url), verbose)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return resp.read(cap).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last


def http_json(url, verbose, retries=RETRIES):
    """GET JSON with a descriptive UA, a short timeout, and bounded retries.
    Raises after the last attempt so the per-item caller records a miss rather
    than the whole run dying."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            log("GET (try %d/%d) %s" % (attempt, retries, url), verbose)
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last = exc
            if attempt < retries:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last


def strip_tags(html):
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html)).strip()


# ---------------------------------------------------------------------------
# CFR-sweep relevance. A part-level sweep (8 CFR 214) is deliberately wide, so
# it returns rules that touch the part for reasons the FAQ does not care about.
# Three layers narrow it WITHOUT ever dropping a document, because a silent drop
# is the exact failure the sweep exists to prevent. Low relevance downgrades to
# WATCH and is still listed with the evidence needed to dismiss it at a glance.
#
# Layer 1: which paragraphs the FAQ actually cites, parsed out of faq.html so
#          the relevance set cannot drift from the content.
# Layer 2: which paragraphs the rule actually AMENDS, parsed from its amendatory
#          instructions. Not a word-frequency heuristic - the instructions state
#          precisely what changes, as opposed to what is merely cross-referenced.
# Layer 3: the rule's SUBJECT, weighted by whether a marker appears in the title.
#          Paragraph overlap alone is not enough: 8 CFR 214.2(h) houses H-2A and
#          H-2B as well as H-1B, so an H-2B rule overlaps the FAQ's 23 citations
#          to 214.2(h) while being irrelevant to it. Subject is the separator.
# ---------------------------------------------------------------------------

_CFR_CITE_RE = re.compile(
    r"(\d+)\s*CFR\s*(\d+[a-z]?\.\d+[a-z]?)((?:\([a-z0-9]+\))*)", re.I)

# "Amend Sec. 214.1 as follows" / "Section 214.2 is amended by"
_AMEND_SEC_RE = re.compile(
    r"(?:Amend|Revise|Add)\s+Sec\.?\s*(\d{2,3}[a-z]?\.\d+[a-z]?)"
    r"|Section\s+(\d{2,3}[a-z]?\.\d+[a-z]?)\s+is\s+amended", re.I)
_AMEND_PARA_RE = re.compile(r"paragraphs?\s+((?:\([a-z0-9]+\)[\s,and]*)+)", re.I)

# Subjects the FAQ is actually about. STRONG markers name a program the site
# covers. WEAK markers are procedural words that appear across every program
# ("fee"), so a weak marker alone must NOT override an out-of-scope title -
# otherwise "Naturalization Application Fee Adjustments" reads as in-scope.
# NOTE ON PLURALS: every noun that can pluralise needs an explicit `s?` before
# the closing \b. Without it the boundary fails on the plural and the marker is
# silently missed - which is how "Religious Organizations" slipped past the
# out-of-scope list and reached ACTION.
_IN_STRONG_RE = re.compile(
    r"\b(H-1B|H1B|F-1|specialty occupations?|academic students?|"
    r"exchange visitors?|optional practical training|cap-gap|L-1|H-4|L-2|"
    r"employment authorizations?|adjustment of status|immigrant petitions?|"
    r"priority dates?|labor certifications?|PERM|national interest waivers?|"
    r"extraordinary ability|multinational|EB-1|EB-2|EB-3|duration of status|"
    r"change of status|nonimmigrant workers?|premium processing|"
    r"prevailing wages?|wage protections?|wage levels?)\b", re.I)
_IN_WEAK_RE = re.compile(r"\b(fee|filing|registration|biometric)s?\b", re.I)

# Title gate for presidential documents. The Federal Register API has NO
# title-scoped condition (conditions[title] errors), and conditions[term] is a
# full-text match - so a term query alone returns tariff, national-park and
# commercial-fishing orders, because sanctions and trade documents carry a
# standard clause suspending "the entry of immigrants and nonimmigrants" for
# designated persons. Gating on the TITLE is what separates subject from
# boilerplate. Deliberately inclusive: a title that squeaks through becomes a
# WATCH at worst, whereas a title wrongly excluded is only ever counted in an
# aggregate line, never silently dropped.
_PRES_TITLE_RE = re.compile(
    r"\b(entry|admission|admit\w*|visas?|immigrant|nonimmigrant|immigration|"
    r"aliens?|foreign nationals?|refugees?|asylum|asylees?|border|"
    r"naturaliz\w*|citizenship|travel|workers?|students?|"
    r"birth tourism|gold card)\b", re.I)
# Adjacent programs that share CFR real estate but not the FAQ's audience.
_OUT_SCOPE_RE = re.compile(
    r"\b(crewm[ae]n|seamen|seafarers?|maritime|vessels?|lightering|"
    r"asylum|asylees?|refugees?|temporary protected status|agricultural|"
    r"H-2A|H-2B|EB-5|regional centers?|investors?|"
    r"religious (?:workers?|organizations?)|diplomats?|parole|"
    r"special immigrant juveniles?|"
    # Employer-penalty and enforcement rulemaking, not individual status.
    r"civil penalt\w*|penalties inflation|"
    # Naturalization is the step AFTER a green card, so it is out of scope for a
    # site about getting one. Fee rules for it would otherwise match on "fee".
    r"naturaliz\w*|citizenship)\b", re.I)


def extract_faq_citations(html):
    """Every CFR section+paragraph the FAQ cites, e.g. ('8','214.2','h').
    Derived from the page so the relevance set maintains itself: cite a new
    regulation in an answer and the sweep starts caring about it."""
    text = strip_tags(_SCRIPT_STYLE_RE.sub(" ", html))
    out = set()
    for title, sec, paras in _CFR_CITE_RE.findall(text):
        m = re.match(r"\(([a-z0-9]+)\)", paras)
        out.add((title, sec, m.group(1) if m else None))
    return out


def amended_paragraphs(text):
    """{section: {paragraph letters}} from a rule's amendatory instructions.
    Each instruction block runs until the next one, capped so a missing
    terminator cannot swallow the rest of the document."""
    t = re.sub(r"\s+", " ", text)
    hits = [(m.start(), m.group(1) or m.group(2))
            for m in _AMEND_SEC_RE.finditer(t)]
    out = {}
    for i, (pos, sec) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else min(len(t), pos + 2500)
        paras = set()
        for pm in _AMEND_PARA_RE.finditer(t[pos:end]):
            paras.update(re.findall(r"\(([a-z0-9]+)\)", pm.group(1)))
        out.setdefault(sec, set()).update(paras)
    return out


def cfr_relevance(title, abstract, topics, amended, faq_cites, cfr_title="8"):
    """(severity, explanation). Never returns a 'drop' - the worst outcome is
    WATCH, so nothing the sweep found disappears silently."""
    ct = str(cfr_title)
    overlap = sorted({"%s(%s)" % (s, p)
                      for s, ps in amended.items() for p in ps
                      if (ct, s, p) in faq_cites})
    title = title or ""
    blob = " ".join([title, abstract or "", " ".join(topics or [])])
    in_title = set(m.lower() for m in _IN_STRONG_RE.findall(title))
    out_title = set(m.lower() for m in _OUT_SCOPE_RE.findall(title))
    in_any = set(m.lower() for m in _IN_STRONG_RE.findall(blob))
    out_any = set(m.lower() for m in _OUT_SCOPE_RE.findall(blob))
    weak_title = set(m.lower() for m in _IN_WEAK_RE.findall(title))
    # A weak marker counts only when nothing out-of-scope competes with it.
    if weak_title and not out_title:
        in_title = in_title | weak_title
        in_any = in_any | weak_title

    # Section-level overlap, used when a rule amends a section the FAQ cites but
    # the instruction gave no paragraph. 1205-AC30 amends 20 CFR 655.731 while
    # the FAQ cites 655.731(c): requiring an exact paragraph match would bury a
    # DOL wage rule that hits the wage-level answer and PERM directly.
    cited_secs = {s for t, s, _ in faq_cites if t == ct}
    sec_overlap = sorted(set(amended) & cited_secs)

    # An out-of-scope TITLE outranks everything. An adjacent program sharing CFR
    # real estate is the main source of noise, and the title states the subject.
    if out_title and not in_title:
        what = (("amends %s, which the FAQ cites, " % ", ".join(overlap))
                if overlap else
                ("amends %s, a section the FAQ cites, " % ", ".join(sec_overlap))
                if sec_overlap else "")
        return "WATCH", ("%sBUT the subject is %s - an adjacent program sharing "
                         "the same part, most likely not about this site's readers"
                         % (what, ", ".join(sorted(out_title))))

    if overlap:
        return "ACTION", ("amends %s, which the FAQ cites%s"
                          % (", ".join(overlap),
                             "; subject matches (%s)" % ", ".join(sorted(in_title))
                             if in_title else
                             "; subject unclear (in=%s out=%s) so treated as "
                             "relevant" % (", ".join(sorted(in_any)) or "none",
                                           ", ".join(sorted(out_any)) or "none")))

    # No paragraph overlap. A strong subject in the title is independent
    # evidence and is enough on its own: "9-11 Response and Biometric Entry-Exit
    # Fee for H-1B and L-1 Visas" (1651-AB48) is squarely about this site's
    # readers even though it amends a paragraph the FAQ does not happen to cite.
    if in_title:
        return "ACTION", ("subject matches (%s)%s"
                          % (", ".join(sorted(in_title)),
                             "; amends %s, a section the FAQ cites"
                             % ", ".join(sec_overlap) if sec_overlap else
                             "; amends %s, none of it a paragraph the FAQ cites"
                             % (", ".join(sorted(amended)) or "nothing parsed")))

    if sec_overlap:
        return "ACTION", ("amends %s, a section the FAQ cites, though no exact "
                          "paragraph was named" % ", ".join(sec_overlap))

    if not amended:
        # No instructions parsed and no subject signal. Common on proposed rules,
        # which often describe changes in prose. Fail LOUD rather than assume.
        return "ACTION", ("relevance UNKNOWN - no amendatory instructions parsed "
                          "and the subject is ambiguous (in=%s out=%s). Read it."
                          % (", ".join(sorted(in_any)) or "none",
                             ", ".join(sorted(out_any)) or "none"))

    return "WATCH", ("amends %s; none of it is a section or paragraph the FAQ "
                     "cites" % ", ".join(sorted(amended)))


def parse_mdy(month, day, year):
    try:
        return datetime.date(int(year), _MONTHS[month.lower().rstrip(".")], int(day))
    except (KeyError, ValueError):
        return None


def find_dates(text):
    """{date: (sentence, matched_text)} for every date in `text`. The matched
    text is kept so the caller can locate the date in the RAW html and report
    the line the date itself sits on, rather than the line the region starts on.
    dict preserves first-seen order, keeping report output stable run to run."""
    out = {}
    for rx, order in ((_DATE_MDY, "mdy"), (_DATE_DMY, "dmy"), (_DATE_ISO, "iso")):
        for m in rx.finditer(text):
            g = m.groups()
            if order == "mdy":
                d = parse_mdy(g[0], g[1], g[2])
            elif order == "dmy":
                d = parse_mdy(g[1], g[0], g[2])
            else:
                try:
                    d = datetime.date(int(g[0]), int(g[1]), int(g[2]))
                except ValueError:
                    d = None
            if d and d not in out:
                out[d] = (sentence_around(text, m.start()), m.group(0))
    return out


def dates_with_lines(raw_slice, base_line, dates):
    """{date: (sentence, line)}. Locates each date's literal text inside the raw
    slice so the reported line points at the date, not at the region start."""
    out = {}
    for d, (sentence, matched) in dates.items():
        pos = raw_slice.find(matched)
        offset = raw_slice[:pos].count("\n") if pos != -1 else 0
        out[d] = (sentence, base_line + offset)
    return out


def sentence_around(text, pos):
    """The sentence containing offset `pos`. Splits on '. ' only, so the
    abbreviated cites the copy is full of (8 CFR 214.2(f)(5)(vii),
    No. 1:26-cv-13799, D. Mass.) do not shatter it into fragments."""
    start = text.rfind(". ", 0, pos)
    start = 0 if start == -1 else start + 2
    end = text.find(". ", pos)
    end = len(text) if end == -1 else end + 1
    return text[start:end].strip()


# ---------------------------------------------------------------------------
# faq.html parsing
# ---------------------------------------------------------------------------

def parse_faq(faq_path):
    """Return (html, [region dicts]). A region is either a .faq-flag block or
    the prose BETWEEN flags, so a date written in an ordinary paragraph is
    monitored too - just tagged in_flag=False."""
    html = faq_path.read_text(encoding="utf-8")
    # Replace script/style bodies with the SAME number of newlines they held, so
    # every reported faq.html:N still points at the real line. Collapsing them
    # to a single space shifts every later line number, which sent me to the
    # wrong passage when I went to edit one.
    clean = _SCRIPT_STYLE_RE.sub(
        lambda m: "\n" * m.group(0).count("\n"), html)

    # Cut positions are advanced past the end of the enclosing tag. An id=""
    # match sits INSIDE a tag, so slicing at its offset would leave a dangling
    # '<section class="hub-section"' fragment that _TAG_RE cannot strip, and
    # that fragment then leaks into a finding's quoted sentence.
    anchors = []
    for m in _ANCHOR_RE.finditer(clean):
        close = clean.find(">", m.end())
        anchors.append(((close + 1) if close != -1 else m.end(), m.group(1)))

    def anchor_before(pos):
        prior = [a for p, a in anchors if p < pos]
        return prior[-1] if prior else None

    regions = []
    cursor = 0
    for m in _FLAG_RE.finditer(clean):
        if m.start() > cursor:
            regions.extend(
                _split_prose(clean, cursor, m.start(), anchors, anchor_before))
        body = strip_tags(m.group(2))
        base = clean[:m.start()].count("\n") + 1
        regions.append({
            "in_flag": True,
            "flag_kind": m.group(1),
            "anchor": anchor_before(m.start()),
            "line": base,
            "dates": dates_with_lines(m.group(2), base, find_dates(body)),
        })
        cursor = m.end()
    if cursor < len(clean):
        regions.extend(
            _split_prose(clean, cursor, len(clean), anchors, anchor_before))
    return html, regions


def _split_prose(clean, start, end, anchors, anchor_before):
    """Non-flag prose, chunked at each anchor so a finding still points
    somewhere useful. Chunking by anchor rather than emitting one giant blob is
    what makes the anchor on a body-prose finding meaningful."""
    bounds = [p for p, _ in anchors if start < p < end]
    cuts = [start] + bounds + [end]
    out = []
    for i in range(len(cuts) - 1):
        seg = clean[cuts[i]:cuts[i + 1]]
        body = strip_tags(seg)
        if not body:
            continue
        dates = find_dates(body)
        if not dates:
            continue
        base = clean[:cuts[i]].count("\n") + 1
        out.append({
            "in_flag": False,
            "flag_kind": None,
            "anchor": anchor_before(cuts[i] + 1),
            "line": base,
            "dates": dates_with_lines(seg, base, dates),
        })
    return out


def find_stamp(html, cfg):
    m = re.search(cfg["verified_stamp"]["pattern"], html)
    if not m:
        return None
    dates = find_dates(m.group(1))
    return sorted(dates)[0] if dates else None


# ---------------------------------------------------------------------------
# Watch handlers. Each takes (item, verbose) and returns (observed, findings).
# Each may raise; the caller turns that into a GAP and counts a consecutive
# miss, so one dead endpoint never kills the run.
# ---------------------------------------------------------------------------

def _fr_query(params, verbose):
    # Do NOT percent-encode the literal bracket keys - only the values.
    parts = []
    for k, v in params:
        parts.append("%s=%s" % (k, urllib.parse.quote(str(v), safe="")))
    return http_json(FR_API + "?" + "&".join(parts), verbose)


def watch_fr_rin(item, verbose):
    """One rulemaking, by RIN. Query by RIN and NOT by agency: 1615-AD05 is
    filed under the DHS parent and is absent from the USCIS agency feed
    entirely, so an agency-scoped query misses it silently."""
    rin = item["rin"]
    params = [("conditions[regulation_id_number]", rin)]
    for f in ("document_number", "publication_date", "type", "title", "action",
              "html_url"):
        params.append(("fields[]", f))
    params += [("per_page", 5), ("order", "newest")]
    data = _fr_query(params, verbose)
    results = data.get("results") or []
    latest = results[0] if results else {}
    observed = {
        "count": data.get("count") or 0,
        "latest_document_number": latest.get("document_number"),
        "latest_publication_date": latest.get("publication_date"),
        "latest_type": latest.get("type"),
    }
    base = item.get("baseline") or {}
    findings = []
    if (observed["latest_document_number"] != base.get("latest_document_number")
            or observed["count"] != base.get("count")):
        findings.append({
            "key": "fr|%s|%s" % (item["id"], observed["latest_document_number"]),
            "severity": "ACTION",
            "check": "fr-rin",
            "title": "%s: new Federal Register document under RIN %s"
                     % (item["id"], rin),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": ("Baseline %s %s (%s), count %s -> now %s %s (%s), count %s. "
                       "%s | %s | %s"
                       % (base.get("latest_type"),
                          base.get("latest_document_number"),
                          base.get("latest_publication_date"), base.get("count"),
                          latest.get("type"), latest.get("document_number"),
                          latest.get("publication_date"), observed["count"],
                          (latest.get("action") or "").strip(),
                          (latest.get("title") or "").strip()[:150],
                          latest.get("html_url") or "")),
        })
    return observed, findings


def watch_fr_cfr(item, verbose, faq_cites=None):
    """Every rule touching one CFR part since a cutoff. This is the net for
    rulemakings nobody added to the watchlist. Documents whose RIN is already
    watched individually are skipped so they are not double-reported.

    Each NEW document is then scored for relevance (see cfr_relevance) so a
    part-level sweep does not spray ACTIONs for adjacent programs. Nothing is
    dropped: low relevance becomes WATCH, still listed, with the amended
    paragraphs and subject markers needed to dismiss it quickly."""
    faq_cites = faq_cites or set()
    title, part = item["cfr_title"], item["cfr_part"]
    params = [("conditions[cfr][title]", title), ("conditions[cfr][part]", part),
              ("conditions[publication_date][gte]", item.get("since", "2026-01-01"))]
    for f in ("document_number", "publication_date", "type", "title",
              "regulation_id_numbers", "html_url", "abstract", "topics",
              "raw_text_url"):
        params.append(("fields[]", f))
    params += [("per_page", 50), ("order", "newest")]
    data = _fr_query(params, verbose)
    results = data.get("results") or []

    base = item.get("baseline") or {}
    seen = set(base.get("seen_documents") or [])
    known_rins = set(item.get("known_rins") or [])

    findings = []
    for r in results:
        doc = r.get("document_number")
        if not doc or doc in seen:
            continue
        rins = set(r.get("regulation_id_numbers") or [])
        if rins & known_rins:
            log("cfr %s/%s: %s covered by watched RIN %s"
                % (title, part, doc, sorted(rins & known_rins)), verbose)
            continue

        # Relevance needs the rule's own amendatory instructions. Only fetched
        # for NEW documents, so steady-state runs make no extra calls.
        amended = {}
        note = ""
        raw_url = r.get("raw_text_url")
        if raw_url:
            try:
                amended = amended_paragraphs(http_text(raw_url, verbose))
            except Exception as exc:  # noqa: BLE001 - unreadable text must not hide the doc
                note = " (full text unreadable: %s)" % type(exc).__name__
        sev, why = cfr_relevance(r.get("title"), r.get("abstract"),
                                 r.get("topics"), amended, faq_cites,
                                 cfr_title=title)
        findings.append({
            "key": "fr-cfr|%s|%s" % (item["id"], doc),
            # One rule can amend several watched parts (1205-AC30 touches both
            # 20 CFR 655 and 656), so each sweep would report it separately.
            # run_watches merges on this so a document is listed once.
            "merge_doc": doc,
            "merge_part": "%s CFR %s" % (title, part),
            "severity": sev,
            "check": "fr-cfr",
            "title": "%s: unwatched rule touching %s CFR %s (%s)"
                     % (item["id"], title, part, r.get("publication_date")),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": "%s %s, RIN %s. %s%s | Relevance: %s | %s"
                      % (r.get("type"), doc, ",".join(sorted(rins)) or "none",
                         (r.get("title") or "")[:120], note, why,
                         r.get("html_url") or ""),
        })
    observed = {
        "count": data.get("count") or 0,
        "seen_documents": sorted({r.get("document_number") for r in results
                                  if r.get("document_number")} | seen),
    }
    return observed, findings


def watch_fr_presidential(item, verbose):
    """Presidential documents - proclamations and executive orders - matching a
    search term since a cutoff.

    THIS CLOSES A STRUCTURAL BLIND SPOT. The other Federal Register watches key
    on a RIN or a CFR part. A proclamation has NEITHER: it is not a rulemaking
    and it amends no CFR part, so fr_rin and fr_cfr are both blind to it by
    construction. Yet proclamations under INA 212(f) can restrict entry outright
    - Proclamation 10973 "Restriction on Entry of Certain Nonimmigrant Workers"
    (2025-09-24) is exactly the kind of instrument this site's readers need.

    Volume is low (single digits per year for immigration terms), so unlike the
    CFR sweeps this does not need paragraph-level relevance scoring; there are no
    amendatory instructions to parse anyway. Severity defaults to ACTION because
    these are rare and high-consequence, and drops to WATCH only when the title
    is squarely about an adjacent programme."""
    term = item["term"]
    params = [("conditions[type][]", "PRESDOCU"),
              ("conditions[term]", term),
              ("conditions[publication_date][gte]", item.get("since", "2025-01-01"))]
    for f in ("document_number", "publication_date", "title", "abstract",
              "presidential_document_number", "subtype", "html_url"):
        params.append(("fields[]", f))
    params += [("per_page", 50), ("order", "newest")]
    data = _fr_query(params, verbose)
    results = data.get("results") or []

    base = item.get("baseline") or {}
    seen = set(base.get("seen_documents") or [])

    findings, filtered = [], []
    for r in results:
        doc = r.get("document_number")
        if not doc or doc in seen:
            continue
        title = r.get("title") or ""
        # TITLE GATE. conditions[term] is a FULL-TEXT match and the API has no
        # title-scoped condition (conditions[title] is not supported - it errors).
        # Sanctions and trade orders routinely carry boilerplate suspending "the
        # entry of immigrants and nonimmigrants" for designated persons, so a
        # full-text query alone pulled in tariffs, national parks and commercial
        # fishing. The title is what states the subject, so gate on it.
        if not _PRES_TITLE_RE.search(title):
            filtered.append("%s (%s)" % (title[:70], r.get("publication_date")))
            continue
        out_title = set(m.lower() for m in _OUT_SCOPE_RE.findall(title))
        in_title = set(m.lower() for m in _IN_STRONG_RE.findall(title))
        sev = "WATCH" if (out_title and not in_title) else "ACTION"
        why = (("subject is %s, an adjacent programme"
                % ", ".join(sorted(out_title))) if sev == "WATCH" else
               ("title is immigration-relevant; proclamations can restrict entry "
                "directly and are invisible to any RIN or CFR watch"))
        findings.append({
            "key": "fr-pres|%s|%s" % (item["id"], doc),
            "merge_doc": doc,
            "merge_part": "presidential: %s" % term,
            "severity": sev,
            "check": "fr-presidential",
            "title": "%s: new %s (%s)"
                     % (item["id"], (r.get("subtype") or "presidential document"),
                        r.get("publication_date")),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": "%s no. %s, doc %s. %s | Relevance: %s | %s"
                      % (r.get("subtype") or "Presidential document",
                         r.get("presidential_document_number") or "n/a", doc,
                         title[:130], why, r.get("html_url") or ""),
        })

    # Nothing is silently dropped: the title-gated remainder is reported ONCE as
    # an aggregate so a human can see the count and spot-check, without 30
    # separate finding blocks burying the ones that matter.
    if filtered:
        findings.append({
            "key": "fr-pres-filtered|%s|%d" % (item["id"], len(filtered)),
            "severity": "WATCH",
            "check": "fr-presidential",
            "title": "%s: %d further presidential document(s) matched the term "
                     "but not the title gate" % (item["id"], len(filtered)),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": ("Matched on full text only - almost always the standard "
                       "clause suspending entry of designated persons. Titles: %s"
                       % "; ".join(filtered[:8])
                       + (" ... and %d more" % (len(filtered) - 8)
                          if len(filtered) > 8 else "")),
        })
    observed = {
        "count": data.get("count") or 0,
        "seen_documents": sorted({r.get("document_number") for r in results
                                  if r.get("document_number")} | seen),
    }
    return observed, findings


def watch_courtlistener(item, verbose):
    """One federal docket, via the CourtListener /search/ endpoint - the only
    one that answers anonymously (/docket-entries/ and /dockets/{id}/ return
    401). recap_documents here is a SUBSET of the docket, so this detects that
    the case moved, not the complete filing history."""
    q = 'docketNumber:"%s"' % item["docket_number"]
    url = CL_SEARCH + "?" + urllib.parse.urlencode({"q": q, "type": "r"})
    data = http_json(url, verbose)
    results = data.get("results") or []
    if not results:
        raise RuntimeError("docket %s returned no results" % item["docket_number"])

    # Guard against a docket-number collision across courts.
    court = item.get("court_id")
    match = next((r for r in results if not court or r.get("court_id") == court),
                 results[0])

    docs = match.get("recap_documents") or []
    def _num(e):
        try:
            return int(e.get("document_number") or 0)
        except (TypeError, ValueError):
            return 0
    max_doc = max([_num(e) for e in docs] or [0])
    entry_dates = sorted([e.get("entry_date_filed") for e in docs
                          if e.get("entry_date_filed")])
    observed = {
        "date_terminated": match.get("dateTerminated"),
        "max_document_number": max_doc,
        "latest_entry_date": entry_dates[-1] if entry_dates else None,
        "docket_id": match.get("docket_id"),
    }
    base = item.get("baseline") or {}
    findings = []
    link = "https://www.courtlistener.com%s" % (
        match.get("docket_absolute_url") or "")

    if observed["date_terminated"] and not base.get("date_terminated"):
        findings.append({
            "key": "docket|%s|terminated" % item["id"],
            "severity": "ACTION",
            "check": "litigation",
            "title": "%s: docket %s was TERMINATED on %s"
                     % (item["id"], item["docket_number"],
                        observed["date_terminated"]),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": "%s. Read the final order before touching the answers. %s"
                      % (match.get("caseName") or "", link),
        })

    if max_doc > int(base.get("max_document_number") or 0):
        new = [e for e in docs if _num(e) > int(base.get("max_document_number") or 0)]
        descs = [((e.get("short_description") or e.get("description") or "").strip())
                 for e in new]
        ruling = [d for d in descs if _RULING_RE.search(d)]
        findings.append({
            "key": "docket|%s|entry-%d" % (item["id"], max_doc),
            "severity": "ACTION" if ruling else "WATCH",
            "check": "litigation",
            "title": "%s: docket %s has new filings up to entry %d%s"
                     % (item["id"], item["docket_number"], max_doc,
                        " (looks like a ruling)" if ruling else ""),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": "New: %s | %s"
                      % ("; ".join(d[:90] for d in descs[:4]) or "(no description)",
                         link),
        })
    return observed, findings


def watch_wayback_digest(item, verbose):
    """Detect that an origin page changed WITHOUT fetching the origin. Reads
    archive.org capture digests, because uscis.gov / travel.state.gov are
    Cloudflare-walled and this project never fetches or bypasses them
    (RUNBOOK.md). A digest change includes cosmetic edits - nav, banners,
    footers - so this is a 'go look' pointer, not proof of a substantive change."""
    url = item["url"]
    q = ("%s?url=%s&output=json&fl=timestamp,digest,statuscode"
         "&filter=statuscode:200&collapse=digest&limit=-%d"
         % (CDX_API, urllib.parse.quote(url, safe=""), item.get("captures", 4)))
    rows = http_json(q, verbose)
    if not rows or len(rows) < 2:
        raise RuntimeError("no archive.org captures for %s" % url)
    data = rows[1:]
    ts, digest = data[-1][0], data[-1][1]
    observed = {"latest_digest": digest, "latest_capture": ts}
    base = item.get("baseline") or {}
    findings = []
    if base.get("latest_digest") and digest != base["latest_digest"]:
        findings.append({
            "key": "wayback|%s|%s" % (item["id"], digest),
            "severity": "WATCH",
            "check": "page",
            "title": "%s: archived page content changed (capture %s)"
                     % (item["id"], ts),
            "anchor": (item.get("faq_anchors") or [None])[0],
            "detail": ("%s. Digest %s -> %s. May be cosmetic. "
                       "https://web.archive.org/web/%s/%s"
                       % (item.get("what", url), base["latest_digest"][:12],
                          digest[:12], ts, url)),
        })
    return observed, findings


HANDLERS = {
    "fr_rin": watch_fr_rin,
    "fr_cfr": watch_fr_cfr,
    "fr_presidential": watch_fr_presidential,
    "courtlistener_docket": watch_courtlistener,
    "wayback_digest": watch_wayback_digest,
}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_dates(regions, cfg, today):
    scan = cfg.get("date_scan") or {}
    horizon = int(scan.get("horizon_days", 45))
    ack = set()
    for s in scan.get("acknowledged_past") or []:
        try:
            ack.add(datetime.date.fromisoformat(s))
        except ValueError:
            pass

    # A date inside a volatility flag is a PROMISE about a pending change, so a
    # passed one means the answer is now wrong -> ACTION. A date in ordinary
    # body prose is almost always a historical citation ("the rule took effect
    # April 1, 2024"), so passed ones are ignored by default; otherwise every
    # citation on the page would need suppressing by hand. Future dates are
    # reported from BOTH, because a pending change written into a paragraph
    # instead of a flag still needs catching.
    report_past_in_body = bool(scan.get("report_past_in_body", False))

    findings = []
    for r in regions:
        for d, (sentence, dline) in r["dates"].items():
            if d in ack:
                continue
            delta = (d - today).days
            if delta < 0:
                if not r["in_flag"] and not report_past_in_body:
                    continue
                sev, verb = "ACTION", "PASSED %d days ago" % abs(delta)
            elif delta <= horizon:
                sev, verb = "SOON", "in %d days" % delta
            else:
                continue
            where = "flag" if r["in_flag"] else "body prose"
            findings.append({
                "key": "date|%s|%s|%s" % (r["anchor"], d.isoformat(), where),
                "severity": sev,
                "check": "date",
                "title": "%s (%s, %s)" % (d.isoformat(), verb, where),
                "anchor": r["anchor"],
                "detail": sentence,
                "line": dline,
            })
    return findings


def check_watch_dates(cfg, today):
    """Dates carried in the config rather than the copy: effective dates and
    comment-period closes."""
    horizon = int((cfg.get("date_scan") or {}).get("horizon_days", 45))
    findings = []
    for item in cfg.get("watch") or []:
        anchors = item.get("faq_anchors") or []
        for field, past, future in (
                ("effective_date", "effective date", "effective date"),
                ("comments_close", "comment period closed", "comments close")):
            raw = item.get(field)
            if not raw:
                continue
            try:
                d = datetime.date.fromisoformat(raw)
            except ValueError:
                continue
            delta = (d - today).days
            if delta < 0 and field == "comments_close":
                findings.append({
                    "key": "watch-date|%s|%s|%s" % (item["id"], field, raw),
                    "severity": "WATCH", "check": "watch-date",
                    "title": "%s: %s %s (%d days ago)"
                             % (item["id"], past, raw, abs(delta)),
                    "anchor": anchors[0] if anchors else None,
                    "detail": "A final rule can issue at any time. %s"
                              % item.get("why_it_matters", ""),
                })
            elif 0 <= delta <= horizon:
                findings.append({
                    "key": "watch-date|%s|%s|%s" % (item["id"], field, raw),
                    "severity": "SOON", "check": "watch-date",
                    "title": "%s: %s %s (in %d days)"
                             % (item["id"], future, raw, delta),
                    "anchor": anchors[0] if anchors else None,
                    "detail": item.get("why_it_matters", ""),
                })
    return findings


def check_litigation_stamp(html, cfg, today):
    """The litigation line carries its OWN checked-on date, with a much shorter
    life than the page-level stamp. A docket can move in a day while the rest of
    an answer stays accurate for months, so the generic passed-date logic is the
    wrong tool: it would fire the morning after the check. This ages it instead."""
    conf = cfg.get("litigation_stamp") or {}
    pattern = conf.get("pattern")
    if not pattern:
        return []
    m = re.search(pattern, html)
    if not m:
        return [{
            "key": "litigation-stamp|missing", "severity": "ACTION",
            "check": "litigation-stamp",
            "title": "Could not find the litigation-status checked date",
            "anchor": conf.get("anchor"),
            "detail": "The litigation_stamp pattern no longer matches faq.html. "
                      "Either the line was reworded or the dated claim was "
                      "removed while the case is still live.",
        }]
    dates = find_dates(m.group(1))
    if not dates:
        return []
    stamp = sorted(dates)[0]
    age = (today - stamp).days
    limit = int(conf.get("max_age_days", 14))
    if age > limit:
        return [{
            "key": "litigation-stamp|%s" % stamp.isoformat(),
            "severity": "ACTION", "check": "litigation-stamp",
            "title": "Litigation status is %d days old (limit %d)" % (age, limit),
            "anchor": conf.get("anchor"),
            "detail": "faq.html says the docket was last checked on %s. This is "
                      "the fastest-moving fact on the site. Re-read the docket "
                      "and update the date, even if nothing changed."
                      % stamp.isoformat(),
        }]
    return []


def check_stamp(stamp, cfg, today):
    if stamp is None:
        return [{
            "key": "stamp|missing", "severity": "ACTION", "check": "stamp",
            "title": "Could not find the 'Last checked' stamp in faq.html",
            "anchor": None,
            "detail": "The verified_stamp pattern in faq_tripwires.json no "
                      "longer matches - the stamp was reworded or removed.",
        }]
    age = (today - stamp).days
    limit = int(cfg["verified_stamp"].get("max_age_days", 90))
    if age > limit:
        return [{
            "key": "stamp|%s" % stamp.isoformat(), "severity": "ACTION",
            "check": "stamp",
            "title": "Verification stamp is %d days old (limit %d)" % (age, limit),
            "anchor": None,
            "detail": "faq.html says answers were last checked against primary "
                      "sources on %s. Re-verify and update the stamp."
                      % stamp.isoformat(),
        }]
    return []


def run_watches(cfg, ledger, verbose, faq_cites=None):
    """Execute every network watch. A failure becomes a GAP, and after
    max_consecutive_failures it escalates to ACTION - otherwise a permanently
    broken endpoint would look identical to 'nothing changed'."""
    findings, observed = [], {}
    limit = int(cfg.get("max_consecutive_failures", 3))
    misses = ledger.setdefault("consecutive_failures", {})

    for item in cfg.get("watch") or []:
        kind = item.get("kind")
        handler = HANDLERS.get(kind)
        if handler is None:
            continue
        wid = item["id"]
        try:
            if kind == "fr_cfr":
                obs, found = handler(item, verbose, faq_cites=faq_cites)
            else:
                obs, found = handler(item, verbose)
        except Exception as exc:  # noqa: BLE001 - one dead endpoint must not kill the run
            misses[wid] = int(misses.get(wid, 0)) + 1
            n = misses[wid]
            log("%s FAILED (%d consecutive): %s" % (wid, n, exc), verbose)
            findings.append({
                "key": "gap|%s" % wid,
                "severity": "ACTION" if n >= limit else "GAP",
                "check": "gap",
                "title": "%s: not checked (%d consecutive failure%s)"
                         % (wid, n, "" if n == 1 else "s"),
                "anchor": (item.get("faq_anchors") or [None])[0],
                "detail": "%s: %s%s" % (type(exc).__name__, exc,
                                        " - at or past the %d-failure limit, so "
                                        "this is now an ACTION." % limit
                                        if n >= limit else ""),
            })
            continue
        misses[wid] = 0
        observed[wid] = obs
        findings.extend(found)
        if not found:
            log("%s: no change" % wid, verbose)
    return merge_cross_sweep(findings, verbose), observed


def merge_cross_sweep(findings, verbose):
    """Collapse CFR-sweep findings that describe the SAME document. A rule can
    amend several watched parts, so without this a reader sees one document
    listed two or three times with identical reasoning. The merged entry names
    every part it touched and keeps the highest severity."""
    out, by_doc = [], {}
    for f in findings:
        doc = f.get("merge_doc")
        if not doc:
            out.append(f)
            continue
        if doc in by_doc:
            prev = by_doc[doc]
            prev["_parts"].append(f.get("merge_part"))
            if _ORDER[f["severity"]] < _ORDER[prev["severity"]]:
                prev["severity"] = f["severity"]
            log("merged duplicate sweep hit for %s" % doc, verbose)
        else:
            f["_parts"] = [f.get("merge_part")]
            by_doc[doc] = f
            out.append(f)
    for f in by_doc.values():
        parts = [p for p in f.pop("_parts", []) if p]
        if len(parts) > 1:
            # Rewrite the title so it names every part rather than just the
            # sweep that happened to be evaluated first.
            f["title"] = re.sub(r"touching [^(]+\(", "touching %s (" %
                                ", ".join(sorted(set(parts))), f["title"])
    return out


# ---------------------------------------------------------------------------
# Ledger + report
# ---------------------------------------------------------------------------

_ORDER = {"ACTION": 0, "SOON": 1, "WATCH": 2, "GAP": 3}


def load_ledger(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"last_run": None, "last_fingerprint": None,
            "seen_findings": {}, "consecutive_failures": {}}


def fingerprint(findings):
    basis = "|".join(sorted("%s=%s" % (f["key"], f["severity"]) for f in findings))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def classify(findings, ledger, today):
    """Split into new-or-escalated vs still-open. Suppression is a REPORTING
    concern only - the exit code below considers every current ACTION, so a
    long-lived unresolved finding keeps failing the build."""
    seen = ledger.get("seen_findings") or {}
    fresh, ongoing = [], []
    for f in findings:
        prev = seen.get(f["key"])
        if prev is None:
            f["since"] = today.isoformat()
            fresh.append(f)
        elif _ORDER[f["severity"]] < _ORDER.get(prev.get("severity", "GAP"), 3):
            f["since"] = prev.get("first_seen", today.isoformat())
            f["escalated_from"] = prev.get("severity")
            fresh.append(f)
        else:
            f["since"] = prev.get("first_seen", today.isoformat())
            ongoing.append(f)
    return fresh, ongoing


def render(fresh, ongoing, regions, stamp, today, watch_count):
    all_f = fresh + ongoing
    lines = ["# FAQ staleness report - %s" % today.isoformat(), ""]
    n_dates = sum(len(r["dates"]) for r in regions)
    lines.append("Scanned %d dates across %d regions of faq.html (%d in "
                 "volatility flags). Verification stamp: %s. Network watches: %d."
                 % (n_dates, len(regions),
                    sum(len(r["dates"]) for r in regions if r["in_flag"]),
                    stamp.isoformat() if stamp else "NOT FOUND", watch_count))
    lines.append("")

    if not all_f:
        lines.append("**Nothing needs action.** No date has passed or is inside "
                     "the horizon, no watched rulemaking or docket has moved, no "
                     "archived page changed, and the stamp is current.")
        return "\n".join(lines) + "\n"

    counts = {}
    for f in all_f:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    lines.append("**%s** (%d new or escalated, %d still open)"
                 % (", ".join("%d %s" % (counts[k], k)
                              for k in sorted(counts, key=lambda x: _ORDER[x])),
                    len(fresh), len(ongoing)))
    lines.append("")
    lines.append("ACTION = an answer is now wrong, a rule moved, or a check has "
                 "been failing. SOON = inside the horizon. WATCH = a window "
                 "opened or a page changed. GAP = could not be checked.")
    lines.append("")

    for label, bucket in (("New or escalated since the last run", fresh),
                          ("Still open", ongoing)):
        if not bucket:
            continue
        lines.append("## %s" % label)
        lines.append("")
        for sev in sorted({f["severity"] for f in bucket},
                          key=lambda x: _ORDER[x]):
            lines.append("### %s" % sev)
            lines.append("")
            for f in sorted([x for x in bucket if x["severity"] == sev],
                            key=lambda x: x["title"]):
                where = ""
                if f.get("anchor"):
                    where = " - [`#%s`](faq.html#%s)" % (f["anchor"], f["anchor"])
                if f.get("line"):
                    where += " (faq.html:%d)" % f["line"]
                extra = ""
                if f.get("escalated_from"):
                    extra = " _(was %s)_" % f["escalated_from"]
                elif bucket is ongoing:
                    extra = " _(since %s)_" % f.get("since", "?")
                lines.append("- **%s**%s%s" % (f["title"], where, extra))
                if f.get("detail"):
                    lines.append("  %s" % f["detail"].strip())
                lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Report which FAQ answers went stale: passed dates, "
                    "Federal Register movement by RIN and CFR part, litigation "
                    "docket movement, archived page changes, stamp age.")
    ap.add_argument("--faq", default=str(ROOT / "faq.html"))
    ap.add_argument("--tripwires", default=str(HERE / "faq_tripwires.json"))
    ap.add_argument("--ledger", default=str(HERE / "faq_staleness_ledger.json"))
    ap.add_argument("--out", default=None,
                    help="write the markdown report here")
    ap.add_argument("--date", default=None, help="treat this YYYY-MM-DD as today")
    ap.add_argument("--skip-network", action="store_true",
                    help="dates and stamp only; no API calls")
    ap.add_argument("--update-baselines", action="store_true",
                    help="accept observed state into the tripwire ledger")
    ap.add_argument("--no-ledger-write", action="store_true",
                    help="do not record findings as seen (keeps them 'new')")
    ap.add_argument("--force-report", action="store_true",
                    help="write --out even when findings are unchanged")
    ap.add_argument("--fail-on-action", action="store_true",
                    help="exit 2 when any ACTION finding is present")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    today = (datetime.date.fromisoformat(args.date) if args.date
             else datetime.date.today())
    faq_path, trip_path = pathlib.Path(args.faq), pathlib.Path(args.tripwires)
    ledger_path = pathlib.Path(args.ledger)
    for p, what in ((faq_path, "faq.html"), (trip_path, "tripwire ledger")):
        if not p.exists():
            sys.stderr.write("%s not found at %s\n" % (what, p))
            return 1

    cfg = json.loads(trip_path.read_text(encoding="utf-8"))
    ledger = load_ledger(ledger_path)
    html, regions = parse_faq(faq_path)
    stamp = find_stamp(html, cfg)
    log("parsed %d regions, %d dates, stamp=%s"
        % (len(regions), sum(len(r["dates"]) for r in regions), stamp),
        args.verbose)

    findings = []
    findings += check_stamp(stamp, cfg, today)
    findings += check_litigation_stamp(html, cfg, today)
    findings += check_dates(regions, cfg, today)
    findings += check_watch_dates(cfg, today)

    observed, watch_count = {}, 0
    if args.skip_network:
        log("--skip-network: no API calls", args.verbose)
    else:
        faq_cites = extract_faq_citations(html)
        log("FAQ cites %d CFR section+paragraph pairs" % len(faq_cites),
            args.verbose)
        wf, observed = run_watches(cfg, ledger, args.verbose,
                                   faq_cites=faq_cites)
        findings += wf
        watch_count = len([i for i in (cfg.get("watch") or [])
                           if i.get("kind") in HANDLERS])

    fresh, ongoing = classify(findings, ledger, today)
    report = render(fresh, ongoing, regions, stamp, today, watch_count)
    sys.stdout.write(report)

    fp = fingerprint(findings)
    changed = fp != ledger.get("last_fingerprint")
    if args.out:
        out = pathlib.Path(args.out)
        if changed or args.force_report or not out.exists():
            out.write_text(report, encoding="utf-8")
            log("wrote %s (fingerprint %s)" % (args.out, fp), args.verbose)
        else:
            # Findings are byte-identical to last run. Leaving the file alone
            # means git sees no diff, so the weekly job stops committing noise.
            log("findings unchanged (%s); left %s untouched" % (fp, args.out),
                args.verbose)

    if args.update_baselines and observed:
        for item in cfg.get("watch") or []:
            if item["id"] in observed:
                item["baseline"] = observed[item["id"]]
        trip_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        sys.stderr.write("[faq_staleness] baselines updated: %s\n"
                         % ", ".join(sorted(observed)))

    if not args.no_ledger_write:
        seen = ledger.setdefault("seen_findings", {})
        current = {f["key"] for f in findings}
        for f in findings:
            prev = seen.get(f["key"]) or {}
            seen[f["key"]] = {
                "severity": f["severity"],
                "first_seen": prev.get("first_seen", today.isoformat()),
                "last_seen": today.isoformat(),
            }
        for key in [k for k in seen if k not in current]:
            del seen[key]  # resolved; forget it so it re-reports if it returns
        ledger["last_run"] = today.isoformat()
        ledger["last_fingerprint"] = fp
        ledger_path.write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.fail_on_action and any(f["severity"] == "ACTION" for f in findings):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
