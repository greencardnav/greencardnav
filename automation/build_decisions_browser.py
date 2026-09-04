#!/usr/bin/env python3
"""
build_decisions_browser.py - generate niw-decisions.html, a filterable per-decision browser.

WHAT THIS IS
    The aggregate page (niw-appeals.html) answers "what happens to appeals in general". This
    answers "show me the ones like mine", which is the thing the research kept identifying as
    the highest-value free hour a petitioner can spend: read the decisions in your own field
    before you draft. Nothing on the site let you do that.

WHAT CHANGED FROM THE EARLIER POLICY, DELIBERATELY
    build_appeals_page.py withholds the per-decision listing, on the grounds that publishing it
    "turns an aggregate page into a crawlable per-case index". That concern is real but it is
    about individually addressable CASES becoming search results. This page is built so that
    cannot happen:

      * the case rows are NOT in the HTML. They load from niw-decisions.json and render
        client-side, so there is no per-case markup for a crawler to index and no per-case URL
        for it to rank.
      * the page itself is indexable, because the page is the useful thing.

    The identifier shown is the USCIS-published PDF filename (e.g. MAY072026_03B5203), which is
    already public on the USCIS listing. The 8-digit internal case_id is in decisions.json and
    is still rendered nowhere.

WHAT THIS CANNOT DO, AND SAYS SO
    Comparable third-party tools show a plain-English narrative summary per decision. We have
    no summary field, and the indexer has no LLM anywhere in its chain by design - every value
    is deterministically parsed from the PDF text. So each card carries a sentence ASSEMBLED
    from the parsed fields (outcome, occupation, which prongs failed, whether the AAO stopped
    early) rather than a summary of the decision's reasoning. That is thinner, and the page
    says which it is instead of implying it read the case.

    Where a field is missing the card says so. 21% of decisions never state an occupation, 76
    have an order line that could not be parsed, and 1,783 name no prong - and a browser that
    quietly rendered those as blanks would read as broken software rather than as absent data.

USAGE
    python3 automation/build_decisions_browser.py            # dry run
    python3 automation/build_decisions_browser.py --commit
"""

import argparse
import collections
import html
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.expanduser("~/aao-indexer/out/decisions.json")
OUT_HTML = os.path.join(REPO, "niw-decisions.html")
OUT_JSON = os.path.join(REPO, "niw-decisions.json")

# Shared classification rules, imported rather than copied - the same reason
# build_appeals_page.py imports them. A local copy is how the published Software bucket once
# said 133 where the dashboard said 284.
sys.path.insert(0, os.path.join(REPO, "aao-indexer"))
import dashboard as _idx  # noqa: E402

OCC_GROUPS = _idx.OCC_GROUPS
PRECEDENTS = _idx.PRECEDENTS

MERITS = ("dismissed", "sustained", "remanded")

OUTCOME_LABEL = {
    "dismissed": "Dismissed",
    "sustained": "Sustained",
    "remanded": "Remanded",
    "motion_dismissed": "Motion dismissed",
    "motion_granted": "Motion granted",
    "abandoned": "Abandoned",
    "": "Unreadable",
}
# Sentence templates. "%s" takes the subject, which is either the occupation in possessive
# form or a bare "The".
OUTCOME_SENTENCE = {
    "dismissed": "%s appeal was dismissed",
    "sustained": "%s appeal was sustained",
    "remanded": "%s case was sent back to the service center",
    "motion_dismissed": "%s motion to reopen or reconsider was dismissed",
    "motion_granted": "%s motion to reopen or reconsider was granted",
    "abandoned": "%s appeal was treated as abandoned",
}
PRONG_SHORT = {"1": "substantial merit and national importance",
               "2": "well positioned to advance the endeavor",
               "3": "on balance, beneficial to waive the job offer"}


def esc(s):
    return html.escape(str(s), quote=True)


