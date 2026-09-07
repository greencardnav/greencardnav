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

# The hand-typed OUTCOMES table that used to live here has been DELETED.
#
# It was nine labels, each a regex guessing at what the Board's order language
# would look like. Audited against the stored evidence spans, five were badly
# contaminated: `reversed` 44.1% (24.6% of hits were NEGATED clauses such as
# "provides no basis for reversing the initial decision", 7.8% were
# agency-favourable reversals counted as appellant wins), `vacated` 32.6%
# (partial vacatur of a single finding read as full relief), `corrective` 28.9%
# (19.7% attributed to an arbitrator, administrative judge or OPM rather than the
# Board), `settled` 21.8% (withdrawal *requests*, some of them denied). It
# labelled 281 records `reversed` when only 191 documents contain a first-person
# "we reverse" at all.
#
# It is replaced by a vocabulary DERIVED from the corpus. The grammar is defined
# once in derive_dispositions.py and imported here so the two cannot drift; the
# scores it measures are read from dispositions.json at load time. Re-running
# `python3 derive_dispositions.py` after adding documents updates the vocabulary
# with no pattern authoring.
from derive_dispositions import (                                  # noqa: E402
    ORDER_TITLE as ORDER_TITLE_RX,
    BOILERPLATE_OBJ as BOILERPLATE_OBJ_RX,
    frames_in as _frames_raw,
    norm_obj as _norm_obj,
    PFR as PFR_RX,
)

DISPO_PATH = os.path.join(HERE, "dispositions.json")

# Per-verb measured signals: caps_ratio, edge_share, remand_lift, negated_ratio.
# Absent file is fatal rather than silently degrading -- an empty score table
# would make every document look dispositionless.
try:
    with open(DISPO_PATH, encoding="utf-8") as _fh:
        _DISPO = json.load(_fh)
    DISPO_SCORE = {v["verb"]: v for v in _DISPO["verbs"]}
except (IOError, ValueError, KeyError) as _e:
    # Fatal, not a silent degrade. An empty score table makes every document look
    # dispositionless, which would read as "the corpus has no outcomes" rather
    # than "the vocabulary is missing".
    sys.exit("cannot load %s (%s).\nRun: python3 derive_dispositions.py"
             % (DISPO_PATH, _e))

# NOTE: a draft of this block hand-wrote an ORDERED_RELIEF verb regex to decide
# which `order` objects counted as relief. Deleted -- it was the same hardcoding
# the rest of this rewrite removed, and it is not needed: `order` carries the
# highest caps_ratio in the corpus (94.1%, the Board's own marking of an operative
# clause), and its object distribution is dominated by genuine relief
# (`agency to cancel the` 324, `agency to pay the` 48, `opm to grant the` 20,
# `agency to restore the` 19). The compliance-notice objects that look procedural
# (`agency to submit to` 31, `agency to tell the` 12) appear ONLY in decisions
# that granted relief, because that paragraph is the standard follow-on to an
# order -- so they are not false positives either. The verb alone is the signal.

# PFR detection is imported from the grammar module (see PFR_RX in the import
# block above) so mspb_index.py and derive_dispositions.py cannot disagree about
# what an operative grant/deny clause looks like -- derive_dispositions.py needs
# it too, to measure the per-object deny_rate that now supplies clause scope.

# DERIVED clause level, replacing two hand-written scope regexes.
#
# SCOPE_PARTIAL / SCOPE_FULL were the last hardcoded surface in this pipeline and
# they left relief_scope `unknown` on 43.7% of clauses. Worse, they were wrong on
# the single most common object: `initial decision` (1,382 clauses) was labelled
# `full` while co-occurring with a DENIED petition 97.0% of the time.
#
# Replaced by a measured signal. For each object head the miner records how often
# the same document denies the petition -- a clause that merely tidies reasoning
# co-occurs with denial, an operative disposition does not. pfr_of() reads a
# different sentence than the frame, so this is not circular. The distribution is
# sharply bimodal (99%+ vs 0%), which is why a 0.5 cut is safe rather than tuned.
OBJ_DENY = {o["object"]: o["deny_rate"] for o in _DISPO.get("objects", [])}
DENY_CUT = 0.5


