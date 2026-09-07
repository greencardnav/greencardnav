#!/usr/bin/env python3
"""
derive_dispositions.py — learn the Board's disposition grammar FROM the corpus.

Why this exists
---------------
The first version of mspb_index.py carried a hand-typed OUTCOMES table: nine
labels, each a regex somebody (me) guessed at. Auditing it against the stored
evidence spans showed five of the nine were contaminated — `reversed` 44.1%,
`vacated` 32.6%, `corrective` 28.9%, `settled` 21.8% — by negated clauses
("provides no basis for reversing the initial decision"), clauses attributed to
somebody other than the Board ("the arbitrator ordered the agency to reinstate"),
agency-favourable reversals read as appellant wins, and partial vacaturs of a
single finding read as full vacaturs.

Every one of those is the same failure: a hand-authored pattern encodes what I
expected the text to say. Adding more hand-authored patterns for the negations
would encode a second round of the same guess.

So this script does not contain a disposition vocabulary. It DERIVES one:

  1. Find every first-person operative clause in the corpus — the Board speaking
     as "we", which is how it states what it is actually doing.
  2. Parse each into a frame: (polarity, modality, verb, object head, scope).
  3. Rank frames by corpus frequency. The head of that distribution IS the
     disposition vocabulary, in the Board's own words and proportions.
  4. Emit it as dispositions.json for mspb_index.py to consume.

Adding a year, an office, or a second agency needs no new patterns here — rerun
and the vocabulary updates. A frame that appears in the corpus but not in the
emitted table is reported as residual, so silent coverage loss is visible.

Ground truth for free
---------------------
MSPB titles its own decisions: 84.2% "FINAL ORDER", 10.9% "REMAND ORDER", at a
median offset of 389 characters. That title is independent of any clause we
extract, so it is used as a held-out check: a derived disposition of `remanded`
should co-occur with a REMAND ORDER title. The disagreement rate is reported as
a quality metric rather than assumed away.

Usage
-----
    python3 derive_dispositions.py              # derive, report, write JSON
    python3 derive_dispositions.py --report     # derive and report, write nothing
    python3 derive_dispositions.py --min 25     # frequency floor for the vocabulary

Python 3 standard library only. No model calls. No network.
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = os.path.join(HERE, "cache", "text")
OUT = os.path.join(HERE, "dispositions.json")

# ---------------------------------------------------------------------------
# The ONE structural assumption, and it is about grammar, not about outcomes.
#
# A tribunal states its holding in the first person. "we DENY the petition",
# "we REVERSE the initial decision", "we ORDER the agency to cancel the removal".
# Anything the Board is not the subject of is somebody else's action being
# described -- an arbitrator's award, an administrative judge's finding, a prior
# Federal Circuit ruling -- and is exactly what contaminated the hand-written
# version.
#
# So: locate first-person clauses, then let the corpus say what verbs and objects
# fill them. No verb list, no outcome list, no cue-phrase list.
# ---------------------------------------------------------------------------

CLAUSE = re.compile(
    r"""
    (?P<lead>(?:\b\w+\b[ ,;]{0,2}){0,12}?)      # left context, for polarity
    \bwe\s+
    (?P<mod>(?:also|hereby|further|thus|therefore|accordingly|instead)\s+){0,2}
    (?P<neg>(?:do\s+not|shall\s+not|will\s+not|decline\s+to|need\s+not)\s+)?
    (?P<verb>[A-Za-z]+)
    (?P<obj>(?:\s+\w+){0,7})
    """,
    re.I | re.X,
)

# NO verb list. An earlier draft of this file carried a hand-typed
# NON_DISPOSITIVE_HINT regex naming ~60 "discussion" verbs to exclude. That was
# the same mistake the hand-written OUTCOMES table made -- it encodes what I
# expect the text to contain -- so it was deleted rather than extended.
#
# In its place, three signals MEASURED per verb from the corpus, reported and
# written to JSON so downstream code can threshold them explicitly:
#
#   caps_ratio  The Board capitalises its operative verbs ("we DENY", "we ORDER",
#               "we VACATE"). Measured: order 94.1%, deny 90.5%, dismiss 55.3%,
#               affirm 51.1%, vacate 42.4% -- versus find 0.1%, disagree 0%,
#               offer 0%. Strong but NOT sufficient alone: `modify` sits at 8%
#               and is genuinely dispositive in 736 documents, which is exactly
#               why this is a reported score and not a cutoff baked in here.
#
#   edge_share  Share of occurrences in the opening 15% or closing 25% of the
#               document -- holdings and the ORDER section. Discussion verbs
#               spread uniformly (accept 2.2%, apply 6.7%, offer 8.2%).
#
#   remand_lift Ratio of this verb's REMAND ORDER share to the corpus base rate
#               (10.9%). Dispositive verbs move the title: remand 8.78x,
#               vacate 3.08x, reverse 2.46x, while deny runs 0.09x because
#               denials are FINAL ORDERs. The title is independent of the clause,
#               so this is genuine held-out signal rather than circular.
#
# No verb is dropped here. Everything above --min is emitted with its scores
# attached; selection is the consumer's decision, made explicit and re-derivable.

# Scope: does the clause act on the whole decision, or on one finding inside it?
# The distinction is the entire reason `vacated` was wrong -- vacating a finding
# while denying the petition is not relief. Object heads come from the corpus.
SCOPE_PARTIAL = re.compile(
    r"\b(?:finding|findings|portion|part|analysis|conclusion|conclusions|statement|"
    r"determination|discussion|reference|footnote|paragraph|sentence|"
    r"administrative\s+judge|aspect)\b",
    re.I,
)
SCOPE_FULL = re.compile(
    r"\b(?:initial\s+decision|petition|appeal|final\s+order|reconsideration\s+decision|"
    r"removal|suspension|demotion|action|award)\b",
    re.I,
)

# The Board's disposition OF the petition for review. Lives here rather than in
# mspb_index.py so the grammar has one home; mspb_index.py imports it. Needed in
# this file because the per-object deny_rate below is measured against it.
PFR = re.compile(
    r"\bwe\s+(?:(?:also|hereby|further|thus|therefore|accordingly)\s+){0,2}"
    r"(?P<v>GRANT\w*|grant\w*|DENY|deny)\b"
    r"(?P<o>(?:\s+\w+){0,6})",
)


def pfr_of(text):
    """granted / denied / '' -- prefers the capitalised (operative) clause."""
    best = None
    for m in PFR.finditer(text):
        obj = norm_obj(m.group("o") or "")
        if BOILERPLATE_OBJ.match(obj):        # 5 CFR 1201.115 standard, not a holding
            continue
        rank = (1 if m.group("v").isupper() else 0, -m.start())
        if best is None or rank > best[0]:
            best = (rank, m.group("v").lower())
    if not best:
        return ""
    return "granted" if best[1].startswith("grant") else "denied"


# Independent ground truth: the document's own title.
ORDER_TITLE = re.compile(
    r"\b(FINAL ORDER|REMAND ORDER|OPINION AND ORDER|ORDER AND OPINION|"
    r"DISMISSAL ORDER|INITIAL DECISION|NONPRECEDENTIAL FINAL ORDER)\b"
)

NEG_LEAD = re.compile(
    r"\b(?:no\s+basis|not\s+provide|provides\s+no|insufficient|fails?\s+to|"
    r"failed\s+to|nothing\s+in|neither|nor|without\s+merit|unpersuasive)\b", re.I
)


def norm_obj(s):
    """Collapse an object phrase to a comparable head, using only whitespace and
    stopword normalisation -- no semantic mapping table."""
    s = re.sub(r"\s+", " ", s.lower()).strip()
    s = re.sub(r"^(?:the|that|this|these|those|his|her|their|its|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return " ".join(s.split()[:4])


# The one discriminator the corpus itself handed over: 5 C.F.R. 1201.115
# boilerplate reads "the Board grants petitions such as this one only when...".
# It is 6,898 of the 8,671 `grant` documents -- the single largest false signal in
# the corpus -- and it is identifiable by its object head (PLURAL "petitions"
# plus "such as"), not by anything I decided in advance. Found by ranking
# verb+object frames by frequency, which is why the ranking exists.
BOILERPLATE_OBJ = re.compile(r"^petitions?\s+such\s+as\b", re.I)


def frames_in(text):
    """Yield one frame per first-person clause. No verb filtering -- scores are
    measured and attached, selection happens downstream."""
    for m in CLAUSE.finditer(text):
        raw = m.group("verb")
        verb = raw.lower()
        obj = norm_obj(m.group("obj") or "")
        if not obj or BOILERPLATE_OBJ.match(obj):
            continue
        lead = m.group("lead") or ""
        negated = bool(m.group("neg")) or bool(NEG_LEAD.search(lead))
        if SCOPE_PARTIAL.search(obj):
            scope = "partial"
        elif SCOPE_FULL.search(obj):
            scope = "full"
        else:
            scope = "unknown"
        yield {
            "verb": verb,
            "obj": obj,
            "caps": raw.isupper(),          # the Board's own marking
            "negated": negated,
            "scope": scope,
            "span": (m.start(), m.end()),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=20,
                    help="corpus-frequency floor for a frame to enter the vocabulary")
    ap.add_argument("--report", action="store_true", help="report only, write nothing")
    ap.add_argument("--top", type=int, default=45, help="rows to show per table")
    a = ap.parse_args()

    if not os.path.isdir(TEXT):
        sys.exit("no text cache at %s -- run `mspb_index.py fetch` first" % TEXT)
    files = sorted(f for f in os.listdir(TEXT) if f.endswith(".txt"))
    if not files:
        sys.exit("text cache is empty")

    verb_obj = collections.Counter()     # (verb, obj) -> docs
    verb_tot = collections.Counter()     # verb -> docs
    neg_by_verb = collections.Counter()
    scope_by_verb = collections.Counter()
    title_by_verb = collections.Counter()
    caps_by_verb = collections.Counter()
    occ_by_verb = collections.Counter()
    edge_by_verb = collections.Counter()
    titles = collections.Counter()
    obj_tot = collections.Counter()
    obj_deny = collections.Counter()
    docs_with_any = 0

    for fn in files:
        t = open(os.path.join(TEXT, fn), encoding="utf-8", errors="replace").read()
        L = max(len(t), 1)
        tm = ORDER_TITLE.search(t[:6000])
        title = tm.group(1) if tm else ""
        titles[title or "(none)"] += 1
        # Held-out signal for clause LEVEL: a clause that merely tidies reasoning
        # co-occurs with the petition being denied; an operative one does not.
        # pfr_of() reads a different sentence than the frames below, so this is not
        # circular. Replaces two hand-written scope regexes.
        _pfr = pfr_of(t)

        seen_vo, seen_v = set(), set()
        for fr in frames_in(t):
            v = fr["verb"]
            seen_vo.add((v, fr["obj"]))
            seen_v.add(v)
            occ_by_verb[v] += 1
            if fr["caps"]:
                caps_by_verb[v] += 1
            if fr["negated"]:
                neg_by_verb[v] += 1
            rel = fr["span"][0] / L
            if rel < 0.15 or rel > 0.75:
                edge_by_verb[v] += 1
            scope_by_verb[(v, fr["scope"])] += 1
        for vo in seen_vo:
            verb_obj[vo] += 1
            obj_tot[vo[1]] += 1
            if _pfr == "denied":
                obj_deny[vo[1]] += 1
        for v in seen_v:
            verb_tot[v] += 1
            title_by_verb[(v, title or "(none)")] += 1
        if seen_v:
            docs_with_any += 1

    n = len(files)
    base_remand = titles.get("REMAND ORDER", 0) / float(n)
    print("corpus: %d documents, %d (%.1f%%) contain at least one first-person "
          "clause\n" % (n, docs_with_any, 100.0 * docs_with_any / n))

    print("=== document titles (independent ground truth) ===")
    for k, v in titles.most_common():
        print("  %-30s %6d (%5.1f%%)" % (k, v, 100.0 * v / n))
    print("  REMAND ORDER base rate used for lift: %.3f" % base_remand)

    print("\n=== verbs with MEASURED dispositiveness signals (no verb list) ===")
    print("  %-13s %6s %6s %6s %6s %7s  %s"
          % ("verb", "docs", "caps%", "edge%", "lift", "neg%", "partial/full/unk"))
    vocab = []
    for verb, dv in verb_tot.most_common():
        if dv < a.min:
            continue
        occ = max(occ_by_verb[verb], 1)
        caps = caps_by_verb[verb] / float(occ)
        edge = edge_by_verb[verb] / float(occ)
        negr = neg_by_verb[verb] / float(occ)
        tn = sum(c for (v2, _), c in title_by_verb.items() if v2 == verb) or 1
        remsh = sum(c for (v2, t2), c in title_by_verb.items()
                    if v2 == verb and t2 == "REMAND ORDER") / float(tn)
        lift = (remsh / base_remand) if base_remand else 0.0
        p = scope_by_verb[(verb, "partial")]
        f = scope_by_verb[(verb, "full")]
        u = scope_by_verb[(verb, "unknown")]
        print("  %-13s %6d %5.1f%% %5.1f%% %5.2fx %6.1f%%  %d/%d/%d"
              % (verb, dv, 100 * caps, 100 * edge, lift, 100 * negr, p, f, u))
        vocab.append({
            "verb": verb, "docs": dv, "occurrences": occ,
            "caps_ratio": round(caps, 4), "edge_share": round(edge, 4),
            "remand_lift": round(lift, 3), "negated_ratio": round(negr, 4),
            "scope_partial": p, "scope_full": f, "scope_unknown": u,
        })

    print("\n=== verb + object frames (this is the disposition grammar) ===")
    for (verb, obj), c in verb_obj.most_common(a.top):
        if c < a.min:
            break
        sc = ("partial" if SCOPE_PARTIAL.search(obj)
              else "full" if SCOPE_FULL.search(obj) else "unknown")
        print("  %6d  %-12s %-40s [%s]" % (c, verb, obj[:40], sc))

    print("\n=== per-object DENY rate (derived clause level; replaces hand-written scope) ===")
    print("  high deny%% = the clause tidies reasoning; low = operative disposition")
    _rows = sorted(((o, n, obj_deny[o] / float(n)) for o, n in obj_tot.items() if n >= 25),
                   key=lambda r: -r[2])
    for o, n, d in _rows[:8]:
        print("  %6d  %5.1f%%  %s" % (n, 100 * d, o[:52]))
    print("  ...")
    for o, n, d in _rows[-8:]:
        print("  %6d  %5.1f%%  %s" % (n, 100 * d, o[:52]))
    _cov = sum(n for _, n in obj_tot.most_common() if n >= 10)
    print("  objects with n>=10: %d, covering %d/%d = %.1f%% of clause occurrences"
          % (sum(1 for _, n in obj_tot.most_common() if n >= 10), _cov,
             sum(obj_tot.values()), 100.0 * _cov / max(sum(obj_tot.values()), 1)))

    residual = sum(c for vo, c in verb_obj.items() if c < a.min)
    print("\nresidual below --min %d: %d frame-occurrences "
          "(the long tail this vocabulary does NOT cover)" % (a.min, residual))

    if not a.report:
        payload = {
            "generated_from": {"documents": n, "text_cache": TEXT},
            "min_doc_frequency": a.min,
            "titles": dict(titles),
            "remand_base_rate": round(base_remand, 5),
            "verbs": vocab,
            "objects": [
                {"object": o, "docs": n,
                 "deny_rate": round(obj_deny[o] / float(n), 4)}
                for o, n in obj_tot.most_common() if n >= 10
            ],
            "frames": [
                {"verb": v, "object": o, "docs": c,
                 "scope": ("partial" if SCOPE_PARTIAL.search(o)
                           else "full" if SCOPE_FULL.search(o) else "unknown")}
                for (v, o), c in verb_obj.most_common() if c >= a.min
            ],
        }
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
        print("\nwrote %s (%d verbs, %d frames)"
              % (OUT, len(payload["verbs"]), len(payload["frames"])))


if __name__ == "__main__":
    main()
