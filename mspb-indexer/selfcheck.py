#!/usr/bin/env python3
"""
selfcheck.py — mechanical audit of the indexer's whole surface.

Why this exists
---------------
Repeatedly this tool was declared finished and then a fresh question found a new
defect: `vacated` counted as relief, five of nine outcome labels contaminated,
seven dead branches in the outcome function, two text fields excluded from the
de-identification check, a report() block still computing a favourable rate the
old broken way. Every one of those was found by ad-hoc inspection, which is why
they kept arriving one at a time.

The surface is actually finite: the fields parse_one emits, the consumers of
those fields, the branches that can fire, and the docs that describe them. This
script enumerates that closed set and checks it, so "done" becomes a verifiable
claim rather than an impression.

Exit code 0 = all checks pass. Non-zero = the count of failures.

    python3 selfcheck.py
"""

import collections
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "mspb_index.py")
DERIVE = os.path.join(HERE, "derive_dispositions.py")
DISPO = os.path.join(HERE, "dispositions.json")
RECORDS = os.path.join(HERE, "out", "decisions.json")
CSV = os.path.join(HERE, "out", "decisions.csv")
README = os.path.join(HERE, "README.md")

fails, warns = [], []


def check(name, ok, detail=""):
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -- " + detail) if detail and not ok else ""))
    if not ok:
        fails.append(name)


def warn(name, ok, detail=""):
    if not ok:
        print("  WARN %s%s" % (name, ("  -- " + detail) if detail else ""))
        warns.append(name)


src = io.open(SRC, encoding="utf-8").read()
der = io.open(DERIVE, encoding="utf-8").read()
recs = json.load(io.open(RECORDS, encoding="utf-8"))["records"]
dispo = json.load(io.open(DISPO, encoding="utf-8"))
scores = {v["verb"]: v for v in dispo["verbs"]}
readme = io.open(README, encoding="utf-8").read() if os.path.exists(README) else ""

print("\n[1] no dangling references to deleted machinery")
for dead in ("OUTCOMES[", "for name, pat in OUTCOMES", "ORDERED_RELIEF.search"):
    check("no live reference to %r" % dead, dead not in src)

print("\n[2] every emitted field is populated somewhere")
keys = collections.Counter()
for r in recs:
    for k, v in r.items():
        if v not in ("", None, 0):
            keys[k] += 1
allk = set(recs[0].keys())
for k in sorted(allk):
    warn("field %r is empty on every record" % k, keys[k] > 0)
check("no field is empty across the whole corpus",
      all(keys[k] > 0 for k in allk),
      "empty: %s" % sorted(k for k in allk if keys[k] == 0))

print("\n[3] PRIVACY: every document-derived text field is de-identified")
m = re.search(r"FREE_TEXT = \(([^)]*)\)", src)
declared = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
# A field carries document text if any value contains a space and is long.
textish = {k for k in allk
           if sum(1 for r in recs
                  if isinstance(r.get(k), str) and len(r[k]) > 25
                  and " " in r[k]) > 20}
# Fields built from lookup tables or the manifest, NOT lifted from the decision
# body, so the de-identification check does not apply to them.
textish -= {"case_type", "doc_type", "agency", "office", "order_type"}
missing = textish - declared
check("all body-text fields are in FREE_TEXT", not missing,
      "NOT checked: %s (declared: %s)" % (sorted(missing), sorted(declared)))

print("\n[4] no dead branches in the outcome function")
# Every verb the outcome function tests must exist in the derived vocabulary.
body = src[src.find("def _outcome_from"):src.find("def _conflicts")]
tested = set(re.findall(r'v == "([a-z]+)"', body))
tested |= set(re.findall(r'v in \(([^)]*)\)', body) and
              re.findall(r'"([a-z]+)"', " ".join(re.findall(r'v in \(([^)]*)\)', body))) or [])
dead = sorted(t for t in tested if t not in scores)
check("every verb tested by _outcome_from exists in the vocabulary", not dead,
      "dead branches: %s" % dead)
# And every label it can return must actually occur.
labels = set(re.findall(r'return "([a-z_]+)"', body))
seen = {r["outcome"] for r in recs}
unreachable = sorted(l for l in labels if l and l not in seen)
warn("labels never produced on this corpus: %s" % unreachable, not unreachable)

print("\n[5] derived vocabulary is loaded and non-trivial")
check("dispositions.json has verbs", len(scores) > 20, "%d" % len(scores))
check("dispositions.json has frames", len(dispo.get("frames", [])) > 50)
check("missing vocabulary is fatal, not a silent degrade",
      "sys.exit(" in src[src.find("DISPO_PATH"):src.find("DISPO_PATH") + 1200])
check("grammar is imported from derive_dispositions, not duplicated",
      "from derive_dispositions import" in src)
for sym in ("ORDER_TITLE", "BOILERPLATE_OBJ", "frames_in", "norm_obj"):
    check("derive_dispositions still exports %s" % sym,
          re.search(r"^(def |%s\s*=|%s = )" % (sym, sym), der, re.M) is not None
          or ("def %s" % sym) in der or ("%s = re.compile" % sym) in der)

