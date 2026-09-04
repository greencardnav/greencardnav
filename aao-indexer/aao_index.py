#!/usr/bin/env python3
"""
aao_index.py - build your own searchable index of USCIS AAO non-precedent decisions.

WHY THIS EXISTS
---------------
Every community tool in this space (casereviewer.ai, the open-source comparison
scripts) is a layer over one free public dataset: the USCIS Administrative Appeals
Office non-precedent decisions. None of them has data you cannot get yourself.

Two of them have a defect worth avoiding. They summarise each decision with an LLM.
casereviewer.ai's own launch thread contains a reader finding a case labelled as
denied where the PDF showed the prongs were met and the appeal sustained. One
open-source script costs $30-$40 in API calls for a full run.

So this tool parses DETERMINISTICALLY. Every field it emits is a regex over the
decision's own words, and it records the exact matched span so any row can be
audited against the PDF. Nothing is inferred, nothing is generated, and a field it
cannot parse is left empty rather than guessed. Cost: zero.

USAGE
-----
  python3 aao_index.py fetch  --category niw --pages 4        # download + cache PDFs
  python3 aao_index.py parse                                  # parse cache -> out/
  python3 aao_index.py report                                 # aggregates to stdout
  python3 aao_index.py search --occupation software            # grep the index
  python3 aao_index.py all --category niw --pages 4            # fetch, parse, report

Requires: python3 stdlib + `pdftotext` (poppler). No API keys, no packages.

SOURCE OF TRUTH
---------------
  https://www.uscis.gov/administrative-appeals/aao-decisions/aao-non-precedent-decisions
  uri_1=18 -> B5, Advanced Degree / Exceptional Ability (this is where NIW lives)
  uri_1=19 -> B2, Extraordinary Ability (EB-1A)
Note uri_1=18 contains BOTH NIW and non-NIW EB-2 cases. USCIS reports ~8,934 rows
there; a third-party index reports 4,167 after filtering to NIW only. Both can be
right. This tool records whether each decision actually mentions a national
interest waiver so you can filter honestly rather than trusting a label.

This is read-only research against public documents, at a deliberate crawl delay.
It is NOT wired into any scheduled automation.
"""

import argparse, csv, datetime, json, os, re, subprocess, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
LISTING = "https://www.uscis.gov/administrative-appeals/aao-decisions/aao-non-precedent-decisions"
CRAWL_DELAY = 1.0   # be a good citizen

CATEGORIES = {
    "niw":   ("18", "B5 - Advanced Degree / Exceptional Ability (includes EB-2 NIW)"),
    "eb1a":  ("19", "B2 - Extraordinary Ability (EB-1A)"),
}


# ----------------------------------------------------------------------------- http
def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


# ---------------------------------------------------------------------------- fetch
# The listing's year <select> takes an ORDINAL, not the year: y=1 is 2026, y=2 is
# 2025, and so on. Passing y=2024 silently returns zero results, which is how the
# first attempt at year filtering appeared to fail. There are 22 year options.
YEAR_BASE = 2027   # ordinal = YEAR_BASE - year


def year_param(year):
    if year in (None, "All", "all"):
        return "All"
    y = int(year)
    ordinal = YEAR_BASE - y
    if not 1 <= ordinal <= 22:
        raise SystemExit("year %s is outside the listing's range (2005-2026)" % y)
    return str(ordinal)