def _scope_of(verb, obj, regex_fallback):
    """reasoning | operative, from the measured per-object deny rate.

    LIMIT OF THE DENY-RATE PROXY, found by it breaking something: `order` clauses
    must bypass it. "we ORDER the agency to cancel the removal" carries a 65.6%
    denial rate, because the Board often denies the petition precisely when the
    judge below already granted the right remedy -- so deny_rate conflates
    "reasoning-level clause" with "relief the appellant already won below". Taking
    it at face value reclassified 491 genuine corrective-action records as
    reasoning and dropped `corrective` from 637 to 146.
    `order` has no reasoning-level reading -- the Board directing an agency to act
    is operative by construction -- so it is exempt. The proxy governs only the
    verbs whose relief status is genuinely ambiguous (affirm/vacate/reverse/modify),
    which is what it was measured on.
    """
    if verb == "order":
        return "operative"
    d = OBJ_DENY.get(obj)
    if d is None:
        return regex_fallback
    return "reasoning" if d >= DENY_CUT else "operative"


def _frames(text):
    """frames_in() plus the match object, so evidence spans stay auditable."""
    for fr in _frames_raw(text):
        m = type("M", (), {"start": lambda self, s=fr["span"][0]: s,
                           "end": lambda self, e=fr["span"][1]: e})()
        yield fr, m


def _sentence_at(t, a, b, cap=320):
    """Clamp an evidence span to its own sentence.

    The previous fixed 60-character window ran past the end of the clause and
    pulled in whatever followed -- in one record a case citation whose party name
    matched this appellant's own surname, which tripped the de-identification
    check. A sentence boundary is both better evidence (the clause entire, no
    fragment) and a smaller surface for that failure.
    """
    lo = max(0, a - cap)
    left = t.rfind(". ", lo, a)
    start = left + 2 if left != -1 else lo
    right = t.find(". ", b, min(len(t), b + cap))
    end = right + 1 if right != -1 else min(len(t), b + cap)
    return re.sub(r"\s+", " ", t[start:end]).strip()


def _outcome_from(o):
    """Derive the SUBSTANTIVE disposition from the measured signals.

    `outcome` and `pfr_disposition` answer different questions and are kept
    apart. The standard MSPB order reads "we DENY the petition for review and
    AFFIRM the initial decision": the denial is procedural, the affirmance is the
    substantive result. An earlier version of this function collapsed both into
    `denied`, which turned 5,106 affirmances into a label carrying no information
    -- the same mistake as the deleted table, one layer up.

    Relief is credited only when the clause is affirmative AND full-scope. A
    negated clause ("we do not disturb the findings") or a partial one ("we
    vacate that finding") leaves the initial decision standing.
    """
    v, scope, neg = o["relief_verb"], o["relief_scope"], o["relief_negated"]

    if o["order_type"] == "Remand Order" or (v == "remand" and not neg):
        return "remanded"
    if v == "dismiss" and not neg:
        return "dismissed"
    if not neg and scope != "reasoning":
        if v == "reverse":
            return "reversed"
        if v == "vacate":
            return "vacated"
        if v == "modify":
            return "modified"
        # Corrective action. An earlier version listed the verbs by hand
        # ("mitigate", "substitute", "reinstate", "cancel", "restore") and all
        # SEVEN of those branches were DEAD, because none of those verbs clears
        # the derivation frequency floor -- the Board says "we ORDER the agency
        # to cancel/restore/pay", so the relief rides in the object while the
        # operative verb is always `order`.
        if v == "order":
            return "corrective"
    # Everything else leaves the initial decision in place. That is an
    # affirmance whether the Board says so explicitly, denies the petition, or
    # merely declines to disturb the findings.
    if v == "affirm" or o["pfr_disposition"] == "denied" or neg or scope == "reasoning":
        return "affirmed"
    return ""


