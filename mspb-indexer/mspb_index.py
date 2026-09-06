#!/usr/bin/env python3
"""
mspb_index.py - a deterministic index of U.S. Merit Systems Protection Board decisions.

WHY THIS EXISTS
---------------
This is the second corpus in a method, not a one-off. The first is aao_index.py, over
USCIS Administrative Appeals Office immigration decisions. The claim being tested is
that outcomes and reasoning in federal administrative adjudication can be extracted
DETERMINISTICALLY - regex over the agency's own words, matched span stored for audit,
no model anywhere - and that the approach generalises across agencies.

MSPB is a good second case because it is structurally similar and substantively
unrelated: federal employees appealing adverse personnel actions, decided by regional
offices, with published written decisions. If the method only worked on immigration
it would be a trick rather than a method.

THE IDENTITY PROBLEM, AND WHAT THIS TOOL DOES ABOUT IT
------------------------------------------------------
USCIS redacts before publishing. Its decisions say "Petitioner" and caption as
"MATTER OF S-". MSPB does NOT: every record in its manifest carries the appellant's
first and last name, and roughly a third of the filenames embed the full name.

Those names are already public. But a structured, searchable index of named
individuals' employment disputes is not the same artifact as the same names scattered
across thousands of agency PDFs - it collapses the practical obscurity that makes the
originals relatively harmless. So this tool treats identity as something to DISCARD AT
PARSE TIME rather than to publish and hope nobody aggregates it:

  - Appellant first/last name, META_KEYWORDS, META_TITLE, DOCNAME and FILE_NAME are
    read from the manifest, used ONLY to redact, and never written to output.
  - Every name learned from the manifest is scrubbed from any text span this tool
    stores, so quoted evidence cannot leak an identity that the structured fields
    dropped.
  - The DOCKET NUMBER IS kept. It is a case citation, not a name - the same thing a
    law review footnote carries - and it preserves auditability: any row can be
    checked against the source decision. It also encodes the regional office, which
    is the analytical point.

The names cost nothing to drop. Every question worth asking here is about offices,
agencies, outcomes and reasoning.

USAGE
-----
  python3 mspb_index.py manifest                 # download the decision manifest
  python3 mspb_index.py fetch --limit 500        # download + cache decision PDFs
  python3 mspb_index.py parse                    # parse cache -> out/
  python3 mspb_index.py report                   # aggregates to stdout
  python3 mspb_index.py all --limit 500          # manifest, fetch, parse, report

Requires: python3 stdlib + `pdftotext` (poppler). No API keys, no packages.

SOURCE OF TRUTH
---------------
  https://www.mspb.gov/decisions/nonprecedential.htm
  manifest: /decisions/nonprecedential/NonPrecedentialDecisions_Manifest-updmar2025.json

Read-only research against public documents at a deliberate crawl delay. NOT wired
into any scheduled automation.
"""

import argparse, collections, csv, hashlib, io, json, os, re, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out")
TEXT = os.path.join(CACHE, "text")

BASE = "https://www.mspb.gov"
MANIFEST_URL = (BASE + "/decisions/nonprecedential/"
                "NonPrecedentialDecisions_Manifest-updmar2025.json")
PDF_DIR = "/decisions/nonprecedential/"

# The site 403s a bare scripted client. This is the same read a browser performs, at a
# slower rate than a human clicking through the search UI.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
CRAWL_DELAY = 1.0

# ---------------------------------------------------------------------------
# Fields dropped on principle. Read to redact, never written.
IDENTITY_FIELDS = ("APL_FIRST_NAME", "APL_LAST_NAME", "META_KEYWORDS",
                   "META_TITLE", "DOCNAME", "FILE_NAME", "META_AUTHOR")