def fetch(category, pages, per_page=50, year="All"):
    uri, label = CATEGORIES[category]
    os.makedirs(CACHE, exist_ok=True)
    print("category %s -> uri_1=%s  (%s)  year=%s" % (category, uri, label, year))
    seen, got, skipped, empty_streak = [], 0, 0, 0
    for page in range(pages):
        q = urllib.parse.urlencode({"uri_1": uri, "m": "All", "y": year_param(year),
                                    "items_per_page": per_page, "page": page})
        print("  listing page %d ..." % page, end=" ", flush=True)
        # A single failed or empty listing page is usually a transient, not the end
        # of the results. Retry with backoff, and only stop after TWO consecutive
        # empty pages - an earlier version broke on the first one and silently
        # truncated the crawl at 50 decisions.
        hrefs = []
        for attempt in range(3):
            try:
                html = get(LISTING + "?" + q)
                hrefs = list(dict.fromkeys(
                    re.findall(r'href="(/sites/default/files/err/[^"]+\.pdf)"', html)))
                if hrefs:
                    break
            except Exception as e:
                print("[retry %d: %s]" % (attempt + 1, e), end=" ", flush=True)
            time.sleep(2 * (attempt + 1))
        print("%d pdf links" % len(hrefs))
        if not hrefs:
            empty_streak += 1
            if empty_streak >= 2:
                print("  two consecutive empty pages; stopping"); break
            continue
        empty_streak = 0
        for href in hrefs:
            name = urllib.parse.unquote(href.rsplit("/", 1)[-1])
            dest = os.path.join(CACHE, name)
            seen.append(name)
            if os.path.exists(dest) and os.path.getsize(dest) > 10000:
                skipped += 1
                continue
            try:
                blob = get("https://www.uscis.gov" + href, binary=True)
                with open(dest, "wb") as fh:
                    fh.write(blob)
                got += 1
            except Exception as e:
                print("    ! %s: %s" % (name, e))
            time.sleep(CRAWL_DELAY)
    print("\nlisting yielded %d decisions | downloaded %d new | %d already cached"
          % (len(seen), got, skipped))
    return seen


def to_text():
    """pdftotext every cached PDF that lacks a .txt sibling."""
    made = 0
    for f in sorted(os.listdir(CACHE)):
        if not f.lower().endswith(".pdf"):
            continue
        txt = os.path.join(CACHE, f[:-4] + ".txt")
        if os.path.exists(txt) and os.path.getsize(txt) > 200:
            continue
        try:
            subprocess.run(["pdftotext", "-layout", os.path.join(CACHE, f), txt],
                           check=True, capture_output=True)
            made += 1
        except Exception as e:
            print("  ! pdftotext %s: %s" % (f, e))
    return made


# ---------------------------------------------------------------------------- parse
# Every pattern below was validated against real decision text. Each returns the
# matched span so a row can be audited back to the PDF.

RE_CASEID = re.compile(r'In\s*Re:\s*(\d{5,})', re.I)
RE_DATE = re.compile(r'Date:\s*([A-Z]{3}\.?\s*\d{1,2},\s*\d{4})', re.I)
# Pre-2017 decisions use a different header entirely: "DATE: APR 0 3 2015", with the
# day split across characters by the OCR and no comma. The modern pattern misses
# every one of them, which silently blanked the date on older cases.
RE_DATE_OLD = re.compile(r'DATE:\s*([A-Z]{3})[A-Z]*\.?\s*(\d)\s*(\d)?\s*,?\s*(\d{4})', re.I)

# The DECISION FILENAME is a better date source than the decision text. USCIS names every
# file deterministically as MONDDYYYY_NNB5203, e.g. JUL012021_01B5203, so month, day and year
# are all present with no OCR involved.
#
# Measured across the 4,987-decision corpus before switching:
#   * 4,977 filenames (99.8%) parse to a valid date
#   * 4,694 agree with the date parsed out of the body text
#   * 272 had an unusable body date, and the filename fixes every one. The commonest failure
#     was the OCR reading "JULY" as "WLY" - 41 times - which RE_DATE captured as a
#     three-letter month and stored verbatim, because nothing validated it against a real
#     month name.
#   * only 11 disagree, and in every one the FILENAME is right: the body carries an OCR'd
#     year, e.g. "JAN. 17, 2022" on JAN172023_03B5203, or "JAN. 21, 2016" on a 2026 file.
#     Day and month match; a year digit was misread.
#
# So the filename is primary and the body is the fallback, not the other way round.
RE_FILEDATE = re.compile(r'^([A-Z]{3})(\d{2})(\d{4})_\d+B\d+', re.I)
MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def date_from_filename(fname):
    """-> (display, iso) or (None, None). No OCR: this is USCIS's own file naming."""
    m = RE_FILEDATE.match(os.path.basename(fname or ""))
    if not m:
        return None, None
    mon = m.group(1).upper()
    if mon not in MONTH_NUM:
        return None, None
    try:
        d = datetime.date(int(m.group(3)), MONTH_NUM[mon], int(m.group(2)))
    except ValueError:
        return None, None
    return "%s. %d, %d" % (mon, d.day, d.year), d.isoformat()


