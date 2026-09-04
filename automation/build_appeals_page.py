#!/usr/bin/env python3
"""Build niw-appeals.html: the AAO appeal-outcome analysis as a gcnav guide page.

WHY A BUILDER
    Every figure comes from ~/aao-indexer/out/decisions.json, which is regenerated
    whenever the crawl is refreshed. Hand-maintaining prose against changing data is how
    a number in a sentence drifts away from the table beside it. Everything here is
    computed at build time from one source, so they cannot disagree.

    The shell (head, topbar, footer) is LIFTED from paths.html at build time rather than
    duplicated, because the site has no build step and those blocks are copy-pasted
    across 17 files. Reading one means this page inherits nav and footer changes instead
    of silently falling behind.

WHY paths.html IS THE DONOR, NOT resources.html
    paths.html IS the EB-2 NIW page (h1 "EB-2 National Interest Waiver (NIW)", 73 NIW
    mentions). eb2.html is the PERM page and explicitly disclaims NIW. Using paths.html
    gives this page body.paths-page, which matters for three MEASURED reasons:
      * .paths-page .container is 1060px, not 900px, so tables and stat cards get 962px
        of width instead of 802px.
      * .paths-page .container > .hub-section > p.hub-sub has max-width:none, so the lead
        paragraph matches every sibling guide page instead of being the only narrow lead
        on the site.
      * .paths-content .hub-section > p.hub-sub resolves to 583px, about 82 characters
        per line, which is inside the readable band. The previous plain-container layout
        mixed a 79.7-CPL lead with 106-CPL body text in the same card, and that 258px
        right-edge mismatch is what read as broken.

WHAT IS NOT PUBLISHED, AND WHY
    The per-decision table. It is 92% of the local dashboard's bytes, and it turns an
    aggregate page into a crawlable per-case index. --with-case-ids exists and defaults
    OFF so publishing it stays an explicit act. Note the identifier involved is the
    USCIS-published PDF filename (e.g. APR012016_01B5203), not the 8-digit case_id --
    that field is in decisions.json but is rendered nowhere, here or locally.

    Also deliberately dropped from the local dashboard:
      * its footer privacy claim ("makes no network requests at all ... nobody can tell
        that you opened it"), which is FALSE here because GoatCounter runs on every page;
      * its theme toggle, which would fight the site's own control over data-theme;
      * two unsourced competitive claims about a named third-party tool.

USAGE
    python3 automation/build_appeals_page.py            # dry run
    python3 automation/build_appeals_page.py --commit
"""

import argparse
import collections
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# SINGLE SOURCE OF TRUTH for anything that determines a NUMBER.
#
# These were duplicated here and in aao-indexer/dashboard.py, and they drifted: OCC_GROUPS
# is a first-match-wins list, so its ORDER is the classification rule. A local reorder
# silently moved people between buckets and the published page said "Software 133 (3%)"
# where the dashboard said 284 (7%) for the same 4,987 decisions. Both looked plausible,
# and the combined-industry total was self-consistent either way, so no arithmetic check
# would have caught it.
#
# Importing rather than copying means a rule can only be changed in one place. The
# per-bucket regexes, the adverse-phrase set, the tooltip definitions and the precedent
# citations/URLs all now come from the indexer.
#
# Display COPY still lives here on purpose: this page is written for a public reader and
# the local dashboard is written for me. What must not diverge is the classification.
sys.path.insert(0, os.path.join(REPO, "aao-indexer"))
import dashboard as _idx

OCC_GROUPS = _idx.OCC_GROUPS          # order is the rule; never reorder locally
PHRASE_LABEL = _idx.PHRASE_LABEL      # which adverse formulations are counted