print("\n[6] relief fields only hold dispositive clauses")
bad = [r["relief_verb"] for r in recs
       if r.get("relief_verb") and r["relief_verb"] in scores
       and scores[r["relief_verb"]]["caps_ratio"] <= 0.0
       and scores[r["relief_verb"]]["remand_lift"] < 2.0]
check("no non-dispositive verb in relief_verb", not bad,
      "%d records, e.g. %s" % (len(bad), collections.Counter(bad).most_common(3)))

print("\n[7] outcome agrees with the document's own title")
conf = sum(r.get("outcome_conflict", 0) for r in recs)
check("title conflicts under 1%%", conf / len(recs) < 0.01,
      "%d/%d = %.2f%%" % (conf, len(recs), 100.0 * conf / len(recs)))

print("\n[8] merits coverage")
merits = [r for r in recs if r["doc_class"] == "merits"]
blank = sum(1 for r in merits if not r["outcome"])
check("merits documents with no outcome under 5%%", blank / len(merits) < 0.05,
      "%d/%d = %.1f%%" % (blank, len(merits), 100.0 * blank / len(merits)))

print("\n[9] CSV and JSON agree")
if os.path.exists(CSV):
    import csv as _csv
    with io.open(CSV, encoding="utf-8") as fh:
        cols = next(_csv.reader(fh))
    check("CSV columns match JSON keys", set(cols) == allk,
          "json-only: %s  csv-only: %s"
          % (sorted(allk - set(cols)), sorted(set(cols) - allk)))
    check("no identity field reached the CSV",
          not ({"APL_FIRST_NAME", "APL_LAST_NAME", "FILE_NAME", "DOCNAME",
                "META_TITLE", "META_KEYWORDS", "META_AUTHOR"} & set(cols)))

print("\n[10] documentation matches the code")
# The README must not advertise labels the code can no longer emit. But it SHOULD
# still discuss them: the audit narrative explains that `settled` was 21.8%
# contaminated and was therefore dropped, and deleting that history to satisfy a
# naive substring check would remove the reason the label is gone.
#
# So a mention only counts as "advertising" when it is NOT accompanied by language
# marking it as withdrawn. The earlier version of this check flagged the audit
# paragraph itself, which is a false positive that trains you to ignore the warning.
WITHDRAWN_CUES = ("contaminat", "removed", "deleted", "dropped", "no longer",
                  "withdraw", "%")


def advertises(label):
    if label not in readme or label in seen:
        return False
    for m in re.finditer(re.escape(label), readme):
        sent = readme[max(0, m.start() - 400):m.end() + 200].lower()
        if not any(cue in sent for cue in WITHDRAWN_CUES):
            return True          # a bare mention with no "this was dropped" nearby
    return False


for stale in ("mitigated", "settled"):
    warn("README still advertises the %r outcome label as emittable" % stale,
         not advertises(stale))
check("README documents the derived pipeline",
      "derive_dispositions" in readme,
      "README does not mention derive_dispositions.py")
check("report() no longer prints a single favourable rate",
      'appellant-favourable %4d' not in src)
check("report() restricts to appellant-petitioned",
      'petitioner") == "appellant"' in src)

print("\n[11] no model calls, no network in the parse path")
for banned in ("openai", "anthropic", "requests.post", "bedrock"):
    check("no %r anywhere" % banned, banned not in src and banned not in der)

# Every cached PDF should have produced a text file. Two did not, and the pipeline
# skipped them without saying so, which is the kind of silent shortfall that makes a
# corpus quietly smaller than it reports.
#
# These two are STRUCTURALLY CORRUPT, not image-only scans: pdftotext reports
# "xref num 2 not found but needed" and "Catalog dictionary does not contain a valid
# /Pages entry" rather than an empty text layer.
#
# Re-fetching does NOT fix them, which was tested rather than assumed: both were
# re-downloaded from mspb.gov and came back byte-identical (53,032 and 140,628 bytes),
# so the files are corrupt on the government's own server. They are unrecoverable
# without a repair pass (qpdf/ghostscript, neither installed here), and even then the
# text layer may simply not be present.
#
# Reported as a warning, not a failure: 2 of 10,666 is 0.019% and cannot move any
# finding. The point is that it is visible instead of invisible, and that nobody
# wastes time re-fetching.
print("\n[12] every cached PDF produced text")
_pdfs = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(HERE, "cache", "*.pdf"))}
_txts = {os.path.basename(p)[:-4]
         for p in glob.glob(os.path.join(HERE, "cache", "text", "*.txt"))}
_gap = sorted(_pdfs - _txts)
warn("%d cached PDF(s) yielded no text - corrupt at SOURCE, re-fetch does not help: %s"
     % (len(_gap), ", ".join(_gap[:3]) + (" ..." if len(_gap) > 3 else "")),
     not _gap)
if not _gap:
    print("  PASS all %d cached PDFs have extracted text" % len(_pdfs))

print()
if fails:
    print("%d CHECK(S) FAILED: %s" % (len(fails), ", ".join(fails)))
else:
    print("all checks passed (%d warnings)" % len(warns))
sys.exit(len(fails))