def date_from_body(text):
    """The old path, now a fallback. Validates the month instead of trusting three letters -
    that validation is exactly what "WLY" needed and never had."""
    m = RE_DATE.search(text)
    if m:
        raw = norm(m.group(1))
        bm = re.match(r'^([A-Za-z]{3})\.?\s*(\d{1,2}),\s*(\d{4})$', raw)
        if bm and bm.group(1).upper() in MONTH_NUM:
            try:
                d = datetime.date(int(bm.group(3)), MONTH_NUM[bm.group(1).upper()],
                                  int(bm.group(2)))
                return raw, d.isoformat()
            except ValueError:
                pass
        return None, None            # captured something that is not a real date
    m = RE_DATE_OLD.search(text)
    if m:
        mon, d1, d2, yr = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
        if mon in MONTH_NUM:
            day = int((d1 + d2) if d2 else d1)
            try:
                d = datetime.date(int(yr), MONTH_NUM[mon], day)
                return "%s. %d, %s" % (mon, day, yr), d.isoformat()
            except ValueError:
                pass
    return None, None

# The service centre is named only in the older format ("OFFICE: NEBRASKA SERVICE
# CENTER"); modern decisions omit it. So coverage is partial by nature, not by
# parser weakness - the field is left empty rather than guessed.
RE_CENTER = re.compile(r'OFFICE:\s*([A-Z][A-Z ]{3,20}?)\s+SERVICE\s+CENTER', re.I)
RE_CENTER2 = re.compile(r'\b(Nebraska|Texas|California|Vermont|Potomac)\s+Service\s+Center', re.I)

ORDERS = [
    ("dismissed",           r'ORDER:\s*The appeal is (?:summarily )?dismissed'),
    ("sustained",           r'ORDER:\s*The appeal is sustained'),
    ("remanded",            r'ORDER:\s*The (?:decision|matter)[^.]{0,60}(?:withdrawn|remanded)'),
    ("abandoned",           r'dismissed as abandoned'),
    ("motion_dismissed",    r'ORDER:\s*The motion[^.]{0,60}is dismissed'),
    ("motion_granted",      r'ORDER:\s*The motion[^.]{0,60}is granted'),
    ("dismissed",           r'we will dismiss the appeal'),
    ("motion_dismissed",    r'we will dismiss the motion'),
    ("sustained",           r'we will sustain the appeal'),
    ("remanded",            r'we will (?:withdraw|remand)'),
]

# --- occupation cleanup -------------------------------------------------------------
# Applied AFTER extraction, and deliberately minimal: the extraction regexes hit 3,944 of
# 4,987 records, so widening them to chase a handful of malformed values risks the ones that
# already work.
#
# WHAT IS REPAIRED: unbalanced parentheses. The capture stops at , . or ; which truncates
# mid-parenthetical ("STEM (science") or, where no comma intervenes, runs past the occupation
# into the sentence ("mechanical engineer under the employment-based second preference (EB-2").
# Cutting at the unmatched bracket cannot affect a well-formed value.
#
# WHAT IS NOT REPAIRED, AND WHY: OCR digit substitution. The scans read i as 1 and o as 0,
# giving nutnt10nist, computer v1s10n, medical pract1t10ner, se1sm1c. I wrote the substitution
# and then backed it out, because it cannot actually finish the job - the same scans also read
# "ri" as "nt" and "in" as "m", so nutnt10nist repairs to "nutntionist" and se1sm1c structural
# engmeer to "seismic structural engmeer". Both are still wrong, and a half-corrected word
# looks like a real if unusual word, whereas one with digits in it visibly announces that the
# scan is damaged. Silently converting obviously-broken data into plausibly-broken data is the
# worse outcome.
#
# So the damage is FLAGGED instead, in occupation_ocr_suspect, and consumers decide. 11 of
# 4,987 records carry it.
_OCR_SUSPECT = re.compile(r'[A-Za-z][01]|[01][A-Za-z]')