def bucket_of(occ):
    """First-match-wins, exactly as the aggregate page does. Order IS the rule."""
    if not occ:
        return ""
    for name, pat in OCC_GROUPS:
        if re.search(pat, occ, re.I):
            return name
    return "Not classified"


def describe(r):
    """One sentence, assembled from parsed fields. Not a summary of the decision."""
    occ = (r.get("occupation") or "").strip()
    out = r.get("outcome") or ""
    if out not in OUTCOME_SENTENCE:
        s = ("The order line could not be read from this decision, so the outcome is unknown.")
        if occ:
            s += " The petitioner described themselves as %s." % occ
        return s
    if occ:
        subject = "A%s %s's" % ("n" if occ[:1].lower() in "aeiou" else "", occ)
    else:
        subject = "The"
    s = (OUTCOME_SENTENCE[out] % subject).strip()
    s = s[0].upper() + s[1:] + "."
    pf = [c for c in (r.get("prongs_failed") or "") if c in PRONG_SHORT]
    if pf:
        s += " The AAO found the petition fell short on %s." % (
            "prong " + pf[0] if len(pf) == 1
            else "prongs " + ", ".join(pf[:-1]) + " and " + pf[-1])
    if r.get("declined_to_reach") == "yes":
        s += " It stopped there rather than reaching the remaining prongs."
    return s


def payload(rows):
    """Compact column-oriented JSON. Object-per-row with full keys was 1.1 MB; this is ~40% of
    that, because the field names are stated once instead of 4,987 times."""
    # No "txt" field. The description is derived entirely from o, occ, p and dc, so shipping
    # the finished sentence meant repeating the same boilerplate 4,987 times - 1.28 MB of JSON,
    # of which roughly 700 KB was that one field. The client assembles it from the components
    # instead, which states each phrase once. describe() below is kept as the reference
    # implementation and is what the self-check compares the JS against.
    fields = ["id", "d", "y", "o", "occ", "b", "p", "dc", "sc", "ocr", "cites"]
    out = []
    for r in rows:
        pf = "".join(c for c in (r.get("prongs_failed") or "") if c in PRONG_SHORT)
        cites = [k for k in sorted(PRECEDENTS) if r.get("cite_" + k)]
        out.append([
            re.sub(r"\.txt$", "", r.get("file") or ""),
            r.get("date") or "",
            (r.get("date_iso") or "")[:4],
            r.get("outcome") or "",
            r.get("occupation") or "",
            bucket_of(r.get("occupation") or ""),
            pf,
            1 if r.get("declined_to_reach") == "yes" else 0,
            r.get("service_center") or "",
            1 if r.get("occupation_ocr_suspect") else 0,
            cites,
        ])
    out.sort(key=lambda x: (x[1] and x[0][:3], x[0]), reverse=True)
    # Sort properly by real date, newest first, using date_iso which is now on 100% of records.
    iso = {re.sub(r"\.txt$", "", r.get("file") or ""): (r.get("date_iso") or "")
           for r in rows}
    out.sort(key=lambda x: iso.get(x[0], ""), reverse=True)
    return {"fields": fields, "rows": out}


def kpis(rows):
    oc = collections.Counter(r.get("outcome") or "" for r in rows)
    merits = sum(oc[k] for k in MERITS)
    sustained = oc["sustained"]
    remanded = oc["remanded"]
    # Which prong appears most often among decisions where a prong was identified at all.
    pr = collections.Counter()
    parsed = 0
    for r in rows:
        pf = [c for c in (r.get("prongs_failed") or "") if c in PRONG_SHORT]
        if pf:
            parsed += 1
            for c in pf:
                pr[c] += 1
    top = pr.most_common(1)[0] if pr else ("1", 0)
    return {
        "total": len(rows), "oc": oc, "merits": merits,
        "sustained": sustained, "remanded": remanded,
        "one_in": round(merits / sustained) if sustained else 0,
        "top_prong": top[0], "top_prong_share": (100.0 * top[1] / parsed) if parsed else 0,
        "parsed_prong": parsed,
    }