def _conflicts(o):
    """1 when the derived outcome contradicts the document's own title."""
    ot, oc = o["order_type"], o["outcome"]
    if not ot or not oc:
        return 0
    if ot == "Remand Order" and oc != "remanded":
        return 1
    if ot == "Final Order" and oc == "remanded":
        return 1
    return 0

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

# ADVERSE REASONING PHRASES.
#
# Two sets, kept separate on purpose.
#
# SHARED: the first six are the SAME regexes aao_index.py uses. They are generic
# adjudicative-adverse vocabulary, not immigration-specific, so counting them here
# gives a genuine like-for-like measure across the two agencies. An earlier version
# of this file only tracked substantive ISSUE categories (jurisdiction, whistleblower,
# performance), which describe what a case is ABOUT rather than how the Board reasoned
# about it - those are not comparable to the AAO phrase set and comparing them would
# have been an apples-to-oranges claim.
#
# MSPB-ONLY: standard-of-review moves specific to Board review of an administrative
# judge's initial decision. There is no AAO analogue because AAO reviews a service
# center's denial, not a prior adjudicator's findings.
PHRASES_SHARED = {
    "conclusory":       r'conclusor\w+',
    "generalized":      r'generaliz\w+',
    "speculative":      r'speculat\w+',
    "unsupported":      r'unsupported',
    "material_change":  r'material change',
    "inconsistent":     r'inconsisten\w+',
}

PHRASES_MSPB = {
    # Petitioner merely re-argues what the AJ already weighed
    "mere_disagreement":    r'mere\w*\s+disagree\w+|simply\s+disagree\w+',
    # Burden language
    "failed_to_establish":  r'(?:has|have)\s+not\s+(?:shown|established|demonstrated)|'
                            r'fail\w*\s+to\s+(?:show|establish|demonstrate)',
    # New evidence on review is generally not considered
    "no_new_evidence":      r'not\s+previously\s+available|new\s+evidence[^.]{0,60}not\s+consider',
    # Board will not reweigh the record
    "reweigh":              r'reweigh\w*|substitute\s+our\s+(?:own\s+)?(?:judgment|assessment)',
    # Deference to the AJ on credibility (the Hillen factors)
    "credibility_deference": r'defer\w*\s+to[^.]{0,50}credibility|credibility\s+determination',
    # Error must be harmful to matter
    "harmful_error":        r'harmful\s+error|error\w*\s+did\s+not\s+(?:prejudice|affect)',
}