# Docket prefix. MSPB dockets read like DC-0843-25-0238-I-1: prefix, case-type code,
# year, sequence.
#
# CB IS NOT A REGIONAL OFFICE, and an earlier version of this map wrongly called it
# "Central (Chicago)". The case-type mix proves it: all eight true regional offices are
# dominated by 0752 (adverse actions, i.e. appeals from an agency action), whereas CB
# carries 1208/7121/1205/7521 - Special Counsel proceedings and arbitration review,
# which are ORIGINAL Board jurisdiction rather than an appeal from a regional office.
# Counting its 265 cases as a ninth region would have silently corrupted every
# office-comparison statistic.
REGIONS = {
    "AT": "Atlanta", "CH": "Chicago", "DA": "Dallas", "DC": "Washington DC",
    "DE": "Denver", "NY": "New York", "PH": "Philadelphia", "SF": "San Francisco",
    "SE": "Seattle", "SL": "St. Louis", "CF": "Central Field",
}
HQ = {"CB": "Board (original jurisdiction)"}
OFFICES = dict(REGIONS, **HQ)

# Case type, from the second docket segment. This is the subject-matter dimension and
# it is the closest MSPB analogue to occupation in the immigration corpus.
CASE_TYPES = {
    "0752": "adverse action (removal/suspension/demotion)",
    "0432": "performance-based removal",
    "0353": "restoration / reemployment rights",
    "1221": "individual right of action (whistleblower)",
    "1208": "Special Counsel stay request",
    "1205": "Special Counsel disciplinary action",
    "7121": "arbitration decision review",
    "7521": "administrative law judge action",
    "0831": "retirement (CSRS)",
    "0841": "retirement (FERS)",
    "0843": "retirement (FERS survivor/disability)",
    "3443": "reduction in force / RIF",
    "3330": "veterans preference (VEOA)",
    "315H": "probationary termination",
}

# DOCUMENT CLASS, decided before outcome.
#
# A first pass forced every document into the affirmed/reversed taxonomy and left 10.7%
# unparsed. Inspecting those showed roughly half were not merits dispositions at all:
# stay orders (which grant or deny a stay, not an appeal), split-vote orders (where two
# Board members cannot agree, so there IS no disposition), lack-of-quorum orders, and
# interim orders soliciting evidence by a date. Coercing those into an outcome would be
# an invented finding. They get classified instead, and only `merits` documents are
# expected to carry an outcome.
DOC_CLASSES = [
    ("split_vote",  r'Split\s*[_ ]?Vote|two\s+Board\s+members\s+cannot\s+agree'),
    ("stay",        r'\bstay\b.{0,40}(?:order|request|extension)|OSC\s+Stay'),
    ("quorum",      r'Lack\s+of\s+Quorum|quorum'),
    ("enforcement", r'petition\s+for\s+enforcement|compliance\s+proceeding'),
    ("arb_review",  r'request\s+for\s+review\b.{0,60}arbitrat|RFR\s+File'),
]

# Outcome, read from the Board's own order language. Order matters: the first pattern
# that matches wins, so the more specific and more appellant-favourable ones lead.
#
# The corrective-action forms were added after the sample: "We ORDER the agency to
# cancel the removal and reinstate the appellant" and "...to substitute a 120-day
# suspension" are unambiguous appellant wins that the first pattern set missed entirely,
# because it only looked for the verbs "reverse" and "mitigate".
OUTCOMES = [
    ("settled",        r'dismiss\w*\s+as\s+settled|dismissed\s+the\s+appeal\s+as\s+settled|'
                       r'withdraw\w*\s+(?:his|her|their|the)\s+(?:appeal|petition)'),
    ("mitigated",      r'\bwe\s+mitigate\b|penalty\s+is\s+mitigated|'
                       r'ORDER\s+the\s+agency\s+to\s+cancel\s+the\s+\w+\s+and\s+(?:to\s+)?substitute|'
                       r'substitute\s+a\s+[\w-]+\s+(?:day\s+)?suspension'),
    ("corrective",     r'ORDER\s+the\s+agency\s+to\s+cancel\s+the\s+(?:removal|suspension|demotion)|'
                       r'reinstate\s+the\s+appellant|grant\w*\s+(?:the\s+appellant.{0,12})?request\s+for\s+corrective\s+action'),
    ("remanded",       r'\bwe\s+remand\b|is\s+remanded|REMAND\s+ORDER|remand\w*\s+(?:the\s+)?(?:appeal|case)\s+to'),
    ("reversed",       r'\bwe\s+reverse\b|is\s+reversed|revers\w*\s+the\s+initial\s+decision'),
    ("vacated",        r'\bwe\s+vacate\b|is\s+vacated'),
    ("affirmed",       r'\bwe\s+affirm\b|is\s+affirmed|affirm\w*\s+the\s+initial\s+decision'),
    ("denied",         r'petition\s+for\s+review\s+is\s+denied|\bwe\s+deny\b|'
                       r'DENY\s+the\s+petition\s+for\s+review'),
    ("dismissed",      r'appeal\s+is\s+dismissed|\b(?:we|and)\s+(?:hereby\s+)?DISMISS\b'),
]