def donut(oc, total):
    """Outcome ring, hand-rolled SVG. Same approach as every other chart on the site: no chart
    library, no external request."""
    order = [("dismissed", "d-dis"), ("motion_dismissed", "d-mot"), ("remanded", "d-rem"),
             ("sustained", "d-sus"), ("", "d-unk")]
    C, R, W = 90, 68, 26
    circ = 2 * 3.14159265 * R
    segs, off, legend = [], 0.0, []
    for key, cls in order:
        n = oc.get(key, 0)
        if not n:
            continue
        frac = n / total
        segs.append(
            '<circle class="%s" cx="%d" cy="%d" r="%d" fill="none" stroke-width="%d" '
            'stroke-dasharray="%.2f %.2f" stroke-dashoffset="%.2f" '
            'transform="rotate(-90 %d %d)"><title>%s: %s (%.1f%%)</title></circle>'
            % (cls, C, C, R, W, circ * frac, circ * (1 - frac), -off * circ, C, C,
               esc(OUTCOME_LABEL.get(key, key)), "{:,}".format(n), 100 * frac))
        legend.append('<li><span class="d-key %s"></span>%s &mdash; %s (%.0f%%)</li>'
                      % (cls, esc(OUTCOME_LABEL.get(key, key)), "{:,}".format(n), 100 * frac))
        off += frac
    return ('<div class="donut-wrap"><svg viewBox="0 0 180 180" class="donut" role="img" '
            'aria-label="Outcome breakdown of %s decisions">%s</svg>'
            '<ul class="donut-legend">%s</ul></div>'
            % ("{:,}".format(total), "".join(segs), "".join(legend)))


# The site shell (topbar nav + footer) is LIFTED from niw-appeals.html rather than copied here.
# Copying it would fork: a nav link added to the 17 hand-written pages would silently skip this
# generated one, and smoke-test.mjs checks every page for the nav and the footer. Lifting means
# the shell can only ever drift if niw-appeals.html itself changes shape, which the asserts catch.
def site_shell():
    src = os.path.join(REPO, "niw-appeals.html")
    html = io.open(src, encoding="utf-8").read()

    # niw-appeals.html has no <main> element - its content root is
    # <div class="container" id="maincontent" role="main">. So the shell header is everything from
    # the topbar up to that id, which also picks up the privacy notice bar that sits between them.
    i = html.find('<div class="topbar"')
    j = html.find('id="maincontent"')
    if i < 0 or j < 0 or j <= i:
        raise SystemExit("could not locate the topbar..maincontent header block in "
                         "niw-appeals.html - the shared shell moved, so this builder needs "
                         "updating")
    # Back up to the opening angle bracket of the element that carries id="maincontent".
    j = html.rfind("<", i, j)
    header = html[i:j].rstrip()

    # The EB Paths tab strip. Lifted for the same reason as the header: this page is a tab in
    # that strip, and a hand-copied strip is how it ended up missing here entirely while the
    # other 8 pages had it - navigating to this page dropped the whole EB Paths nav.
    ti = html.find('<nav class="path-switch"')
    tj = html.find("</nav>", ti)
    if ti < 0 or tj < 0:
        raise SystemExit("could not locate the path-switch tab strip in niw-appeals.html")
    strip = html[ti:tj + len("</nav>")]
    if 'href="niw-decisions.html"' not in strip:
        raise SystemExit("niw-appeals.html's tab strip has no niw-decisions.html tab, so this "
                         "page cannot mark itself active in it - add the tab there first")
    # Move the active state onto this page's own tab.
    strip = strip.replace(' class="active" aria-current="page"', "", 1)
    strip = strip.replace('<a href="niw-decisions.html">',
                          '<a href="niw-decisions.html" class="active" aria-current="page">', 1)

    fi = html.find("<footer")
    fj = html.find("</footer>", fi)
    if fi < 0 or fj < 0:
        raise SystemExit("could not locate <footer> in niw-appeals.html")
    footer = html[fi:fj + len("</footer>")]

    # This page lives under the NIW Appeals section, so carry the active state onto that link and
    # off the EB Paths link it was marked on in the source page.
    # Mark THIS page's own topbar entry active, not the NIW Appeals one. Marking appeals
    # active is what made the trail read "Learn > NIW Appeals" while you were standing on the
    # decisions page - the wrong parent, and the reason the hierarchy looked broken. The
    # entry exists on every page now, so this page can point at itself.
    header = header.replace(' class="active" aria-current="page"', "", 1)
    old_link = '<a href="niw-decisions.html" data-nav="decisions">'
    if old_link not in header:
        raise SystemExit("niw-appeals.html's topbar has no data-nav=\"decisions\" entry, so this "
                         "page cannot mark itself active. Add it to the topbar of the "
                         "hand-written pages first.")
    header = header.replace(
        old_link,
        '<a href="niw-decisions.html" data-nav="decisions" class="active" '
        'aria-current="page">', 1)
    if header.count('aria-current="page"') != 1:
        raise SystemExit("expected exactly one active topbar link, got %d"
                         % header.count('aria-current="page"'))

    # Fail loudly rather than shipping a page the smoke test will reject.
    for needed in ('href="status.html"', 'href="tools.html"'):
        if needed not in header:
            raise SystemExit("lifted header is missing %s" % needed)
    if "site-footer" not in footer and "privacy.html" not in footer:
        raise SystemExit("lifted footer has neither site-footer nor a privacy.html link")
    return header, strip, footer