# Citation text, the count key and the primary-source URL come from the indexer. Only the
# reader-facing gloss is authored here, because the local dashboard is written for me and
# this page is written for someone deciding whether to appeal. Anything that affects a
# NUMBER is shared; only prose differs.
PREC_GLOSS = {
    "Dhanasar": ("the three-prong NIW test",
        "Defines the modern NIW test: the endeavor has substantial merit and national "
        "importance, you are well positioned to advance it, and on balance it benefits the "
        "US to waive the job offer and labor certification. If you read one, read this."),
    "Chawathe": ("the standard of proof",
        "You must show eligibility is more likely than not, not beyond doubt. Nearly every "
        "decision recites it, which is why it sits near the top of this table rather than "
        "because it decides anything."),
    "Bagamasbad": ("authority to stop after one prong",
        "A Supreme Court decision, not an immigration one: agencies need not make findings "
        "on issues whose decision is unnecessary to the result. Where the AAO cites it, it "
        "has almost certainly stopped at prong 1 and never evaluated prongs 2 and 3."),
    "Christos": ("review starts again from scratch",
        "The AAO reviews the whole record afresh rather than checking the service center "
        "for clear error. That cuts both ways: it can find new grounds to deny, and it can "
        "withdraw a prong the service center already granted you."),
    "Katigbak": ("eligibility is fixed on the filing date",
        "You must have met every requirement on the day you filed. Qualifications earned "
        "afterwards do not count, however strong. This is why filing too early is expensive."),
    "Izummi": ("you cannot fix it after filing",
        "The companion to Katigbak: you cannot make material changes after filing to bring "
        "a deficient petition into compliance. Changing how you describe the endeavor "
        "mid-case is the trap this catches."),
    "Furtado": ("evidence produced only on appeal",
        "A 2024 Board of Immigration Appeals decision, the newest authority here. It lets "
        "the AAO refuse evidence produced for the first time on appeal when you were "
        "already put on notice of the gap, usually by an RFE. Answer the RFE fully; the "
        "appeal is not a second chance to file."),
}

# Bagamasbad: the indexer links a law-school mirror. This site's rule is that every
# citation must sit on an official source, so it is overridden to the Library of Congress
# U.S. Reports scan. Kept as an explicit, narrow override rather than a second full copy.
URL_OVERRIDE = {
    "Bagamasbad": ("https://tile.loc.gov/storage-services/service/ll/usrep/usrep429/"
                   "usrep429024/usrep429024.pdf", "U.S. Reports via the Library of Congress"),
}

PRECEDENTS = {}
for _k, _v in _idx.PRECEDENTS.items():
    _url, _note = URL_OVERRIDE.get(_k, (_v["url"], None))
    _forwhat, _held = PREC_GLOSS.get(_k, (_v.get("for", ""), _v.get("held", "")))
    PRECEDENTS[_k] = dict(label=_v["label"], cite=_v["cite"], url=_url,
                          url_note=_note, forwhat=_forwhat, held=_held)
TIPS = dict(_idx.TIPS)                # definitions, so both artifacts define terms alike

TEMPLATE = os.path.join(REPO, "paths.html")
OUT_HTML = os.path.join(REPO, "niw-appeals.html")
SRC = os.path.expanduser("~/aao-indexer/out/decisions.json")

E = html.escape
SLUG = "niw-appeals.html"
TITLE = "What happens when an EB-2 or NIW denial is appealed"
META_TITLE = "EB-2 NIW Appeal Outcomes After a Denial"
DESC = ("What happens if you appeal a denied EB-2 or national interest waiver petition, "
        "counted from USCIS Administrative Appeals Office decisions. Not legal advice.")

AAO_LISTING = ("https://www.uscis.gov/administrative-appeals/aao-decisions/"
               "aao-non-precedent-decisions?uri_1=18&amp;m=All&amp;y=All&amp;items_per_page=100")





SECTIONS = [
    ("appeal-outcomes", "Appeal Outcomes"),
    ("appeal-prongs", "Which Prong Decided It"),
    ("appeal-language", "How Denials Are Worded"),
    ("appeal-precedents", "Key Precedents"),
    ("appeal-who", "Who Appeals"),
    ("appeal-volume", "Decisions by Year"),
    ("appeal-center", "By Service Center"),
    ("appeal-method", "Method and Sources"),
    ("appeal-gaps", "Known Gaps"),
]


def tip(term, label=None):
    d = TIPS.get(term)
    shown = label if label is not None else term
    if not d:
        return shown
    return '<span class="gloss-tip" tabindex="0" title="%s">%s</span>' % (E(d), shown)


def pct(a, b):
    return (100.0 * a / b) if b else 0.0


def n(x):
    return "{:,}".format(x)


def bar(share, tone="t-lose"):
    return ('<span class="rate-bar" aria-hidden="true"><i class="%s" style="width:%.1f%%"></i></span>'
            % (tone, max(0.0, min(100.0, share))))


def year_of(d):
    m = re.search(r"(\d{4})", d or "")
    return m.group(1) if m else None


def section(sid, eyebrow, title, sub, body, caveat=None):
    """A gcnav hub-section.

    The shape is load-bearing twice: styles.css targets these classes, and
    build-search-index.mjs only indexes a section that has an id AND its own
    <h2 class="hub-title">. A plain <h2> yields zero search entries.
    """
    cav = ('<p class="band-caveat">%s</p>' % caveat) if caveat else ""
    return ('<section class="hub-section" id="%s" aria-labelledby="%s-title">'
            '<span class="hub-eyebrow">%s</span>'
            '<h2 class="hub-title" id="%s-title">%s</h2>'
            '<p class="hub-sub">%s</p>%s%s</section>'
            % (sid, sid, eyebrow, sid, title, sub, body, cav))