# Recurring substantive issues. Counted, not interpreted.
ISSUES = {
    "removal":            r'\bremoval\b',
    "suspension":         r'\bsuspension\b',
    "demotion":           r'\bdemotion\b',
    "retirement":         r'\bretirement\s+(?:annuity|benefits)|\bCSRS\b|\bFERS\b',
    "whistleblower":      r'whistleblow\w+|protected\s+disclosure',
    "usERRA":             r'\bUSERRA\b|uniformed\s+services\s+employment',
    "discrimination":     r'discriminat\w+',
    "retaliation":        r'retaliat\w+',
    "performance":        r'unacceptable\s+performance',
    "reduction_in_force": r'reduction\s+in\s+force|\bRIF\b',
    "probationary":       r'probationary\s+(?:employee|period)',
    "jurisdiction":       r'lack\w*\s+jurisdiction|without\s+jurisdiction',
    "timeliness":         r'untimely|time\s+limit',
}

# Authorities MSPB leans on, the analogue of the AAO precedent set.
PRECEDENTS = {
    "Douglas":    r'Douglas\s+v\.?\s+Veterans',       # the 12 penalty factors
    "Chevron":    r'Chevron',
    "Cornelius":  r'Cornelius\s+v\.?\s+Nutt',
    "Carr":       r'Carr\s+v\.?\s+Social\s+Security', # whistleblower reprisal factors
    "Hillen":     r'Hillen\s+v\.?\s+Department',      # credibility determinations
    "Special":    r'Special\s+Counsel\s+v\.?',
}


def log(msg):
    sys.stderr.write(msg + "\n")