def page(rows, k, data):
    buckets = sorted({b for b in (bucket_of(r.get("occupation") or "") for r in rows) if b})
    years = sorted({(r.get("date_iso") or "")[:4] for r in rows if r.get("date_iso")}, reverse=True)
    centers = sorted({r.get("service_center") or "" for r in rows if r.get("service_center")})

    def opts(items):
        return "".join('<option value="%s">%s</option>' % (esc(i), esc(i)) for i in items)

    H = []
    A = H.append
    A('''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Browse EB-2 NIW appeal decisions — Green Card Navigator</title>
<meta name="description" content="Filter %s published USCIS Administrative Appeals Office decisions on EB-2 and national interest waiver petitions by outcome, prong, year, occupation and service center.">
<link rel="canonical" href="https://www.greencardnav.com/niw-decisions.html">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="stylesheet" href="styles.css">
</head>
<body class="paths-page">
<a class="skip-link" href="#maincontent">Skip to content</a>
''' % "{:,}".format(k["total"]))

    header, strip, footer = site_shell()
    A(header)

    # The tab strip goes above the page heading, matching where it sits on the 8 sibling pages.
    # No sr-only <h1> here, unlike niw-appeals.html: that page's visible title is an <h2>, so it
    # needs one. This page's visible title IS the <h1>, and adding a second would be two <h1>s.
    A('''<main id="maincontent" class="paths-page">
<div class="container">
%s
<section class="hub-section" id="browse-intro" aria-labelledby="browse-title">
  <span class="hub-eyebrow">EB-2 NIW</span>
  <h1 class="hub-title" id="browse-title">Browse the appeal decisions</h1>
  <p class="hub-sub">Every published USCIS Administrative Appeals Office decision in this
  category, filterable by outcome, prong, year, occupation and service center. Multiple
  approved self-petitioners named reading the decisions in their own field as the most useful
  free hour they spent, so this exists to make that possible. Information, not legal advice.</p>
''' % strip)

    # ---- KPI cards -------------------------------------------------------------
    A('''<div class="kpi-row">
  <div class="kpi"><span class="kpi-label">Decisions indexed</span>
    <span class="kpi-value">%s</span><span class="kpi-note">2015 to 2026</span></div>
  <div class="kpi"><span class="kpi-label">Sustained</span>
    <span class="kpi-value kpi-good">%.1f%%</span>
    <span class="kpi-note">%s of %s decided on the merits, about one in %d</span></div>
  <div class="kpi"><span class="kpi-label">Remanded</span>
    <span class="kpi-value">%.1f%%</span>
    <span class="kpi-note">%s sent back &mdash; not a win</span></div>
  <div class="kpi"><span class="kpi-label">Most contested</span>
    <span class="kpi-value kpi-warn">Prong %s</span>
    <span class="kpi-note">in %.0f%% of decisions naming a prong</span></div>
</div>''' % (
        "{:,}".format(k["total"]),
        100.0 * k["sustained"] / k["merits"] if k["merits"] else 0,
        "{:,}".format(k["sustained"]), "{:,}".format(k["merits"]), k["one_in"],
        100.0 * k["remanded"] / k["merits"] if k["merits"] else 0,
        "{:,}".format(k["remanded"]),
        k["top_prong"], k["top_prong_share"]))

    # h2, not h3: this note follows the page <h1> directly, so h3 skipped a level.
    A('''<div class="note warn"><h2>What these numbers are not</h2>
  Every decision here is an appeal of a petition that was already <strong>denied</strong>, so
  none of this is an approval rate. USCIS does not publish approved petitions, and no
  NIW-specific approval rate exists in any official source.</div>''')
    A("</section>")

    # ---- browse + donut --------------------------------------------------------
    A('''<section class="hub-section" id="browse" aria-labelledby="browse-list-title">
  <span class="hub-eyebrow">Browse</span>
  <h2 class="hub-title" id="browse-list-title">Find the decisions like yours</h2>
  <div class="browse-layout">
  <div class="browse-main">
    <div class="chip-row" role="group" aria-label="Filter by outcome">
      <button type="button" class="fchip is-on" data-outcome="">All outcomes</button>
      <button type="button" class="fchip" data-outcome="dismissed">Dismissed</button>
      <button type="button" class="fchip" data-outcome="remanded">Remanded</button>
      <button type="button" class="fchip" data-outcome="sustained">Sustained</button>
      <button type="button" class="fchip" data-outcome="motion_dismissed">Motions</button>
    </div>
    <div class="filter-row">
      <label class="fl"><span>Prong</span>
        <select id="f-prong"><option value="">Any prong</option>
          <option value="1">Prong 1 &mdash; national importance</option>
          <option value="2">Prong 2 &mdash; well positioned</option>
          <option value="3">Prong 3 &mdash; on balance</option>
          <option value="none">No prong identified</option></select></label>
      <label class="fl"><span>Field</span>
        <select id="f-bucket"><option value="">Any field</option>%s</select></label>
      <label class="fl"><span>Year</span>
        <select id="f-year"><option value="">Any year</option>%s</select></label>
      <label class="fl"><span>Service center</span>
        <select id="f-center"><option value="">Any center</option>%s</select></label>
      <label class="fl"><span>Sort</span>
        <select id="f-sort">
          <option value="desc">Newest first</option>
          <option value="asc">Oldest first</option></select></label>
      <label class="fl fl-wide"><span>Search the occupation</span>
        <input type="search" id="f-q" placeholder="e.g. software, physician, entrepreneur"
               autocomplete="off"></label>
    </div>
    <p class="browse-count" id="browse-count" aria-live="polite"></p>
    <div id="browse-results"></div>
    <nav class="pager" id="pager" aria-label="Pages"></nav>
    <noscript><div class="note warn"><h3>This browser needs JavaScript</h3>
      The %s decisions load from a data file and are filtered in your browser, so nothing is
      sent anywhere. With JavaScript off the list cannot render &mdash; the
      <a href="niw-appeals.html">appeal outcomes page</a> covers the same corpus in aggregate,
      and the full decisions are on the
      <a href="https://www.uscis.gov/administrative-appeals/aao-decisions/aao-non-precedent-decisions"
         target="_blank" rel="noopener noreferrer">USCIS listing</a>.</div></noscript>
  </div>
  <div class="browse-side">   <!-- div, not aside: a nested complementary
       landmark inside a region landmark is an axe violation -->
    <h3 class="side-title">Outcomes at a glance</h3>
    %s
    <h3 class="side-title">How to read a card</h3>
    <div class="note good"><h3>Drafting rather than reading?</h3>
    <p>The <a href="niw-guide.html">step-by-step self-petition guide</a> turns the patterns in
    these decisions into what to actually do, in order.</p></div>
    <p class="help">The sentence on each card is <strong>assembled from parsed fields</strong>
    &mdash; the order line, the stated occupation, which prongs the decision says were not
    established. It is not a summary of the reasoning: nothing here was read by a model. To see
    why a case was decided as it was, open it on the USCIS listing.</p>
    <p class="help">Blank fields are shown as unknown rather than hidden.
    <strong>%s</strong> of decisions never state an occupation, <strong>%s</strong> name no
    prong, and <strong>%s</strong> have an order line that could not be parsed.</p>
  </div>
  </div>
</section>''' % (opts(buckets), opts(years), opts(centers),
                  "{:,}".format(k["total"]), donut(k["oc"], k["total"]),
                  "{:,}".format(sum(1 for r in rows if not r.get("occupation"))),
                  "{:,}".format(k["total"] - k["parsed_prong"]),
                  "{:,}".format(k["oc"].get("", 0))))
    A("</div></main>")
    A(footer)
    return "\n".join(H)