def shell(path):
    """Split paths.html into (head+topbar, footer+scripts) and retarget its metadata."""
    s = open(path, encoding="utf-8").read()
    m = re.search(r'<div class="container" id="maincontent"[^>]*>', s)
    if not m:
        raise SystemExit("donor has no #maincontent container")
    head = s[:m.end()]
    j = s.rfind('<footer class="site-footer"')
    k = s.rfind("</div>", 0, j)
    tail = s[k:]

    head = re.sub(r'<title>[^<]*</title>',
                  '<title>%s &mdash; Green Card Navigator</title>' % E(META_TITLE), head)
    for pat in (r'(<meta name="description" content=")[^"]*(")',
                r'(<meta property="og:description" content=")[^"]*(")',
                r'(<meta name="twitter:description" content=")[^"]*(")'):
        head = re.sub(pat, lambda mm: mm.group(1) + E(DESC) + mm.group(2), head)
    for pat in (r'(<meta property="og:title" content=")[^"]*(")',
                r'(<meta name="twitter:title" content=")[^"]*(")'):
        head = re.sub(pat, lambda mm: mm.group(1) + E(META_TITLE) + mm.group(2), head)
    head = head.replace("/paths.html", "/" + SLUG)
    head = re.sub(r'<h1 class="sr-only">[^<]*</h1>', '', head)
    return head, tail


def path_switch():
    """The guide tab strip, with THIS page marked active.

    Previously nothing was marked, on the reasoning that appeals is not a "path". The
    practical effect was that a reader landing here saw the strip with no current-page
    indicator at all, while the topbar highlighted EB Paths - so the page looked like it
    belonged to the family but gave no position within it. Carrying its own tab, marked
    active, is the orientation fix. The strip's aria-label is widened accordingly, since
    "Choose a green card path" no longer describes the whole set.
    """
    tabs = [("eb1a.html", "EB-1A"), ("eb1b.html", "EB-1B"), ("eb1c.html", "EB-1C"),
            ("eb2.html", "EB-2"), ("paths.html", "EB-2 NIW"), ("eb3.html", "EB-3"),
            ("compare.html", "Compare"), (SLUG, "NIW Appeals"),
            # Labels are kept short because the strip has to fit the content column. The
            # earlier "there is no room for a tenth tab" call was measured against a 662px
            # column and is stale: the container is now aligned to the topbar, so the column is
            # 876px and there is room. A page that DISPLAYS this strip should have a tab in it.
            # The footer and the Learn dropdown keep the longer labels.
            ("niw-decisions.html", "NIW Decisions"),
            ("niw-guide.html", "NIW Guide")]
    out = []
    for href, label in tabs:
        if href == SLUG:
            out.append('<a href="%s" class="active" aria-current="page">%s</a>' % (href, label))
        else:
            out.append('<a href="%s">%s</a>' % (href, label))
    return ('<nav class="path-switch" aria-label="Green card paths and appeal data">%s</nav>'
            % "".join(out))


def toc(items):
    rows = "".join('<a href="#%s">%s</a>' % (i, t) for i, t in items)
    return ('<details class="paths-toc" open><summary>On this page</summary>'
            '<nav aria-label="On this page">%s</nav></details>' % rows)