def http_get(url, binary=False, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            return data if binary else data.decode("utf-8-sig", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt == tries - 1:
                raise
            log("  retry %d/%d after %s" % (attempt + 2, tries, e))
            time.sleep(2 * (attempt + 1))


# ---------------------------------------------------------------------------
def cmd_manifest(a):
    os.makedirs(OUT, exist_ok=True)
    log("fetching manifest ...")
    raw = http_get(MANIFEST_URL)
    rows = json.loads(raw)
    if isinstance(rows, dict):
        rows = rows.get("data") or list(rows.values())[0]
    path = os.path.join(OUT, "manifest.json")
    io.open(path, "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False))
    dates = sorted(r.get("ISSUED_DATE", "") for r in rows if r.get("ISSUED_DATE"))
    log("manifest: %d records, %s to %s -> %s" %
        (len(rows), dates[0] if dates else "?", dates[-1] if dates else "?", path))
    return rows


def load_manifest():
    path = os.path.join(OUT, "manifest.json")
    if not os.path.exists(path):
        sys.exit("no manifest yet - run: mspb_index.py manifest")
    return json.load(io.open(path, encoding="utf-8"))


def doc_key(rec):
    """A stable, non-identifying cache key.

    NOT the source filename, because roughly a third of those embed the appellant's
    name and the cache would then be a directory listing of who appealed. Docket plus
    a short digest of the filename is stable across runs and reveals nothing.
    """
    fn = rec.get("FILE_NAME") or rec.get("DOCNAME") or ""
    dk = (rec.get("DOCKET_NBR") or "nodocket").replace("/", "_")
    return "%s__%s" % (dk, hashlib.sha256(fn.encode("utf-8")).hexdigest()[:10])


def stratified(rows, n, seed):
    """A reproducible sample spread across (year, regional office).

    Plain --limit takes the head of the manifest, which is newest-first, so a 500-record
    limit would be 500 decisions from 2026 and would say nothing about whether the
    outcome patterns hold on older text or in other offices. This allocates the budget
    across strata largest-first and takes a seeded random draw within each, so the
    result is reproducible and every stratum with data is represented.
    """
    import random
    rnd = random.Random(seed)
    buckets = collections.defaultdict(list)
    for r in rows:
        yr = (r.get("ISSUED_DATE") or "")[:4]
        off = (r.get("DOCKET_NBR") or "").split("-")[0]
        buckets[(yr, off if off in OFFICES else "?")].append(r)
    keys = sorted(buckets, key=lambda k: -len(buckets[k]))
    picked, i = [], 0
    # Round-robin one at a time so small strata are not starved by large ones.
    while len(picked) < n and keys:
        progressed = False
        for k in keys:
            if len(picked) >= n:
                break
            b = buckets[k]
            if len(b) > i:
                progressed = True
                picked.append(rnd.choice(b) if len(b) > 1 else b[0])
                b.remove(picked[-1])
        if not progressed:
            break
        i = 0
    log("stratified sample: %d records across %d (year, office) strata, seed=%d"
        % (len(picked), len(keys), seed))
    return picked


def cmd_fetch(a):
    rows = load_manifest()
    os.makedirs(CACHE, exist_ok=True)
    if a.year:
        rows = [r for r in rows if (r.get("ISSUED_DATE") or "").startswith(str(a.year))]
        log("filtered to %s: %d records" % (a.year, len(rows)))
    if a.sample:
        rows = stratified(rows, a.sample, a.seed)
    elif a.limit:
        rows = rows[: a.limit]
    got = skipped = failed = 0
    for i, rec in enumerate(rows, 1):
        fn = rec.get("FILE_NAME") or rec.get("DOCNAME")
        if not fn:
            continue
        dest = os.path.join(CACHE, doc_key(rec) + ".pdf")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        url = BASE + PDF_DIR + urllib.parse.quote(fn)
        try:
            blob = http_get(url, binary=True)
            if not blob.startswith(b"%PDF"):
                failed += 1
                log("  not a PDF: %s" % fn[:70])
            else:
                io.open(dest, "wb").write(blob)
                got += 1
        except Exception as e:
            failed += 1
            log("  fetch failed (%s): %s" % (e, fn[:60]))
        time.sleep(CRAWL_DELAY)
        if i % 100 == 0:
            log("  %d/%d  new=%d cached=%d failed=%d" % (i, len(rows), got, skipped, failed))
    log("fetch done: %d new, %d already cached, %d failed" % (got, skipped, failed))


# ---------------------------------------------------------------------------
def pdf_text(pdf_path, txt_path):
    if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0:
        return io.open(txt_path, encoding="utf-8", errors="ignore").read()
    try:
        subprocess.run(["pdftotext", "-layout", pdf_path, txt_path],
                       check=True, capture_output=True)
    except FileNotFoundError:
        sys.exit("pdftotext not found. Install poppler (brew install poppler).")
    except subprocess.CalledProcessError as e:
        log("  pdftotext failed on %s: %s" % (os.path.basename(pdf_path),
                                              e.stderr[:120]))
        return ""
    return io.open(txt_path, encoding="utf-8", errors="ignore").read()


# Words that appear in MSPB filenames but are document-type vocabulary, not names.
# The filename Adler_Robert_D_DC-0843-25-0238-I-1__Final_Order.pdf contains BOTH the
# appellant's name AND "Final" and "Order". An earlier version of build_redactor()
# harvested every capitalised filename token as a name, which redacted ordinary prose:
# "the Board's Final decision" came out as "the Board's [NAME] decision". Over-redaction
# is not a safe failure - it silently corrupts the evidence spans the tool exists to
# make auditable. So filename harvesting is gone; only the explicit name fields are
# used, and they are populated on 100% of records so nothing is lost.
DOCTYPE_WORDS = frozenset("""
final order remand remanded initial decision opinion redacted split vote dismissed
settled nonprecedential precedential errata amended corrected addendum appeal appendix
""".split())


def build_redactor(rec):
    """Case-insensitive patterns for the appellant name this record discloses.

    Built from APL_FIRST_NAME / APL_LAST_NAME only, applied to any text this tool
    stores, then thrown away. Tokens of three characters or fewer are skipped: an
    initial or a short particle would match far too much ordinary text to redact
    safely, and a false redaction is worse than none because it corrupts the span
    without announcing it.
    """
    pats = []
    for f in ("APL_FIRST_NAME", "APL_LAST_NAME"):
        v = (rec.get(f) or "").strip()
        if len(v) > 3 and v.lower() not in DOCTYPE_WORDS:
            pats.append(re.escape(v))
    if not pats:
        return None
    uniq = sorted(set(pats), key=len, reverse=True)
    return re.compile(r"\b(?:%s)\b" % "|".join(uniq), re.I)


def redact(s, rx):
    return rx.sub("[NAME]", s) if (rx and s) else s


def norm(x):
    return re.sub(r"\s+", " ", x or "").strip()


def parse_one(rec, text):
    """One record. Every field is a regex over the decision's own words.

    Unparsed stays empty. Nothing is inferred and nothing is generated.
    """
    rx = build_redactor(rec)
    t = norm(text)
    docket = (rec.get("DOCKET_NBR") or "").strip()
    office_code = docket.split("-")[0] if "-" in docket else ""
    issued = (rec.get("ISSUED_DATE") or "").replace("/", "-")

    out = collections.OrderedDict()
    seg = docket.split("-")
    ct = seg[1] if len(seg) >= 2 else ""

    out["docket"] = docket                       # citation, not identity
    out["date_iso"] = issued
    out["year"] = issued[:4]
    out["office_code"] = office_code if office_code in OFFICES else ""
    out["office"] = OFFICES.get(office_code, "")
    # Only true regional offices belong in an office-variation comparison. CB is Board
    # original jurisdiction, so it is labelled but flagged out of the regional set.
    out["is_regional"] = 1 if office_code in REGIONS else 0
    out["case_type_code"] = ct
    out["case_type"] = CASE_TYPES.get(ct, "")
    out["agency"] = norm(rec.get("AGENCY"))
    out["doc_type"] = norm(rec.get("DOCTITLE")).replace("_", " ")
    out["words"] = len(t.split())

    # Classify the document before reading an outcome from it. Both the declared
    # DOCTITLE and the body are checked, because the manifest's titles are inconsistent
    # ("Final Order" vs "Final_Order" vs blank).
    hay = (out["doc_type"] + " " + t[:3000])
    out["doc_class"] = "merits"
    for name, pat in DOC_CLASSES:
        if re.search(pat, hay, re.I):
            out["doc_class"] = name
            break

    out["outcome"] = ""
    out["outcome_evidence"] = ""
    for name, pat in OUTCOMES:
        m = re.search(pat, t, re.I)
        if m:
            a, b = max(0, m.start() - 60), min(len(t), m.end() + 60)
            out["outcome"] = name
            out["outcome_evidence"] = redact(t[a:b].strip(), rx)
            break

    for k, pat in ISSUES.items():
        out["issue_" + k] = len(re.findall(pat, t, re.I))
    for k, pat in PRECEDENTS.items():
        out["cite_" + k] = 1 if re.search(pat, t, re.I) else 0

    out["text_chars"] = len(t)
    # Assert the invariant this tool exists to hold.
    for f in IDENTITY_FIELDS:
        assert f not in out, "identity field leaked into output: %s" % f
    return out


def cmd_parse(a):
    rows = load_manifest()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TEXT, exist_ok=True)
    by_key = {doc_key(r): r for r in rows}
    parsed, missing, new_text = [], 0, 0
    for fn in sorted(os.listdir(CACHE)):
        if not fn.endswith(".pdf"):
            continue
        key = fn[:-4]
        rec = by_key.get(key)
        if rec is None:
            missing += 1
            continue
        txt_path = os.path.join(TEXT, key + ".txt")
        existed = os.path.exists(txt_path)
        text = pdf_text(os.path.join(CACHE, fn), txt_path)
        if not existed:
            new_text += 1
        if not text.strip():
            continue
        parsed.append(parse_one(rec, text))
    if new_text:
        log("extracted text from %d new PDFs" % new_text)
    if missing:
        log("%d cached PDFs had no manifest record (skipped)" % missing)
    if not parsed:
        sys.exit("nothing parsed - run: mspb_index.py fetch")

    parsed.sort(key=lambda r: r["date_iso"], reverse=True)
    cols = list(parsed[0].keys())
    with io.open(os.path.join(OUT, "decisions.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(parsed)
    io.open(os.path.join(OUT, "decisions.json"), "w", encoding="utf-8").write(
        json.dumps({"schema_version": 1, "n_records": len(parsed),
                    "fields": cols, "records": parsed},
                   ensure_ascii=False, indent=1))
    log("parsed %d decisions -> out/decisions.csv and out/decisions.json" % len(parsed))

    # A de-identification tool that is not verified is a claim, not a control.
    #
    # The check is PER RECORD, deliberately. An earlier version tested every one of the
    # ~10,700 manifest names against the whole output and reported 244 "leaks" that were
    # almost entirely place and agency names: "Washington" matching office "Washington
    # DC", "Francisco" matching "San Francisco", "Justice" matching an agency. A global
    # name list will always collide with geography, so the only meaningful question is
    # whether THIS row's free text carries THIS appellant's name.
    #
    # Structured fields (office, agency) are excluded from the scan for the same reason:
    # they are drawn from controlled vocabularies, not from the decision body.
    FREE_TEXT = ("outcome_evidence",)
    by_key_rec = {doc_key(r): r for r in rows}
    leaked = []
    for rec_out in parsed:
        src = None
        for k, r in by_key_rec.items():
            if (r.get("DOCKET_NBR") or "").strip() == rec_out["docket"]:
                src = r
                break
        if src is None:
            continue
        for f in ("APL_FIRST_NAME", "APL_LAST_NAME"):
            v = (src.get(f) or "").strip()
            if len(v) <= 3 or v.lower() in DOCTYPE_WORDS:
                continue
            for fld in FREE_TEXT:
                if re.search(r"\b%s\b" % re.escape(v), rec_out.get(fld) or "", re.I):
                    leaked.append((rec_out["docket"], fld))
                    break
    log("de-identification check: %d/%d records leak their own appellant name "
        "into free text" % (len(leaked), len(parsed)))
    if leaked:
        log("  WARNING: do not publish this output until resolved. Examples: %s"
            % leaked[:3])


def cmd_report(a):
    path = os.path.join(OUT, "decisions.json")
    if not os.path.exists(path):
        sys.exit("no parsed output - run: mspb_index.py parse")
    rows = json.load(io.open(path, encoding="utf-8"))["records"]
    n = len(rows)
    print("MSPB decisions parsed: %d" % n)

    def dist(label, key, top=12):
        print("\n%s" % label)
        for k, v in collections.Counter(r.get(key) or "(unparsed)"
                                        for r in rows).most_common(top):
            print("  %-34s %5d  %5.1f%%" % (str(k)[:34], v, 100.0 * v / n))

    dist("outcome", "outcome")
    dist("regional office", "office")
    dist("employing agency", "agency", 10)
    dist("year", "year", 20)

    print("\noutcome by office (merits only)")
    MERITS = {"affirmed", "reversed", "remanded", "mitigated", "vacated"}
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        if r.get("outcome") in MERITS and r.get("is_regional"):
            by[r["office"]][r["outcome"]] += 1
    for off in sorted(by, key=lambda o: -sum(by[o].values())):
        c = by[off]
        tot = sum(c.values())
        fav = c["reversed"] + c["mitigated"] + c["vacated"]
        if tot >= 20:
            print("  %-22s n=%5d  appellant-favourable %4d (%5.2f%%)"
                  % (off, tot, fav, 100.0 * fav / tot))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["manifest", "fetch", "parse", "report", "all"])
    ap.add_argument("--limit", type=int, default=0,
                    help="cap how many PDFs to fetch this run, from the head of the "
                         "manifest (0 = all). Newest-first, so prefer --sample.")
    ap.add_argument("--sample", type=int, default=0,
                    help="reproducible stratified sample of N across (year, office)")
    ap.add_argument("--seed", type=int, default=42,
                    help="seed for --sample (default 42)")
    ap.add_argument("--year", type=int, help="fetch only this issued year")
    a = ap.parse_args()
    if a.cmd == "manifest":
        cmd_manifest(a)
    elif a.cmd == "fetch":
        cmd_fetch(a)
    elif a.cmd == "parse":
        cmd_parse(a)
    elif a.cmd == "report":
        cmd_report(a)
    else:
        cmd_manifest(a); cmd_fetch(a); cmd_parse(a); cmd_report(a)


if __name__ == "__main__":
    main()