# The capture sometimes runs on past the job title into the surrounding sentence. Only the
# unambiguous noise is trimmed:
#   * "... under the second-preference" / "under the employment-based second preference" is the
#     visa classification, not an occupation. 34 records. Always safe to drop - it says nothing
#     about the petitioner, and it produced sentences like "a physical therapist under the
#     second-preference's appeal was dismissed".
#   * a dangling "who" with nothing after it ("entrepreneur who") is a plain truncation.
# Deliberately NOT trimmed, because these carry real information:
#   * "in the field of ..." (130 records) - "physician-researcher in the field of urologic
#     oncology" is more useful than "physician-researcher".
#   * "seeking to ..." (6 records) - that clause is the proposed endeavor, which is the single
#     most decision-relevant thing about an NIW petition.
#   * "who <does something>" (14 records) - same reason.
_OCC_TRAILING = re.compile(
    r'\s+under\s+the\s+(?:employment[-\s]based\s+)?(?:first|second|third)[-\s]*\s*preference.*$'
    r'|\s+who\s*$', re.I)


def clean_occupation(occ):
    """Trim classification noise and balance parentheses. Returns the cleaned string."""
    if not occ:
        return occ
    out = _OCC_TRAILING.sub("", occ)
    if out.count("(") != out.count(")"):
        cut = out.rfind("(") if out.count("(") > out.count(")") else -1
        if cut > 0:
            out = out[:cut]
        else:
            out = out.replace("(", "").replace(")", "")
    return norm(out).strip(" ,;-")


def occupation_ocr_suspect(occ):
    """True when a digit sits against a letter inside a word - the signature of a bad scan."""
    return bool(occ) and bool(_OCR_SUSPECT.search(occ))


# occupation, as the decision itself states it
# Ordered most-specific first. Patterns 4-6 were added after measuring a 27% miss
# rate: the decisions use at least four different opening constructions, and the
# earlier comma-only pattern caught just one of them.
RE_PET = [
    # "The Petitioner, a computer software engineer, seeks ..."
    re.compile(r'The Petitioner,?\s+(?:an?|the)\s+([^,.;]{3,90}?),\s+seeks', re.I),
    re.compile(r'The Petitioner,?\s+(?:an?|the)\s+([^,.;]{3,90}?),', re.I),
    # "The Petitioner - a researcher and developer of ... - requests ..."
    re.compile(r'The Petitioner\s*[-\u2013\u2014]\s*(?:an?|the)?\s*([^-\u2013\u2014]{3,90}?)\s*[-\u2013\u2014]', re.I),
    # "The Petitioner, who specializes in employee training and development, seeks"
    re.compile(r'The Petitioner,?\s+who (?:specializes in|works as|is)\s+(?:an?|the)?\s*([^,.;]{3,80}?),', re.I),
    # employer-filed: "... seeks to employ the Beneficiary as an associate vice president"
    re.compile(r'seeks to employ the Beneficiary as\s+(?:an?|the)?\s*([^,.;]{3,70})', re.I),
    re.compile(r'The Beneficiary,?\s+(?:an?|the)\s+([^,.;]{3,90}?),', re.I),
]

# prong failure. Kept deliberately tight; a miss is better than a false positive.
PRONG_FAIL = {
    1: r'(?:has not|have not|did not|does not|failed to)\s+(?:establish\w*|demonstrat\w*|show\w*)'
       r'[^.]{0,140}?(?:national importance|substantial merit)',
    2: r'(?:has not|have not|did not|does not|failed to)\s+(?:establish\w*|demonstrat\w*|show\w*)'
       r'[^.]{0,140}?well[\s-]positioned',
    3: r'(?:has not|have not|did not|does not|failed to)\s+(?:establish\w*|demonstrat\w*|show\w*)'
       r'[^.]{0,180}?(?:on balance|beneficial to the United States|waiv\w+ the (?:job offer|requirement))',
}