def build(rows, with_case_ids):
    total = len(rows)
    oc = collections.Counter(r.get("outcome") or "unparsed" for r in rows)
    merits = oc["dismissed"] + oc["sustained"] + oc["remanded"]
    one_in = round(merits / oc["sustained"]) if oc["sustained"] else 0
    H = []
    A = H.append

    # ---- lead ---------------------------------------------------------------
    # Distinct from the intro h2 below: an sr-only h1 identical to the first visible
    # heading makes a screen reader announce the same sentence twice.
    A('<h1 class="sr-only">EB-2 NIW appeal outcomes</h1>')
    A(path_switch())
    A('<section class="hub-section" id="niw-appeals-intro" '
      'aria-labelledby="niw-appeals-intro-title">'
      '<span class="hub-eyebrow">EB-2 NIW</span>'
      '<h2 class="hub-title" id="niw-appeals-intro-title">%s</h2>'
      '<p class="hub-sub">If USCIS denies an EB-2 or national interest waiver petition, '
      'the petitioner can appeal to the USCIS Administrative Appeals Office. This page '
      'counts how those appeals actually end, and the short answer is that they almost '
      'never win. Information, not legal advice.</p>' % E(TITLE))

    cards = ['<div class="bulletin-row">']
    for label, value, sub in [
        ("Decisions analysed", n(total), "published 2015 to 2026"),
        ("Appeal dismissed", "%.0f%%" % pct(oc["dismissed"], merits),
         "%s of %s decided on the %s" % (n(oc["dismissed"]), n(merits), tip("merits"))),
        ("Sent back to be redecided", "%.0f%%" % pct(oc["remanded"], merits),
         "%s %s, which is not a win" % (n(oc["remanded"]), tip("remanded"))),
        ("Won outright", "%.1f%%" % pct(oc["sustained"], merits),
         "%s %s, about one in %d" % (n(oc["sustained"]), tip("sustained"), one_in)),
    ]:
        cards.append('<div class="bulletin-cell"><div class="label">%s</div>'
                     '<div class="value">%s</div><div class="sub">%s</div></div>'
                     % (label, value, sub))
    cards.append('</div>')
    A("".join(cards))

    A('<div class="plain-explain"><div class="pe-label">What this actually means</div>'
      'Appealing almost never wins. Of the %s decisions decided on the merits, '
      '<strong>%s were dismissed</strong> and only <strong>%s were sustained</strong>, '
      'about one in %d. A remand is the realistic good outcome and it is not a win: it '
      'means the service center has to decide the case again properly. So getting the '
      'petition right the first time matters far more than the appeal does, and refiling '
      'is often the better move than appealing.</div>'
      % (n(merits), n(oc["dismissed"]), n(oc["sustained"]), one_in))

    A('<p class="help">Counted from %s decisions the Administrative Appeals Office '
      'published between 2015 and 2026, read straight out of the decision PDFs. No '
      'language model is involved at any stage. '
      '<a href="#appeal-method">How these numbers were produced</a>.</p>' % n(total))
    # Point the reader at the per-decision browser. This lived only in the generated HTML
    # before, so this script deleted it on the next run.
    A('<div class="note good"><h3>Read the decisions yourself</h3>'
      '<p>Every one of the %s decisions is browsable one at a time, with filters for outcome, '
      'year, occupation, which prong failed, and which precedent the officer cited. '
      '<a href="niw-decisions.html">Browse all %s decisions</a>. If you are drafting a '
      'petition rather than reading about one, the '
      '<a href="niw-guide.html">step-by-step self-petition guide</a> turns these patterns '
      'into what to actually do.</p></div>' % (n(total), n(total)))
    A('<p class="band-caveat">General information about published decisions. Not legal '
      'advice, and not a prediction about any individual case.</p>')
    A('</section>')
    A('%%%TOC_SPLIT%%%')

    # ---- outcomes -----------------------------------------------------------
    tones = {"dismissed": "t-lose", "motion dismissed": "t-lose", "abandoned": "t-lose",
             "unparsed": "t-lose", "remanded": "t-mid", "sustained": "t-win",
             "motion granted": "t-mid"}
    b = ['<div class="table-scroll"><table class="paths-table"><thead><tr><th>Outcome</th><th class="num">Decisions</th>'
         '<th class="num">Share</th><th class="rate">Rate</th></tr></thead><tbody>']
    for k, v in oc.most_common():
        lbl = k.replace("_", " ")
        b.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="rate">%s</td></tr>'
                 % (tip(lbl), n(v), pct(v, total), bar(pct(v, total), tones.get(lbl, "t-lose"))))
    b.append('</tbody></table></div>')
    b.append('<p class="help">Hover any outcome for what it means. A motion to reopen or '
             'reconsider is a different procedural posture from an appeal, and harder, '
             'which is why the headline rates above exclude them.</p>')
    A(section("appeal-outcomes", "EB-2 NIW", "Appeal Outcomes",
              "Every outcome the parser found, as a share of all %s decisions." % n(total),
              "".join(b)))

    # ---- prongs -------------------------------------------------------------
    pr = collections.Counter()
    for r in rows:
        for d in (r.get("prongs_failed") or ""):
            if d in "123":
                pr[d] += 1
    parsed = sum(1 for r in rows if r.get("prongs_failed"))
    sole1 = sum(1 for r in rows if (r.get("prongs_failed") or "") == "1")
    declined = sum(1 for r in rows if r.get("declined_to_reach"))
    names = {"1": ("Prong 1", "substantial merit and national importance"),
             "2": ("Prong 2", "well positioned to advance it"),
             "3": ("Prong 3", "benefit of waiving the job offer")}
    b = ['<div class="table-scroll"><table class="paths-table"><thead><tr><th>Ground</th><th class="num">Decisions</th>'
         '<th class="num">Share</th><th class="rate">Rate</th></tr></thead><tbody>']
    for d in "123":
        t, gloss = names[d]
        b.append('<tr><td>%s: %s</td><td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="rate">%s</td></tr>'
                 % (tip(t), gloss, n(pr[d]), pct(pr[d], parsed), bar(pct(pr[d], parsed), "t-lang")))
    for lbl, cnt in [("Prong 1 as the only ground given", sole1),
                     ("AAO stopped without reaching the later prongs", declined)]:
        b.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="rate">%s</td></tr>'
                 % (lbl, n(cnt), pct(cnt, parsed), bar(pct(cnt, parsed), "t-lose")))
    b.append('</tbody></table></div>')
    b.append('<p class="help">Shares are of the <strong>%s</strong> decisions where a '
             'prong could be identified, not of all %s. A decision can fail more than one '
             'prong, so these do not sum to 100%%. The other %s name no prong the parser '
             'could read and are left blank rather than guessed.</p>'
             % (n(parsed), n(total), n(total - parsed)))
    A(section("appeal-prongs", "EB-2 NIW", "Which Prong Decided It",
              "Prong 1 is where almost all of these petitions fail, and in a fifth of "
              "decisions the AAO never evaluates prongs 2 and 3 at all.", "".join(b)))

    # ---- adverse language ---------------------------------------------------
    ph = sorted(((sum(1 for r in rows if r.get("ph_" + k)), lbl)
                 for k, lbl in PHRASE_LABEL.items()),
                reverse=True)
    b = ['<div class="table-scroll"><table class="paths-table"><thead><tr><th>What the decision says</th>'
         '<th class="num">Decisions</th><th class="num">Share</th>'
         '<th class="rate">Rate</th></tr></thead><tbody>']
    for c, lbl in ph:
        if not c:
            continue
        b.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td class="rate">%s</td></tr>'
                 % (lbl, n(c), pct(c, total), bar(pct(c, total), "t-lang")))
    b.append('</tbody></table></div>')
    top_c, _ = ph[0]
    b.append('<div class="note warn"><h3>The top line is the whole game</h3>'
             'In %s decisions, %.1f%% of the total, the AAO had to explain that the '
             'importance of your <em>field</em> is not the question it was asked. The '
             'question is whether <em>your own specific proposed work</em> is nationally '
             'important. That is the most common way these petitions are argued wrong.</div>'
             % (n(top_c), pct(top_c, total)))
    A(section("appeal-language", "EB-2 NIW", "How Denials Are Worded",
              "The same formulations recur. Counted as the number of decisions containing "
              "each one at least once.", "".join(b)))

    # ---- precedents ---------------------------------------------------------
    b = ['<div class="table-scroll"><table class="paths-table"><thead><tr><th>Case</th><th class="num">Decisions</th>'
         '<th class="num">Share</th><th>What it decides</th></tr></thead><tbody>']
    prec = sorted(((sum(1 for r in rows if r.get("cite_" + k)), k) for k in PRECEDENTS),
                  reverse=True)
    for c, k in prec:
        if not c:
            continue
        p = PRECEDENTS[k]
        host = p["url"].split("/")[2].replace("www.", "")
        note = p.get("url_note") or host
        b.append('<tr><td><a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                 '<br><span class="band-caveat">%s</span></td>'
                 '<td class="num">%s</td><td class="num">%.1f%%</td>'
                 '<td><strong>%s</strong><br>%s'
                 '<br><span class="band-caveat">Full text on %s.</span></td></tr>'
                 % (p["url"], p["label"], p["cite"], n(c), pct(c, total),
                    p["forwhat"], p["held"], E(note)))
    b.append('</tbody></table></div>')
    b.append('<div class="note good"><h3>Read this ranking carefully</h3>'
             'It is mostly a ranking of procedural boilerplate, not of substantive '
             'doctrine. Dhanasar and Chawathe sit within a percentage point of each other '
             'because nearly every decision recites both the test and the burden of '
             'proof. The genuinely informative entry is <strong>Bagamasbad</strong>: it is '
             'the authority for declining to reach your remaining prongs, so wherever it '
             'appears the AAO probably never evaluated prongs 2 and 3. Two of these are '
             'not AAO decisions at all &mdash; Bagamasbad is a 1976 Supreme Court case, '
             'and Furtado is a 2024 Board of Immigration Appeals decision, the newest '
             'authority here.</div>')
    A(section("appeal-precedents", "EB-2 NIW", "Key Precedents",
              "Seven authorities account for almost all of the reasoning. Each links to "
              "its full text so you can check these summaries against the original.",
              "".join(b)))

    # ---- who appeals --------------------------------------------------------
    groups = collections.Counter()
    occ_total = 0
    for r in rows:
        o = (r.get("occupation") or "").strip()
        if not o or re.match(r"(?i)^member of the professions", o):
            continue
        occ_total += 1
        for label, pat in OCC_GROUPS:
            if re.search(pat, o, re.I):
                groups[label] += 1
                break
        else:
            groups["Not classified"] += 1
    if occ_total:
        b = ['<div class="table-scroll"><table class="paths-table"><thead><tr><th>Self-described as</th>'
             '<th class="num">Decisions</th><th class="num">Share</th>'
             '<th class="rate">Rate</th></tr></thead><tbody>']
        for label, c in groups.most_common():
            b.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.0f%%</td>'
                     '<td class="rate">%s</td></tr>'
                     % (label, n(c), pct(c, occ_total), bar(pct(c, occ_total), "t-lang")))
        b.append('</tbody></table></div>')
        # Read the combined-industry buckets by NAME from the shared list, and fail loudly
        # if a name no longer exists. A plain groups["..."] lookup on a Counter returns 0
        # for a missing key, so the previous line silently dropped the whole engineering
        # bucket: it asked for "Engineering, other than software" while the shared label is
        # "Engineering, other". The published sentence therefore understated the industry
        # share by every engineer in the docket, and read as a plausible number.
        def bucket(label):
            if label not in dict(OCC_GROUPS):
                raise SystemExit(
                    "occupation bucket %r no longer exists in the shared OCC_GROUPS. "
                    "Real labels: %s. Fix the name here rather than letting the Counter "
                    "return 0 and quietly understate the published figure."
                    % (label, ", ".join(k for k, _ in OCC_GROUPS)))
            return groups[label]

        industry = (bucket("Business and entrepreneurship")
                    + bucket("Engineering, other")
                    + bucket("Software, IT and data"))
        acad = bucket("Academic and research")
        b.append('<div class="note warn"><h3>This is an industry docket, not a '
                 'researcher&rsquo;s docket</h3>'
                 'Business, engineering and software together are <strong>%s of %s</strong> '
                 '(%.0f%%). Academic and research petitioners are <strong>%s</strong> '
                 '(%.0f%%). Whatever you have read about the NIW being a route for '
                 'researchers, the appeal docket is dominated by people working in '
                 'industry.</div>'
                 % (n(industry), n(occ_total), pct(industry, occ_total),
                    n(acad), pct(acad, occ_total)))
        b.append('<p class="help">Taken from each decision&rsquo;s own opening line, in %s '
                 'of %s cases. The groupings are keyword rules written for this page, not '
                 'an official taxonomy, so treat them as indicative. &ldquo;Not '
                 'classified&rdquo; is shown rather than hidden. Petitions whose opening '
                 'line says only &ldquo;member of the professions&rdquo; are excluded, '
                 'because that describes no occupation.</p>' % (n(occ_total), n(total)))
        A(section("appeal-who", "EB-2 NIW", "Who Appeals",
                  "Petitioners in their own words, from the first line of each decision.",
                  "".join(b)))

    # ---- volume by year -----------------------------------------------------
    by_year = collections.Counter()
    stack = collections.defaultdict(collections.Counter)
    for r in rows:
        y = year_of(r.get("date"))
        if not y:
            continue
        by_year[y] += 1
        stack[y][r.get("outcome") or "unparsed"] += 1
    if by_year:
        years = sorted(by_year)
        peak = max(by_year.values())
        W, HT, PADL, PADB = 640, 200, 40, 22
        plot_h = HT - PADB - 10
        colw = (W - PADL) / float(len(years))
        order = [("dismissed", "var(--neutral-500)"),
                 ("motion_dismissed", "var(--neutral-350)"),
                 ("remanded", "var(--success-600)"),
                 ("sustained", "var(--amber-400)"),
                 ("unparsed", "var(--neutral-250)"),
                 ("abandoned", "var(--neutral-250)"),
                 ("motion_granted", "var(--success-600)")]
        busiest = max(by_year, key=by_year.get)
        sv = ['<svg class="perm-svg" viewBox="0 0 %d %d" role="img" aria-label="Decisions '
              'published per year from %s to %s, stacked by outcome. The busiest year is '
              '%s with %s decisions.">' % (W, HT, years[0], years[-1], busiest, n(peak))]
        for i in range(5):
            gy = 10 + plot_h * i / 4.0
            val = int(round(peak * (4 - i) / 4.0))
            sv.append('<line class="perm-grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
                      % (PADL, gy, W, gy))
            sv.append('<text class="perm-axlabel" x="%d" y="%.1f" text-anchor="end">%s</text>'
                      % (PADL - 6, gy + 3.5, n(val)))
        for xi, y in enumerate(years):
            x = PADL + xi * colw + colw * 0.18
            bw = colw * 0.64
            ytop = 10 + plot_h
            for key, color in order:
                c = stack[y].get(key, 0)
                if not c:
                    continue
                h = plot_h * c / float(peak)
                ytop -= h
                sv.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                          % (x, ytop, bw, h, color))
            sv.append('<text class="perm-axlabel" x="%.1f" y="%d" text-anchor="middle">%s'
                      '</text>' % (x + bw / 2.0, HT - 5, y))
        sv.append('</svg>')
        legend = ('<div class="perm-legend">'
                  '<span class="perm-leg"><i class="perm-leg-swatch" style="background:var(--neutral-500)"></i>dismissed</span>'
                  '<span class="perm-leg"><i class="perm-leg-swatch" style="background:var(--neutral-350)"></i>motion dismissed</span>'
                  '<span class="perm-leg"><i class="perm-leg-swatch" style="background:var(--success-600)"></i>remanded</span>'
                  '<span class="perm-leg"><i class="perm-leg-swatch" style="background:var(--amber-400)"></i>sustained</span>'
                  '</div>')
        undated = total - sum(by_year.values())
        A(section("appeal-volume", "EB-2 NIW", "Decisions by Year",
                  "The shape of the record. A taller bar means more decisions were "
                  "published that year, not a better or worse chance of winning.",
                  legend + "".join(sv) +
                  '<p class="help">%s of %s decisions carry no date the parser could read '
                  'and are not in this chart. Bar height reflects both how many people '
                  'appealed and how quickly the AAO published, so it is not a success '
                  'rate.</p>' % (n(undated), n(total))))

    # ---- service center -----------------------------------------------------
    sc = collections.Counter(r["service_center"] for r in rows if r.get("service_center"))
    if sc:
        sc_total = sum(sc.values())
        b = ['<div class="table-scroll"><table class="paths-table"><thead><tr><th>Service center</th>'
             '<th class="num">Decisions</th><th class="num">Share</th>'
             '<th class="rate">Rate</th></tr></thead><tbody>']
        for k, v in sc.most_common():
            b.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%.0f%%</td>'
                     '<td class="rate">%s</td></tr>'
                     % (E(k), n(v), pct(v, sc_total), bar(pct(v, sc_total), "t-lang")))
        b.append('</tbody></table></div>')
        b.append('<div class="note"><h3>What this does not settle</h3>'
                 'A claim that circulates in applicant forums is that one service center '
                 'issues NIW requests for evidence at many times another&rsquo;s rate. '
                 'These counts lean the same way but nowhere near that strongly, and '
                 'appeal volume is not the same measurement as an RFE rate. This neither '
                 'confirms nor refutes it.</div>')
        # Do NOT describe this as a "pre-2017 format" quirk. Measured over the corpus, the
        # centre is named in essentially every decision from 2015 through 2024 (100% in most
        # years), then 44% in 2025 and 0% in 2026 - USCIS stopped naming it partway through
        # 2025. So the gap is recent, not old, and the comparison below is a 2015-2024
        # statement rather than a current one. Saying "some formats" implied a parser or
        # vintage quirk and pointed the reader at the wrong end of the corpus.
        b.append('<p class="help">Decisions named the service center consistently from 2015 '
                 'through 2024, then stopped: 44%% of 2025 decisions name it and none of the '
                 '2026 ones do. So this covers %s of %s decisions (%.0f%%) and is best read '
                 'as a statement about 2015 to 2024, not about how the centers compare today. '
                 'A center with only a handful of decisions is shown for completeness and '
                 'should not be read as a meaningful rate.</p>'
                 % (n(sc_total), n(total), pct(sc_total, total)))
        A(section("appeal-center", "EB-2 NIW", "By Service Center",
                  "Where the original denial came from, in the decisions that name it.",
                  "".join(b)))

    # ---- method -------------------------------------------------------------
    b = ['<p class="paths-p">A script downloads each decision as a PDF, extracts the text, '
         'and reads the fields out using fixed text patterns. Every row keeps the exact '
         'sentence it matched, so any figure here can be traced back to its own PDF. No '
         'language model is involved at any stage, so nothing on this page is summarised '
         'or inferred.</p>',
         '<p class="paths-p">Coverage is <strong>%s</strong> decisions against about '
         '<strong>5,122</strong> that the USCIS listing exposes for 2015 to 2026, roughly '
         '97%%. You can <a href="%s" target="_blank" rel="noopener noreferrer">browse the '
         'source listing</a> yourself; it is the authoritative record.</p>'
         % (n(total), AAO_LISTING),
         '<p class="paths-p">The parser records nothing rather than guessing, so some '
         'fields are sparse: no prong for %.1f%%, no self-described occupation for %.1f%%, '
         'no service center for %.1f%%, no date for %.1f%%. Every share on this page is '
         'computed over the decisions where that field was actually found, and each table '
         'states which denominator it used. A sparse field means a smaller denominator, '
         'not a zero.</p>'
         % (pct(sum(1 for r in rows if not r.get("prongs_failed")), total),
            pct(sum(1 for r in rows if not r.get("occupation")), total),
            pct(sum(1 for r in rows if not r.get("service_center")), total),
            pct(sum(1 for r in rows if not r.get("date")), total))]
    if not with_case_ids:
        b.append('<p class="paths-p">The decision-by-decision listing is not published '
                 'here. Browse it on the USCIS listing linked above.</p>')
    b.append('<div class="note warn"><h3>The one thing this cannot tell you</h3>'
             'Every decision here is an appeal of a <strong>denied</strong> petition. This '
             'is not a sample of NIW petitions generally, so nothing on this page is an '
             'approval rate. USCIS does not publish approved petitions, and no '
             'NIW-specific approval rate exists in any official source. A three per cent '
             'success rate on appeal says nothing about your chance of approval on a first '
             'filing.</div>')
    A(section("appeal-method", "Method", "Method and Sources",
              "Deterministic parsing of the source PDFs, and an honest account of what is "
              "missing.", "".join(b)))

    # ---- gaps ---------------------------------------------------------------
    b = ['<ul>',
         '<li><strong>EB-1A criterion outcomes.</strong> The same listing publishes EB-1A '
         'extraordinary-ability decisions under a different category. Counting which of '
         'the ten criteria fail needs a separate parser and a separate crawl, so it is '
         'absent rather than estimated.</li>',
         '<li><strong>Approval rates of any kind.</strong> Nothing here can be turned into '
         'one. See the note above.</li>',
         '<li><strong>Why any individual case was decided.</strong> These are counts of '
         'what decisions say, not an assessment of whether the AAO was right.</li>',
         '</ul>']
    A(section("appeal-gaps", "Method", "Known Gaps",
              "Gaps named on purpose, because a plausible-looking number would be worse "
              "than an admitted blank.", "".join(b),
              caveat="Published decisions are public records. This page counts them. It "
                     "is not legal advice and it is not a substitute for a licensed "
                     "immigration attorney."))
    return "".join(H)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--with-case-ids", action="store_true",
                    help="publish the per-decision table (defaults OFF)")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print("no %s - run: python3 ~/aao-indexer/aao_index.py parse" % SRC, file=sys.stderr)
        return 2
    rows = json.load(open(SRC, encoding="utf-8"))
    head, tail = shell(TEMPLATE)
    body = build(rows, args.with_case_ids)
    # Split at the marker: everything before it is the full-width intro, everything
    # after is the module column, and the TOC sits between them as the grid sidebar.
    intro, _, modules = body.partition('%%%TOC_SPLIT%%%')
    # Intro goes INSIDE .paths-content so the left sticky TOC top-aligns with it rather
    # than starting below it. Measured before: the TOC began 866px down the page.
    page = (head
            + '\n<div class="paths-layout">\n' + toc(SECTIONS)
            + '\n<div class="paths-content">\n' + intro + "\n" + modules
            + '\n</div>\n</div>\n' + tail)

    print("%s: %d decisions, %d chars%s"
          % (SLUG, len(rows), len(page), "" if args.commit else "   (DRY RUN)"))
    print("  case identifiers: %s" % ("PUBLISHED" if args.with_case_ids else "withheld"))
    if not args.commit:
        print("Dry run: nothing written.")
        return 0
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    print("wrote %s" % OUT_HTML)
    return 0


if __name__ == "__main__":
    sys.exit(main())