# WHO PETITIONED FOR REVIEW. This is load-bearing and was missing from the first
# version, which is a real defect: either party may petition, so a "reversal" only
# favours the appellant when the APPELLANT was the petitioner. Where the agency
# petitioned, a reversal favours the agency. Roughly 8% of decisions are agency,
# cross- or dual-petitions, so treating every reversal as an appellant win
# mislabels several hundred cases and biases any office comparison built on it.
PETITIONER = [
    ("cross", r'cross\s*petition\s+for\s+review'),
    ("agency", r'(?:the\s+)?agency\s+(?:has\s+)?(?:timely\s+)?file\w*\s+a\s+petition\s+for\s+review'),
    ("appellant", r'(?:the\s+)?appellant\s+(?:has\s+)?(?:timely\s+)?file\w*\s+a\s+petition\s+for\s+review'),
]

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

    # ------------------------------------------------------------------
    # Disposition. Three independent signals, none of them a hand-authored
    # outcome taxonomy. See derive_dispositions.py for how the vocabulary is
    # mined from the corpus and why the previous hand-typed OUTCOMES table was
    # abandoned (five of its nine labels were contaminated: reversed 44.1%,
    # vacated 32.6%, corrective 28.9%, settled 21.8%).
    #
    #   order_type       the document's own title. Independent of anything we
    #                    extract, present on 95.2% of the corpus.
    #   pfr_disposition  who won the petition for review, read from the Board's
    #                    own capitalised first-person clause.
    #   relief_*         the top-scoring operative clause, scored on signals
    #                    MEASURED per verb (caps_ratio, edge_share, remand_lift)
    #                    rather than on a list of verbs I expected to matter.
    # ------------------------------------------------------------------
    tm = ORDER_TITLE_RX.search(t[:6000])
    out["order_type"] = tm.group(1).title() if tm else ""

    out["pfr_disposition"] = ""
    out["pfr_evidence"] = ""
    best_pfr = None
    for m in PFR_RX.finditer(t):
        verb = m.group("v")
        obj = _norm_obj(m.group("o") or "")
        if BOILERPLATE_OBJ_RX.match(obj):      # 5 CFR 1201.115 standard, not a holding
            continue
        # The Board capitalises the operative one; prefer it, else take the first.
        rank = (1 if verb.isupper() else 0, -m.start())
        if best_pfr is None or rank > best_pfr[0]:
            best_pfr = (rank, verb.lower(), m)
    if best_pfr:
        _, v, m = best_pfr
        out["pfr_disposition"] = "granted" if v.startswith("grant") else "denied"
        out["pfr_evidence"] = redact(_sentence_at(t, m.start(), m.end()), rx)

    out["relief_verb"] = ""
    out["relief_object"] = ""
    out["relief_scope"] = ""
    out["relief_negated"] = 0
    out["outcome_evidence"] = ""
    best = None
    L = max(len(t), 1)
    for fr, m in _frames(t):
        # grant/deny answer the PETITION question and are already captured in
        # pfr_disposition. Letting them compete here suppressed real relief:
        # `deny` scores 90.5% caps against `reverse` at 29.2%, so every reversal
        # lost to the denial clause in the same document and `reversed` fell to 2
        # records out of 191 documents that contain "we reverse".
        if fr["verb"] in ("grant", "grants", "deny", "denies"):
            continue
        sc = DISPO_SCORE.get(fr["verb"])
        if sc is None:
            continue                            # below the derivation frequency floor
        rel = m.start() / L
        score = (sc["caps_ratio"]
                 + (0.5 if fr["caps"] else 0.0)
                 + (0.4 if (rel < 0.15 or rel > 0.75) else 0.0)
                 + 0.25 * min(sc["remand_lift"] / 4.0, 1.0))
        if best is None or score > best[0]:
            best = (score, fr, m)
    # A clause only counts as relief if its verb shows measured dispositiveness:
    # the Board capitalises it somewhere in the corpus, or it moves the order-type
    # title. Without this bar, discussion verbs won the slot -- `conclude`
    # (caps 0.0%, lift 0.17x) was landing in relief_verb with relief_object
    # "the petitioner has not", which is both wrong and needless text to store.
    if best:
        _sc = DISPO_SCORE[best[1]["verb"]]
        if _sc["caps_ratio"] <= 0.0 and _sc["remand_lift"] < 2.0:
            best = None
    if best:
        _, fr, m = best
        out["relief_verb"] = fr["verb"]
        # redact(): this is an object phrase lifted from the decision and can
        # carry a surname ("order agency to reinstate <name>"). Three records
        # leaked here the moment the field was added to the FREE_TEXT check.
        out["relief_object"] = redact(fr["obj"], rx)
        out["relief_scope"] = _scope_of(fr["verb"], fr["obj"], fr["scope"])
        out["relief_negated"] = 1 if fr["negated"] else 0
        out["outcome_evidence"] = redact(_sentence_at(t, m.start(), m.end()), rx)

    # `outcome` is retained so existing analysis keeps working, but it is now a
    # FUNCTION of the three measured signals rather than a first-match regex.
    # A negated or partial-scope clause can no longer be read as relief -- the
    # exact bug that produced the withdrawn office-variation finding.
    out["outcome"] = _outcome_from(out)

    # Automated self-check the old code had no way to perform: does the derived
    # outcome contradict the document's own title? Reported per row, aggregated
    # by `report`, so drift is visible instead of silent.
    out["outcome_conflict"] = _conflicts(out)

    # Who petitioned for review. Both patterns are checked before deciding, because
    # "cross" and "both" must not be silently collapsed into "appellant".
    apl = re.search(PETITIONER[2][1], t, re.I)
    agy = re.search(PETITIONER[1][1], t, re.I)
    if re.search(PETITIONER[0][1], t, re.I):
        out["petitioner"] = "cross"
    elif apl and agy:
        out["petitioner"] = "both"
    elif agy:
        out["petitioner"] = "agency"
    elif apl:
        out["petitioner"] = "appellant"
    else:
        out["petitioner"] = ""

    # Substantive issue categories: what the case is ABOUT.
    for k, pat in ISSUES.items():
        out["issue_" + k] = len(re.findall(pat, t, re.I))
    # Adverse reasoning phrases: HOW the Board reasoned. Counts, not booleans.
    # ph_* names and regexes are shared with aao_index.py so the two corpora are
    # directly comparable; phm_* are MSPB-specific standard-of-review moves.
    for k, pat in PHRASES_SHARED.items():
        out["ph_" + k] = len(re.findall(pat, t, re.I))
    for k, pat in PHRASES_MSPB.items():
        out["phm_" + k] = len(re.findall(pat, t, re.I))
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
    # Every field that carries document-derived text. `pfr_evidence` and
    # `relief_object` were ADDED after an audit found them excluded: the
    # "0 leaks" result before that only covered outcome_evidence, so the
    # de-identification guarantee this tool advertises was not actually being
    # checked on two of the four text fields.
    FREE_TEXT = ("outcome_evidence", "pfr_evidence", "relief_object")
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

    # Office comparison.
    #
    # The previous version of this block printed a single "appellant-favourable"
    # rate and every part of it was wrong. It counted `vacated` as a win (a
    # standalone vacatur is usually the Board tidying an administrative judge's
    # reasoning while DENYING the petition), counted a `mitigated` key that no
    # longer exists and was therefore always 0, omitted `corrective` -- the
    # largest relief category at 637 records -- and did not restrict to
    # appellant-petitioned cases even though agency-petitioned reversals favour
    # the AGENCY (49.9% vs 6.6% favourable). It reproduced both of the coding
    # errors that forced a finding to be withdrawn, and it printed by default.
    #
    # Replaced with the two rates kept SEPARATE, because that separation is the
    # actual result: relief rate is flat across offices while remand rate is not.
    print("\noutcome by office (regional, merits, APPELLANT-petitioned only)")
    print("  %-22s %6s  %-18s  %s"
          % ("office", "n", "relief granted", "remanded"))
    RELIEF = {"reversed", "vacated", "corrective", "modified"}
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        if (r.get("is_regional") and r.get("doc_class") == "merits"
                and r.get("petitioner") == "appellant" and r.get("outcome")):
            c = by[r["office"]]
            c["n"] += 1
            if r["outcome"] in RELIEF:
                c["relief"] += 1
            if r["outcome"] == "remanded":
                c["remand"] += 1
    for off in sorted(by, key=lambda o: -by[o]["n"]):
        c = by[off]
        if c["n"] < 100:
            continue
        print("  %-22s %6d  %5d (%5.2f%%)      %5d (%5.2f%%)"
              % (off, c["n"], c["relief"], 100.0 * c["relief"] / c["n"],
                 c["remand"], 100.0 * c["remand"] / c["n"]))
    print("  NOTE: relief and remand are reported separately and neither is an\n"
          "  approval rate. `vacated` is NOT counted as relief unless full-scope;\n"
          "  see derive_dispositions.py for why.")


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