RE_DECLINE = re.compile(
    r'declin\w+ to reach[^.]{0,200}?(?:second|third|remaining)[^.]{0,120}prong', re.I)
RE_NIW = re.compile(r'national interest waiver', re.I)
RE_ADVDEG = re.compile(r'advanced degree', re.I)
RE_EXCEPT = re.compile(r'exceptional ability', re.I)
RE_BACH5 = re.compile(r'baccalaureate[^.]{0,120}five years|five years[^.]{0,120}progressive', re.I)

PRECEDENTS = {
    "Chawathe":   r'Chawathe',          # preponderance of the evidence standard
    "Dhanasar":   r'Dhanasar',          # the three-prong NIW framework
    "Bagamasbad": r'Bagamasbad',        # need not make purely advisory findings
    "Christo's":  r"Christo",           # de novo review
    "Katigbak":   r'Katigbak',          # eligibility at time of filing
    "Izummi":     r'Izummi',            # cannot cure via post-filing changes
    "Furtado":    r'Furtado',           # new evidence on appeal
}

# recurring adverse phrases worth counting
PHRASES = {
    "beyond_employer":  r'beyond (?:his|her|their|the Petitioner\'s) (?:employer|company|clients|customers)',
    "not_industry":     r'not the importance of the (?:industry|field|profession)',
    "conclusory":       r'conclusor\w+',
    "generalized":      r'generaliz\w+',
    "speculative":      r'speculat\w+',
    "unsupported":      r'unsupported',
    "teaching_analogy": r'teaching activities',
    "material_change":  r'material change',
    "inconsistent":     r'inconsisten\w+',
}


def norm(x):
    return re.sub(r'\s+', ' ', x).strip()