# The renderer. Vanilla JS, no framework, no external request - same constraints as the rest
# of the site. Rows are held as arrays (see payload) and indexed by name once on load.
BROWSER_JS = r"""
<script>
(function () {
  "use strict";
  var PRONG = {
    "1": "prong 1 · national importance",
    "2": "prong 2 · well positioned",
    "3": "prong 3 · on balance"
  };
  var OUT = {
    dismissed: ["Dismissed", "o-dis"], sustained: ["Sustained", "o-sus"],
    remanded: ["Remanded", "o-rem"], motion_dismissed: ["Motion dismissed", "o-mot"],
    motion_granted: ["Motion granted", "o-mot"], abandoned: ["Abandoned", "o-mot"],
    "": ["Outcome unreadable", "o-unk"]
  };
  // Sentence templates, stated once here instead of baked into every row of the data file.
  var SENT = {
    dismissed: "%s appeal was dismissed",
    sustained: "%s appeal was sustained",
    remanded: "%s case was sent back to the service center",
    motion_dismissed: "%s motion to reopen or reconsider was dismissed",
    motion_granted: "%s motion to reopen or reconsider was granted",
    abandoned: "%s appeal was treated as abandoned"
  };
  var PRONG_LONG = { "1": "prong 1", "2": "prong 2", "3": "prong 3" };

  // Assembled from parsed fields. NOT a summary of the decision - nothing here read the case.
  function describe(r) {
    var occ = (r.occ || "").trim();
    if (!SENT[r.o]) {
      return "The order line could not be read from this decision, so the outcome is unknown." +
        (occ ? " The petitioner described themselves as " + occ + "." : "");
    }
    var subject = occ
      ? "A" + ("aeiou".indexOf(occ.charAt(0).toLowerCase()) >= 0 ? "n" : "") + " " + occ + "'s"
      : "The";
    var s = SENT[r.o].replace("%s", subject);
    s = s.charAt(0).toUpperCase() + s.slice(1) + ".";
    var pf = (r.p || "").split("").filter(function (c) { return PRONG_LONG[c]; });
    if (pf.length === 1) s += " The AAO found the petition fell short on prong " + pf[0] + ".";
    else if (pf.length) {
      s += " The AAO found the petition fell short on prongs " +
           pf.slice(0, -1).join(", ") + " and " + pf[pf.length - 1] + ".";
    }
    if (r.dc) s += " It stopped there rather than reaching the remaining prongs.";
    return s;
  }

  var USCIS = "https://www.uscis.gov/administrative-appeals/aao-decisions/" +
              "aao-non-precedent-decisions";
  var PER = 25;

  var results = document.getElementById("browse-results");
  var countEl = document.getElementById("browse-count");
  var pagerEl = document.getElementById("pager");
  if (!results) return;                       // not this page

  var ALL = [], view = [], page = 1;
  var f = { outcome: "", prong: "", bucket: "", year: "", center: "", q: "", sort: "desc" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function apply() {
    var q = f.q.trim().toLowerCase();
    view = ALL.filter(function (r) {
      if (f.outcome && r.o !== f.outcome) return false;
      if (f.prong === "none") { if (r.p) return false; }
      else if (f.prong && r.p.indexOf(f.prong) < 0) return false;
      if (f.bucket && r.b !== f.bucket) return false;
      if (f.year && r.y !== f.year) return false;
      if (f.center && r.sc !== f.center) return false;
      if (q && r.occ.toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    // ALL is ordered newest-first by real date (build sorts on date_iso desc) and .filter
    // preserves order, so "oldest first" is exactly the reverse. No per-row date needed.
    if (f.sort === "asc") view.reverse();
    page = 1;
    draw();
  }

  function card(r) {
    var o = OUT[r.o] || OUT[""];
    var chips = r.p.split("").map(function (c) {
      return '<span class="pchip">' + esc(PRONG[c] || ("prong " + c)) + "</span>";
    }).join("");
    if (!r.p) chips = '<span class="pchip pchip-none">no prong identified</span>';
    if (r.dc) chips += '<span class="pchip pchip-stop">stopped early</span>';
    var cites = (r.cites || []).map(function (c) {
      return '<span class="cchip">' + esc(c) + "</span>";
    }).join("");
    // The occupation is shown verbatim, with a marker when the scan is damaged, rather than
    // being silently "corrected" into something that reads like a real job title.
    var who = r.occ
      ? esc(r.occ) + (r.ocr ? ' <span class="ocr-flag" title="The scan of this decision is ' +
          'damaged, so this text is garbled in the source">scan damaged</span>' : "")
      : '<span class="unknown">occupation not stated</span>';
    return '<article class="dcard">' +
      '<div class="dcard-head">' +
        '<span class="obadge ' + o[1] + '">' + esc(o[0]) + "</span>" +
        '<span class="dmeta">' + esc(r.d || "date unknown") +
          (r.sc ? " · " + esc(r.sc) : "") + " · " +
          '<span class="dcase">' + esc(r.id) + "</span></span>" +
      "</div>" +
      '<p class="dwho">' + who + "</p>" +
      '<p class="dtxt">' + esc(describe(r)) + "</p>" +
      '<div class="dchips">' + chips + cites + "</div>" +
      "</article>";
  }

  function draw() {
    var n = view.length;
    countEl.textContent = n === ALL.length
      ? n.toLocaleString() + " decisions"
      : n.toLocaleString() + " of " + ALL.length.toLocaleString() + " decisions";
    if (!n) {
      results.innerHTML = '<div class="note"><h3>Nothing matches those filters</h3>' +
        "Try widening one of them. Note that 21% of decisions never state an occupation, so a " +
        "field filter necessarily excludes those.</div>";
      pagerEl.innerHTML = "";
      return;
    }
    var pages = Math.ceil(n / PER);
    if (page > pages) page = pages;
    var start = (page - 1) * PER;
    results.innerHTML = view.slice(start, start + PER).map(card).join("");
    var bits = ['<span class="pinfo">Page ' + page + " of " + pages + "</span>"];
    bits.push('<button type="button" class="pbtn" data-go="prev"' +
              (page === 1 ? " disabled" : "") + ">Previous</button>");
    bits.push('<button type="button" class="pbtn" data-go="next"' +
              (page === pages ? " disabled" : "") + ">Next</button>");
    bits.push('<a class="pall" href="' + USCIS + '" target="_blank" rel="noopener noreferrer">' +
              "Read the full decisions on USCIS</a>");
    pagerEl.innerHTML = bits.join("");
  }

  pagerEl.addEventListener("click", function (e) {
    var b = e.target.closest("[data-go]");
    if (!b || b.disabled) return;
    page += (b.getAttribute("data-go") === "next" ? 1 : -1);
    draw();
    document.getElementById("browse").scrollIntoView({ block: "start" });
  });

  document.querySelectorAll(".fchip").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".fchip").forEach(function (x) { x.classList.remove("is-on"); });
      b.classList.add("is-on");
      f.outcome = b.getAttribute("data-outcome") || "";
      apply();
    });
  });
  [["f-prong", "prong"], ["f-bucket", "bucket"], ["f-year", "year"],
   ["f-center", "center"], ["f-sort", "sort"]].forEach(function (pair) {
    var el = document.getElementById(pair[0]);
    if (el) el.addEventListener("change", function () { f[pair[1]] = el.value; apply(); });
  });
  var qEl = document.getElementById("f-q");
  if (qEl) {
    var t;
    qEl.addEventListener("input", function () {
      clearTimeout(t);
      t = setTimeout(function () { f.q = qEl.value; apply(); }, 140);
    });
  }

  results.innerHTML = '<p class="help">Loading the decisions…</p>';
  fetch("niw-decisions.json").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) {
    var F = d.fields;
    ALL = d.rows.map(function (row) {
      var o = {};
      for (var i = 0; i < F.length; i++) o[F[i]] = row[i];
      return o;
    });
    view = ALL;
    apply();
  })["catch"](function (e) {
    results.innerHTML = '<div class="note warn"><h3>Could not load the decision data</h3>' +
      "The rest of the site still works. The full decisions are on the " +
      '<a href="' + USCIS + '" target="_blank" rel="noopener noreferrer">USCIS listing</a>. ' +
      "(" + esc(e.message) + ")</div>";
    pagerEl.innerHTML = "";
  });
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="write the files (default: dry run)")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        raise SystemExit("no decisions.json at %s - run the indexer's parse step first" % SRC)
    rows = json.load(io.open(SRC, encoding="utf-8"))
    k = kpis(rows)
    data = payload(rows)
    doc = page(rows, k, data)

    # The footer/topbar and app.js come from the shared shell the other pages use; this page
    # only needs app.js for the nav, theme and analytics.
    doc += '\n<script src="app.js"></script>\n' + BROWSER_JS + "\n</body>\n</html>\n"

    js = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    print("niw-decisions.html : %s chars" % "{:,}".format(len(doc)))
    print("niw-decisions.json : %s chars for %s decisions"
          % ("{:,}".format(len(js)), "{:,}".format(len(data["rows"]))))
    print("  outcomes: %s" % dict(k["oc"]))
    print("  sustained %s of %s merits (%.2f%%), one in %d"
          % (k["sustained"], k["merits"], 100.0 * k["sustained"] / k["merits"], k["one_in"]))
    if not args.commit:
        print("Dry run: nothing written. Re-run with --commit.")
        return 0
    io.open(OUT_HTML, "w", encoding="utf-8").write(doc)
    io.open(OUT_JSON, "w", encoding="utf-8").write(js + "\n")
    print("wrote %s and %s" % (OUT_HTML, OUT_JSON))
    return 0


if __name__ == "__main__":
    sys.exit(main())