def parse_one(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    t = norm(raw)
    rec = {"file": os.path.basename(path)}

    m = RE_CASEID.search(t); rec["case_id"] = m.group(1) if m else ""
    # Filename first (no OCR), body text as fallback. date_iso is new: consumers can sort and
    # bucket without re-parsing a display string, which the dashboard and the decisions
    # browser both had to do independently.
    fn_disp, fn_iso = date_from_filename(rec.get("file", ""))
    bd_disp, bd_iso = date_from_body(t)
    if fn_iso:
        rec["date"], rec["date_iso"], rec["date_source"] = fn_disp, fn_iso, "filename"
        rec["date_body_disagrees"] = "yes" if (bd_iso and bd_iso != fn_iso) else ""
    elif bd_iso:
        rec["date"], rec["date_iso"], rec["date_source"] = bd_disp, bd_iso, "body"
        rec["date_body_disagrees"] = ""
    else:
        rec["date"], rec["date_iso"], rec["date_source"] = "", "", ""
        rec["date_body_disagrees"] = ""

    m = RE_CENTER.search(t) or RE_CENTER2.search(t)
    rec["service_center"] = norm(m.group(1)).title() if m else ""

    rec["outcome"] = ""
    rec["outcome_evidence"] = ""
    tail = t[-4000:]
    for label, pat in ORDERS:
        m = re.search(pat, tail, re.I) or re.search(pat, t, re.I)
        if m:
            rec["outcome"] = label
            rec["outcome_evidence"] = norm(m.group(0))[:140]
            break

    # Occupation is only trustworthy from the decision's opening recital, so search
    # the intro only. Anything containing a pronoun or verb is a sentence fragment
    # the regex grabbed by accident, not a job title - reject rather than emit it.
    BAD = re.compile(r'\b(?:he|she|they|his|her|their|not|which|that|projects|'
                     r'purported|proposes|undertake|would|will|has|have|is|are|'
                     r'seeks|filed|submitted)\b', re.I)
    intro = t[:3000]
    rec["occupation"] = ""
    rec["occupation_generic"] = ""
    rec["occupation_ocr_suspect"] = ""
    for r in RE_PET:
        for m in r.finditer(intro):
            occ = clean_occupation(norm(m.group(1)))
            if BAD.search(occ) or len(occ.split()) > 12:
                continue
            if re.match(r'member of the professions', occ, re.I):
                rec["occupation_generic"] = rec["occupation_generic"] or occ
                continue
            rec["occupation"] = occ
            rec["occupation_ocr_suspect"] = "yes" if occupation_ocr_suspect(occ) else ""
            break
        if rec["occupation"]:
            break
    if not rec["occupation"]:
        rec["occupation"] = rec["occupation_generic"]

    failed = []
    for n, pat in PRONG_FAIL.items():
        if re.search(pat, t, re.I):
            failed.append(n)
    rec["prongs_failed"] = "".join(str(x) for x in failed)
    rec["declined_to_reach"] = "yes" if RE_DECLINE.search(t) else ""

    rec["is_niw"] = "yes" if RE_NIW.search(t) else ""
    rec["route"] = ("advanced_degree" if RE_ADVDEG.search(t) else "") + \
                   ("+exceptional" if RE_EXCEPT.search(t) else "")
    rec["bach_plus_5"] = "yes" if RE_BACH5.search(t) else ""

    for name, pat in PRECEDENTS.items():
        rec["cite_" + name.replace("'", "")] = "yes" if re.search(pat, t, re.I) else ""
    for name, pat in PHRASES.items():
        rec["ph_" + name] = len(re.findall(pat, t, re.I))

    rec["words"] = len(t.split())
    return rec


FIELDS = ["file", "case_id", "date", "service_center", "outcome", "occupation", "prongs_failed",
          "declined_to_reach", "is_niw", "route", "bach_plus_5", "words",
          "cite_Chawathe", "cite_Dhanasar", "cite_Bagamasbad", "cite_Christos",
          "cite_Katigbak", "cite_Izummi", "cite_Furtado"] + \
         ["ph_" + k for k in PHRASES] + ["outcome_evidence"]


def parse_all():
    os.makedirs(OUT, exist_ok=True)
    made = to_text()
    if made:
        print("extracted text from %d new PDFs" % made)
    rows = []
    for f in sorted(os.listdir(CACHE)):
        if f.lower().endswith(".txt"):
            rows.append(parse_one(os.path.join(CACHE, f)))
    rows.sort(key=lambda r: r["file"])
    with open(os.path.join(OUT, "decisions.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(OUT, "decisions.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)
    print("parsed %d decisions -> out/decisions.csv and out/decisions.json" % len(rows))
    return rows


# --------------------------------------------------------------------------- report
def report(rows=None):
    p = os.path.join(OUT, "decisions.json")
    if rows is None:
        if not os.path.exists(p):
            print("no index yet; run parse first"); return
        rows = json.load(open(p, encoding="utf-8"))
    n = len(rows)
    if not n:
        print("index empty"); return

    def pct(k, d=None):
        d = d or n
        return "%3d  (%4.1f%%)" % (k, 100.0 * k / d if d else 0)

    print("\n" + "=" * 74)
    print("AAO DECISION INDEX  --  %d decisions" % n)
    print("=" * 74)

    import collections
    oc = collections.Counter(r["outcome"] or "unparsed" for r in rows)
    print("\nOUTCOMES")
    for k, v in oc.most_common():
        print("  %-18s %s" % (k, pct(v)))

    merits = [r for r in rows if r["outcome"] in ("dismissed", "sustained", "remanded")]
    print("\nMERITS-POSTURE ONLY (%d; motions and abandonments excluded)" % len(merits))
    om = collections.Counter(r["outcome"] for r in merits)
    for k, v in om.most_common():
        print("  %-18s %s" % (k, pct(v, len(merits))))

    print("\nPRONG FAILURES  (a decision can fail more than one)")
    for pn in (1, 2, 3):
        c = sum(1 for r in rows if str(pn) in (r["prongs_failed"] or ""))
        print("  prong %d            %s" % (pn, pct(c)))
    print("  none parsed        %s" % pct(sum(1 for r in rows if not r["prongs_failed"])))
    print("  sole ground = P1   %s" % pct(sum(1 for r in rows if r["prongs_failed"] == "1")))
    print("  declined to reach  %s" % pct(sum(1 for r in rows if r["declined_to_reach"])))

    print("\nPRECEDENTS CITED")
    for name in ["Chawathe", "Dhanasar", "Bagamasbad", "Christos", "Katigbak", "Izummi", "Furtado"]:
        c = sum(1 for r in rows if r.get("cite_" + name))
        if c:
            print("  %-12s %s" % (name, pct(c)))

    print("\nRECURRING ADVERSE LANGUAGE (decisions containing it at least once)")
    for k in PHRASES:
        c = sum(1 for r in rows if r.get("ph_" + k))
        if c:
            print("  %-18s %s" % (k, pct(c)))

    print("\nOCCUPATIONS PARSED  (%d of %d)" %
          (sum(1 for r in rows if r["occupation"]), n))
    generic = re.compile(r'member of the professions', re.I)
    real = [r for r in rows if r["occupation"] and not generic.match(r["occupation"])]
    print("  with a real job title: %d" % len(real))
    for r in real[:40]:
        print("    %-22s %-11s %s" % (r["file"].replace(".txt", ""), r["outcome"],
                                      r["occupation"][:56]))

    sc = collections.Counter(r.get("service_center") or "" for r in rows)
    named = sum(v for k, v in sc.items() if k)
    print("\nSERVICE CENTER  (named only in pre-2017 decisions, so coverage is partial)")
    print("  named at all       %s" % pct(named))
    for k, v in sc.most_common():
        if k:
            print("    %-16s %3d" % (k, v))

    print("\nEB-2 route markers")
    print("  mentions NIW        %s" % pct(sum(1 for r in rows if r["is_niw"])))
    print("  bachelor's + 5 yrs  %s" % pct(sum(1 for r in rows if r["bach_plus_5"])))
    print()


def search(**kw):
    p = os.path.join(OUT, "decisions.json")
    rows = json.load(open(p, encoding="utf-8"))
    out = rows
    if kw.get("occupation"):
        q = kw["occupation"].lower()
        out = [r for r in out if q in (r["occupation"] or "").lower()]
    if kw.get("outcome"):
        out = [r for r in out if r["outcome"] == kw["outcome"]]
    if kw.get("prong"):
        out = [r for r in out if kw["prong"] in (r["prongs_failed"] or "")]
    print("%d match(es)" % len(out))
    for r in out:
        print("  %-22s %-11s p%-4s %s" % (r["file"].replace(".txt", ""), r["outcome"],
                                          r["prongs_failed"] or "-", r["occupation"][:56]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "parse", "report", "search", "all"])
    ap.add_argument("--category", default="niw", choices=sorted(CATEGORIES))
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--per-page", type=int, default=50)
    ap.add_argument("--year", default="All",
                    help="Restrict to one decision year, e.g. 2024. The listing is sorted "
                         "newest-first, so without this you only ever reach the most recent "
                         "decisions no matter how many pages you request.")
    ap.add_argument("--all-years", action="store_true",
                    help="Loop 2015..2026, fetching --pages pages of each. This is how you get "
                         "past the newest-first ceiling and build a corpus spanning every year.")
    ap.add_argument("--occupation")
    ap.add_argument("--outcome")
    ap.add_argument("--prong")
    a = ap.parse_args()

    if a.cmd in ("fetch", "all"):
        if a.all_years:
            total = 0
            for y in range(2015, 2027):
                got = fetch(a.category, a.pages, a.per_page, str(y))
                total += len(got)
            print("\nall-years sweep saw %d listing entries" % total)
        else:
            fetch(a.category, a.pages, a.per_page, a.year)
    if a.cmd in ("parse", "all"):
        parse_all()
    if a.cmd in ("report", "all"):
        report()
    if a.cmd == "search":
        search(occupation=a.occupation, outcome=a.outcome, prong=a.prong)


if __name__ == "__main__":
    main()
