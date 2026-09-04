#!/usr/bin/env python3
"""
build_niw_guide.py - generate niw-guide.html, a step-by-step EB-2 NIW self-petition guide.

WHAT THIS IS
    The site already explains what EB-2 NIW is (paths.html), what happens to appeals in
    aggregate (niw-appeals.html), and lets you read the decisions one at a time
    (niw-decisions.html). None of those tell somebody who has never done this what to
    actually DO, in what order. This does.

    The target reader has no immigration knowledge and finishes the page able to say where
    to begin, what to gather, what to write, what to file, and what to do if it goes wrong.

WHY IT IS A BUILDER AND NOT A HAND-WRITTEN PAGE
    Same reason as niw-appeals.html and niw-decisions.html: the shell (topbar, privacy bar,
    tab strip, footer) is LIFTED from niw-appeals.html at build time, so a nav change made
    once reaches this page too. Hand-editing a generated page is how the Decisions tab got
    silently deleted on the next build.

WHERE THE CONTENT CAME FROM, AND WHAT WAS DELIBERATELY LEFT OUT
    Four research passes over the 4,987-decision corpus in ~/aao-indexer/ plus official
    sources. Every statistic here is from that corpus and is stated with its denominator.
    Every fee, deadline and regulation carries a citable official source.

    LEFT OUT ON PURPOSE:
      * Any law firm recommendation, rating, or criticism. Firms may be listed as
        information sources with neutral descriptions; that is the whole of it. The
        "getting help" section teaches the reader to score any firm instead, which also
        works for the firm nobody has reviewed.
      * Per-firm pricing. Attorney fees are given as observed ranges with the basis stated
        and no firm attached.
      * Anything sourced from a private community channel. Aggregated, anonymised patterns
        only, and never as an authority for a legal claim.
      * Any quotation of a petitioner's personal circumstances from a decision. Quoting the
        AAO's LEGAL REASONING is fine and is done here. Quoting somebody's story is not.
      * Any approval rate. USCIS does not publish approved petitions, so no NIW approval
        rate exists in any official source. Every number here has "of appealed denials in
        this corpus" as its denominator, and the page says so.

    IT IS A TAB IN THE EB PATHS STRIP. An earlier version of this file claimed there was no
    room for a tenth tab, measured against a 662px content column. That measurement is stale:
    the container is now aligned to the topbar, so the column is 876px. A page that DISPLAYS
    the strip and has no tab in it is the thing that reads as broken. Also reachable from the
    Learn dropdown, the footer, and a callout on paths.html.

USAGE
    python3 automation/build_niw_guide.py            # dry run
    python3 automation/build_niw_guide.py --commit
"""

import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "niw-guide.html")
SHELL_SRC = os.path.join(REPO, "niw-appeals.html")

TITLE = "How to self-petition an EB-2 NIW"


# ---------------------------------------------------------------------------
# Shell lifting - identical contract to build_decisions_browser.py
# ---------------------------------------------------------------------------
def site_shell():
    html = io.open(SHELL_SRC, encoding="utf-8").read()

    i = html.find('<div class="topbar"')
    j = html.find('id="maincontent"')
    if i < 0 or j < 0 or j <= i:
        raise SystemExit("could not locate the topbar..maincontent block in niw-appeals.html")
    j = html.rfind("<", i, j)
    header = html[i:j].rstrip()

    ti = html.find('<nav class="path-switch"')
    tj = html.find("</nav>", ti)
    if ti < 0 or tj < 0:
        raise SystemExit("could not locate the path-switch strip in niw-appeals.html")
    strip = html[ti:tj + len("</nav>")]

    fi = html.find("<footer")
    fj = html.find("</footer>", fi)
    if fi < 0 or fj < 0:
        raise SystemExit("could not locate <footer> in niw-appeals.html")
    footer = html[fi:fj + len("</footer>")]

    # This page now HAS a tab in the strip, so move the active state onto it rather than
    # leaving NIW Appeals lit while you stand here.
    strip = strip.replace(' class="active" aria-current="page"', "", 1)
    tab = '<a href="niw-guide.html">'
    if tab not in strip:
        raise SystemExit("niw-appeals.html's tab strip has no niw-guide.html tab, so this page "
                         "cannot mark itself active in it. Add it to the tab list in "
                         "build_appeals_page.py first.")
    strip = strip.replace(tab, '<a href="niw-guide.html" class="active" aria-current="page">', 1)

    # Topbar: this page lives under Learn, so mark its own entry.
    header = header.replace(' class="active" aria-current="page"', "", 1)
    link = '<a href="niw-guide.html" data-nav="guide">'
    if link not in header:
        raise SystemExit('niw-appeals.html has no data-nav="guide" topbar entry, so this page '
                         "cannot mark itself active. Add it to the hand-written pages first.")
    header = header.replace(
        link, '<a href="niw-guide.html" data-nav="guide" class="active" aria-current="page">', 1)
    if header.count('aria-current="page"') != 1:
        raise SystemExit("expected exactly one active topbar link, got %d"
                         % header.count('aria-current="page"'))
    for needed in ('href="status.html"', 'href="tools.html"'):
        if needed not in header:
            raise SystemExit("lifted header is missing %s" % needed)
    if "site-footer" not in footer and "privacy.html" not in footer:
        raise SystemExit("lifted footer has neither site-footer nor a privacy.html link")
    return header, strip, footer


# ---------------------------------------------------------------------------
# Small helpers so every section is built the same way
# ---------------------------------------------------------------------------
def section(sid, eyebrow, title, sub, body):
    return ('<section class="hub-section" id="%s" aria-labelledby="%s-t">'
            '<span class="hub-eyebrow">%s</span>'
            '<h2 class="hub-title" id="%s-t">%s</h2>'
            '<p class="hub-sub">%s</p>%s</section>' % (sid, sid, eyebrow, sid, title, sub, body))


def collapsible(summary, body):
    return ('<details class="collapsible"><summary>%s</summary>'
            '<div class="body">%s</div></details>' % (summary, body))


def note(title, body, kind=""):
    k = (" " + kind) if kind else ""
    return '<div class="note%s"><h3>%s</h3>%s</div>' % (k, title, body)


def checklist(items):
    """A print-and-tick list. No JS and no persistence on purpose: this page is meant to be
    printed or worked through beside a drafting document, and a checklist that silently
    forgets your ticks on reload would be worse than one that never claimed to remember."""
    lis = "".join('<li>%s</li>' % i for i in items)
    return '<ul class="gcl">%s</ul>' % lis


def table(headers, rows, caption=None, label=None):
    """A .table-scroll wrapper, made keyboard-reachable.

    On a phone some of these tables genuinely overflow, which turns the wrapper into a
    horizontal scroller. A scroll container that cannot be focused is unreachable for anyone
    driving the page from a keyboard, and axe flags it as scrollable-region-focusable. The
    site's other tables happen not to overflow at 390px, so they never needed this; two of
    the tables on this page do.

    tabindex="0" makes it focusable, and role="group" plus aria-label gives that focus stop a
    name so a screen reader says what was just entered rather than announcing an unlabelled
    group."""
    th = "".join("<th>%s</th>" % h for h in headers)
    trs = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    cap = '<p class="help">%s</p>' % caption if caption else ""
    name = label or ("Table: " + esc_attr(headers[0]))
    return ('<div class="table-scroll" tabindex="0" role="group" aria-label="%s">'
            '<table class="paths-table">'
            '<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>%s'
            % (esc_attr(name), th, trs, cap))


def esc_attr(t):
    """Strip tags and escape quotes, so a heading can be reused as an aria-label."""
    t = re.sub(r"<[^>]+>", "", str(t))
    return t.replace("&", "&amp;").replace('"', "&quot;")


P = lambda t: '<p class="paths-p">%s</p>' % t          # noqa: E731
H3 = lambda t: '<h3 class="paths-h3">%s</h3>' % t      # noqa: E731

# Frequently used links, written once.
PM_NIW = ('<a href="https://www.uscis.gov/policy-manual/volume-6-part-f-chapter-5" '
          'target="_blank" rel="noopener noreferrer">USCIS Policy Manual, Volume 6, Part F, '
          'Chapter 5</a>')
DHANASAR = ('<a href="https://www.justice.gov/media/871246/dl?inline" target="_blank" '
            'rel="noopener noreferrer"><em>Matter of Dhanasar</em></a>')
EB2_PAGE = ('<a href="https://www.uscis.gov/working-in-the-united-states/permanent-workers/'
            'employment-based-immigration-second-preference-eb-2" target="_blank" '
            'rel="noopener noreferrer">USCIS EB-2 page</a>')
G1055 = ('<a href="https://www.uscis.gov/g-1055" target="_blank" rel="noopener noreferrer">'
         'Form G-1055</a>')
I140 = ('<a href="https://www.uscis.gov/i-140" target="_blank" rel="noopener noreferrer">'
        'Form I-140</a>')
I907 = ('<a href="https://www.uscis.gov/i-907" target="_blank" rel="noopener noreferrer">'
        'Form I-907</a>')
I290B = ('<a href="https://www.uscis.gov/i-290b" target="_blank" rel="noopener noreferrer">'
         'Form I-290B</a>')
AILA = ('<a href="https://www.aila.org/" target="_blank" rel="noopener noreferrer">AILA</a>')
NOT_ADVICE = ('<p class="band-caveat">Information about a government process, not legal advice, '
              'and not a prediction about any individual case. Only a licensed immigration '
              'attorney who has read your evidence can advise you.</p>')

# The table of contents. Labels are 2 to 4 words, matching the other paths pages.
TOC = [
    ("g-start", "Start Here"),
    ("g-onething", "The One Mistake"),
    ("g-eb2", "Step 1: Qualify"),
    ("g-endeavor", "Step 2: The Endeavor"),
    ("g-prong1", "Step 3: Prong 1"),
    ("g-prong2", "Step 4: Prong 2"),
    ("g-prong3", "Step 5: Prong 3"),
    ("g-letters", "Step 6: Letters"),
    ("g-package", "Step 7: The Package"),
    ("g-file", "Step 8: Filing"),
    ("g-rfe", "Step 9: If An RFE"),
    ("g-denied", "Step 10: If Denied"),
    ("g-mistakes", "Mistakes That Lose"),
    ("g-help", "Getting Help"),
    ("g-checklist", "Full Checklist"),
    ("g-sources", "Sources And Limits"),
]


def toc_html():
    rows = "".join('<a href="#%s">%s</a>' % (i, t) for i, t in TOC)
    return ('<details class="paths-toc" open><summary>On this page</summary>'
            '<nav aria-label="On this page">%s</nav></details>' % rows)


# ---------------------------------------------------------------------------
# The content
# ---------------------------------------------------------------------------
def build():
    S = []

    # ---- 0. Start here -----------------------------------------------------
    body = (
        '<div class="kpi-row">'
        '<div class="kpi"><span class="kpi-label">You file</span>'
        '<span class="kpi-value">1 form</span>'
        '<span class="kpi-note">Form I-140, on your own behalf</span></div>'
        '<div class="kpi"><span class="kpi-label">Minimum government fee</span>'
        '<span class="kpi-value">$1,015</span>'
        '<span class="kpi-note">$965 if you file online. Attorney fees are separate</span></div>'
        '<div class="kpi"><span class="kpi-label">You must prove</span>'
        '<span class="kpi-value">2 things</span>'
        '<span class="kpi-note">EB-2 eligibility, then the waiver on three prongs</span></div>'
        '<div class="kpi"><span class="kpi-label">Hardest part</span>'
        '<span class="kpi-value kpi-warn">One paragraph</span>'
        '<span class="kpi-note">Describing your endeavor. Step 2 is the whole game</span></div>'
        '</div>'

        + P('A national interest waiver is not a separate visa. It is a request to skip two '
            'employer-driven steps in the EB-2 green card process: the job offer, and the '
            'labor-market test at the Department of Labor called PERM. If USCIS grants it, you '
            'file for yourself, you need no employer to sponsor you, and the petition belongs to '
            'you rather than to a job.')

        + P('That is the whole appeal of it, and it is why people self-petition. It is also why '
            'the bar is real: you are asking to be excused from a requirement that applies to '
            'almost everybody else, so the argument has to be about why your specific work is '
            'worth excusing, not about how accomplished you are.')

        + H3('How to use this page')
        + P('Work down it once in order, then come back to the step you are on. Each step tells '
            'you what to do, what evidence it needs, and the specific way people get it wrong. '
            'The detail sits in the expandable blocks, so you can read the spine first and go '
            'deeper only where you need to.')

        + note('What you should have by the end',
               P('A written endeavor paragraph you can defend. A list of the documents that '
                 'prove each of the three prongs separately. A filled Form I-140 with the right '
                 'fee and the two labor-certification pages most people miss. And a clear '
                 'answer on whether to do this yourself, pay for a review, or hire counsel.'),
               "good")

        + note('The honest framing, before you invest anything',
               P('Nobody publishes how often a national interest waiver is approved. USCIS does '
                 'not release approved petitions, so no NIW approval rate exists in any official '
                 'source, and anyone quoting one is quoting something else. What is public is '
                 'every appeal of a denial, which is what the statistics on this page come from. '
                 'They tell you how petitions FAIL, in the agency\'s own words. That is genuinely '
                 'useful for drafting, and it is not a forecast of your odds.') +
               P('So read the numbers here as a map of the traps, not as a probability.'),
               "warn")
        + NOT_ADVICE
    )
    S.append(section("g-start", "EB-2 NIW", "Start here", "What this is, what you file, and what "
                     "you will have by the end of the page.", body))

    # ---- 1. The one mistake ------------------------------------------------
    body = (
        P('If you take one thing from this page, take this. USCIS is not asking whether your '
          '<em>field</em> matters. It is asking whether the <em>specific thing you propose to '
          'do</em> matters. Almost everybody argues the first and thinks they have answered the '
          'second.')

        + '<div class="plain-explain"><div class="pe-label">The difference, in one line</div>'
          '<p>"Artificial intelligence is critical to American competitiveness" is a fact about a '
          'field. "I will continue developing a named method for detecting a named class of '
          'fault in power-grid sensors, which matters because grid operators currently cannot '
          'detect it before failure" is an endeavor. The first is a premise. The second is the '
          'claim you have to prove.</p></div>'

        + P('This is measurable in the record. Across the 3,331 dismissed EB-2 NIW appeals '
            'decided from 2017 onward, the Administrative Appeals Office had to write some '
            'version of "the relevant question is not the importance of the field, industry, or '
            'profession" in <strong>1,729 of them, 51.9%</strong>. In the 80 decisions it '
            'granted over the same period, that sentence appears in <strong>2</strong>, or 2.5%.')

        + table(["What the decision says", "Dismissed appeals", "Granted appeals"],
                [["not the importance of the industry, field, or profession", "51.9%", "2.5%"],
                 ["the <em>Dhanasar</em> teaching-activities analogy", "39.5%", "2.5%"],
                 ["impact must extend beyond your employer, clients or customers",
                  "22.5%", "2.5%"]],
                "Share of decisions containing each formulation at least once. Counted over the "
                "3,331 dismissed and 80 sustained NIW appeals decided on the merits from 2017 "
                "onward, which is when the current three-prong test took effect. A phrase count "
                "is a proxy: the sentence is partly a recital of the legal standard, so treat "
                "the dismissed column as an upper bound. The gap between the columns is the "
                "finding, and it is not subtle.", label="How refusals are worded, compared with decisions that were granted")

        + collapsible('Why the gap is the interesting part, and not the raw share',
                      P('Taken alone, "51.9% of losses contain this sentence" is weak evidence, '
                        'because the AAO recites the legal standard whether or not the petition '
                        'made that mistake. The reason to believe it is diagnostic is the other '
                        'column. If it were pure boilerplate it would appear at a similar rate '
                        'in the decisions that were granted. It appears in 2 of 80.') +
                      P('So the sentence is not filler. The AAO reaches for it when a petition '
                        'has proved that a field matters and has not separately proved that the '
                        'petitioner\'s own proposed work matters.'))

        + collapsible('The same error wearing three other hats',
                      P('It shows up against a consultant whose benefit stops at their clients, '
                        'against an employee whose benefit stops at their employer, and against '
                        'a business whose benefit stops at its customers. One decision puts it '
                        'flatly: benefits to a specific employer alone, even an employer with a '
                        'national footprint, are not relevant to whether the endeavor has '
                        'national importance.') +
                      P('It also shows up as the endeavor that is really just the current job. '
                        'Saying "my endeavor is separate from my role" does not make it '
                        'separate. In one decision the petitioner said exactly that, and also '
                        'said the current role was how the work would be advanced. The AAO held '
                        'the endeavor "effectively constitutes continuing to perform his current '
                        'job duties."'))
        + NOT_ADVICE
    )
    S.append(section("g-onething", "Read first", "The one mistake that decides most petitions",
                     "Your field is not your endeavor, and the difference is most of the "
                     "outcome.", body))

    # ---- 2. Step 1: EB-2 itself --------------------------------------------
    body = (
        P('Before any national-interest argument, you have to qualify for EB-2 on credentials '
          'alone. This is a separate test with its own evidence, and it is where roughly one in '
          'five losing appeals dies. <strong>664 of 3,633 dismissed appeals, 18.3%</strong>, '
          'contain an adverse finding on this threshold question.')

        + P('There are two doors. You only need one.')

        + H3('Door A: advanced degree professional')
        + P('The common route. You need an official academic record showing a degree above a '
            'bachelor\'s, or a bachelor\'s plus five years of progressive post-baccalaureate '
            'experience in the specialty, evidenced by letters from current or former employers. '
            'The regulation treats bachelor\'s plus five years as equivalent to a master\'s.')
        + note('If you are using the five-years route, start the letters now',
               P('Those employer letters are mandatory evidence, not optional colour. Former '
                 'employers are slow, reorganised, or gone. This is the single most common '
                 'reason a filing slips by months, and it is entirely a scheduling problem '
                 'rather than a legal one.'), "warn")

        + H3('Door B: exceptional ability')
        + P('Exceptional ability means expertise significantly above what is ordinarily '
            'encountered in the sciences, arts or business. You must document at least three of '
            'six categories: a relevant academic record, ten years of full-time experience '
            'evidenced by employer letters, a licence or certification, a salary demonstrating '
            'exceptional ability, membership of professional associations, or recognition for '
            'achievements from peers, government or professional organisations.')

        + collapsible('Two traps inside Door B that are not on the face of the rule',
                      P('<strong>Meeting three categories is not the end.</strong> It is the '
                        'entry requirement. USCIS then makes a separate final merits '
                        'determination on whether your expertise really is significantly above '
                        'the ordinary. Appeals that argue only about the three categories and '
                        'never address the final determination lose on that alone.') +
                      P('<strong>"Professional association" is a defined term.</strong> Because '
                        'the regulation defines a profession as an occupation needing at least a '
                        'US bachelor\'s degree to enter, an association only counts if it '
                        'requires its members to belong to a profession so defined. A trade body '
                        'with no degree requirement does not qualify. In one decision the '
                        'service center granted this criterion and the AAO took it away on its '
                        'own review.'))

        + note('Do not treat this step as a formality',
               P('It is a documents exercise, so it feels administrative next to the interesting '
                 'argument. But no amount of national-interest writing repairs a gap here, and '
                 'an adjudicator who finds one may never reach your endeavor at all. If you are '
                 'using a foreign degree, the credential evaluation has to be finished before '
                 'you file, not pending.'), "warn")

        + checklist([
            "Highest degree certificate, plus the official transcript or academic record.",
            "Credential evaluation establishing US equivalency, if the degree is foreign. "
            "Complete, not pending, on the day you file.",
            "Certified English translation behind every document not in English.",
            "If using bachelor's plus five years: a letter from each employer, on letterhead, "
            "signed, stating dates, titles, duties, and enough detail to show the experience was "
            "progressive and after the bachelor's.",
            "If using Door B: documentation for at least three of the six categories, plus an "
            "argument on the final merits determination.",
        ])
        + NOT_ADVICE
    )
    S.append(section("g-eb2", "Step 1", "Confirm you qualify for EB-2",
                     "A credentials test with its own evidence, separate from the waiver. "
                     "18.3% of losing appeals fail here.", body))

    # ---- 3. Step 2: the endeavor -------------------------------------------
    body = (
        P('Write one paragraph describing what you propose to do. Everything else in the '
          'petition is evidence for or about that paragraph, so it is worth more of your time '
          'than any other page you will write. Expect to rewrite it many times.')

        + H3('The test it has to pass')
        + P('The Policy Manual says the endeavor is "more specific than the general occupation", '
            'and that you should describe not what your occupation normally involves but what '
            'work you propose to undertake specifically within it. Its own example: engineering '
            'is an occupation; the specific projects, goals or areas of engineering are the '
            'endeavor.')
        + '<div class="plain-explain"><div class="pe-label">A blunt working test</div>'
          '<p>If your endeavor statement would fit on any qualified person\'s r&eacute;sum&eacute; '
          'in your field, you have written an occupation. Rewrite it until it could only '
          'describe your work.</p></div>'

        + H3('The shape that appears in the decisions that were granted')
        + P('A narrow, nameable thing paired with a broad consequence. A named technique, method, '
            'problem or system, then what solving it changes for people who are not you or your '
            'employer. The verb in almost every granted endeavor description is "continue", '
            'because these are ongoing lines of work rather than aspirations.')

        + collapsible('Both extremes of scope hurt, and they hurt differently',
                      P('<strong>Too broad</strong> and it collapses into "my field is '
                        'important", which is the failure in the section above. Too broad also '
                        'invites the AAO to split your endeavor in half, find one half not '
                        'nationally important, and narrow its analysis to the rest. It has done '
                        'that while reversing a favourable finding.') +
                      P('<strong>Too narrow</strong> and your own track record stops matching. In '
                        'one dismissal the petitioner defined the endeavor tightly around a '
                        'specific industrial process, and the AAO then found that none of the '
                        'publications, citations or letters addressed it. Every factor failed at '
                        'once, purely because of how the endeavor had been defined.'))

        + collapsible('Geography is not the test',
                      P('"National" does not mean geographically national. One decision states '
                        'it better than the rest: broader implications "can reach beyond a '
                        'particular proposed endeavor\'s geographical locus and focus", and the '
                        'real question is whether the implications "apply beyond just narrowly '
                        'conferring the proposed endeavor\'s benefit".') +
                      P('Locally executed work can qualify. Among the decisions granted, one '
                        'concerned schools in a single US commonwealth and another concerned one '
                        'state\'s agricultural industry.'))

        + note('Once you file, this paragraph is frozen',
               P('Eligibility is fixed as of the filing date. If you later describe a different '
                 'endeavor, the change itself becomes a reason to refuse. This is the most '
                 'purely avoidable loss in the whole corpus and it usually happens in the reply '
                 'to a request for evidence. Step 9 covers how to avoid it.'), "warn")
        + NOT_ADVICE
    )
    S.append(section("g-endeavor", "Step 2", "Write the endeavor in one paragraph",
                     "The highest-leverage page in the petition, and the one most people "
                     "under-write.", body))

    # ---- 4. Step 3: prong 1 ------------------------------------------------
    body = (
        P('Prong 1 asks two things: does the endeavor have substantial merit, and does it have '
          'national importance. Merit is rarely the fight. National importance almost always is.')

        + P('The evidence for this prong is about the WORK, not about you. Your degrees, awards, '
            'citations and career belong to Step 4. The AAO says so directly: education and '
            'prior experience are material to the second prong and "immaterial" to the first.')

        + H3('What carried the decisions that were granted')
        + checklist([
            "A named, specific technique or problem, framed as ongoing work.",
            "An authoritative third-party document that names that specific technology or "
            "problem. This is the exhibit that did the most work: a federal critical-technology "
            "list, a named statute, a named federal research programme, an agency initiative.",
            "Dissemination as the stated mechanism of broad impact. Publication and conference "
            "presentation is the bridge the AAO repeatedly uses to get from meritorious work to "
            "broader implications. No commercialisation or measured downstream effect is needed.",
            "Government funding of the actual work, where it exists.",
        ])

        + H3('What was not enough, however much of it there was')
        + collapsible('Field-level evidence, executive orders, market size, industry reports',
                      P('Disposed of with one move: they do not mention you or your proposed '
                        'endeavor. Aggregating more of it does not help. One decision said that '
                        'even considered "collectively and in the totality of circumstances", '
                        'field-level material did not support a finding about a specific '
                        'endeavor.'))
        + collapsible('Being in a critical and emerging technology area',
                      P('Widely misunderstood. It is credited as a positive factor and then held '
                        'insufficient on its own. The Policy Manual\'s own caveat gets quoted '
                        'back: in all cases the evidence must show that a STEM endeavor has both '
                        'substantial merit and national importance.'))
        + collapsible('Two arguments that are category errors, and lose on sight',
                      P('<strong>"My endeavor does not hurt US workers."</strong> Whether an '
                        'endeavor adversely affects US workers is not a factor in national '
                        'importance at all.') +
                      P('<strong>"There is a shortage in my occupation."</strong> Rejected, and '
                        'worth understanding why: shortages "are directly addressed by the U.S. '
                        'Department of Labor through the labor certification process". Arguing a '
                        'shortage is arguing for the very process you are asking to skip. It '
                        'appears in 325 dismissed appeals.'))
        + collapsible('Small employment and revenue numbers, and projections with no method',
                      P('Concrete figures held insufficient across the losses included one to '
                        'four employees, six employees, and eight growing to thirty-two. The '
                        'objection was usually about method as much as scale: where does the '
                        'number come from, and why does an industry multiplier apply to this '
                        'venture. 380 dismissed appeals contain a finding that a business plan '
                        'was speculative or unexplained.') +
                      P('Worth knowing in the other direction: job creation and economic effect '
                        'are examples of national importance, not requirements. The AAO has '
                        'corrected a service center for treating them as required.'))
        + NOT_ADVICE
    )
    S.append(section("g-prong1", "Step 3", "Prove prong 1 with third-party evidence",
                     "Substantial merit and national importance. This prong is about the work, "
                     "and your CV does not belong in it.", body))

    # ---- 5. Step 4: prong 2 ------------------------------------------------
    body = (
        P('Prong 2 shifts to you: are you well positioned to advance this endeavor. Note the '
          'wording. You do not have to show the endeavor is likely to succeed. You have to show '
          'you are positioned to advance it.')

        + P('Map every piece of evidence here to the endeavor rather than presenting a general '
            'career narrative. A career narrative is the structural cause of the prong 1 and '
            'prong 2 mix-up that appears in 893 dismissed appeals.')

        + H3('The inventory that recurs in the decisions that were granted')
        + checklist([
            "CV and academic records.",
            "Published and presented work, and peer-review activity.",
            "Citation evidence framed as a RATE relative to others in the field, and by "
            "independent researchers. Absolute counts barely appear on the winning side.",
            "Reference letters describing expertise and a record of success. See Step 6.",
            "Grants and funding, especially government, that were genuinely yours.",
            "A plan for future activities, PAIRED with evidence of progress already made.",
        ])

        + note('Plan plus progress, never plan alone',
               P('Every plan-based finding in the decisions granted is paired with something '
                 'already done: an accepted offer, a funded grant, a current position that '
                 'supports the work, a published first-authored paper on exactly that topic. A '
                 'plan on its own reads as an intention.'), "good")

        + H3('The part that surprises people: citations')
        + P('A great deal of petition-drafting advice points at bibliometrics. The AAO\'s '
            'reasoning points the other way, and it is worth reading before you build a petition '
            'on citation counts.')
        + collapsible('What the AAO actually says about citation counts, in its own words',
                      P('That a count is the wrong kind of fact: "citation frequency, which may '
                        'include self-citations, is quantitative in nature and does not reveal '
                        'the reasons for the citations, which involve a qualitative analysis."') +
                      P('That journal prestige is not a proxy: a high journal ranking or impact '
                        'factor "is reflective of the publication\'s overall citation rate" and '
                        'does not show the influence of any particular author.') +
                      P('And the line almost nobody expects, which appears in multiple '
                        'decisions: "our determination that he was well positioned under the '
                        'second prong was not based on his citation record." The AAO\'s account '
                        'of what the governing precedent\'s prong 2 finding rested on is '
                        'education, experience and expertise, the significance of the '
                        'petitioner\'s role in research projects, and sustained government '
                        'interest and funding. Not citations.') +
                      P('What it does want instead, from the Policy Manual: excerpts of '
                        'published articles showing "positive discourse around, or adoption of, '
                        'the person\'s work." Adoption, not arithmetic.'))

        + collapsible('Four other things that are weaker than they look',
                      P('<strong>A doctorate on its own.</strong> Credited as a positive factor, '
                        'then: "a degree in and of itself, is not a basis to determine that a '
                        'person is well positioned." Several petitioners who won had only a '
                        'master\'s, and several had a doctorate still in progress at filing.') +
                      P('<strong>Being a productive researcher.</strong> The most repeated '
                        'adverse sentence in the corpus is that not every individual who has '
                        'performed original research will be found well positioned, because the '
                        'waiver "is an additional benefit, not provided to every member of the '
                        'professions holding an advanced degree who applies."') +
                      P('<strong>Peer review service.</strong> Treated as a common activity among '
                        'researchers. A real positive factor, never a strong one.') +
                      P('<strong>Grant funding that was not yours.</strong> Repeatedly rejected '
                        'where the grant went to the employer, the institution or the supervising '
                        'professor. Being one of several listed key personnel was not enough. '
                        'Describing funding accurately is safer than overstating it.'))

        + note('The job-offer trap, which catches careful readers',
               P('No job offer is required, and its absence is not held against you. But if your '
                 'stated plan is "I will do this as a researcher at X", you have made an offer '
                 'functionally necessary by your own description, and having no documented steps '
                 'toward it then defeats this prong. Several losses turn on exactly that.') +
               P('Petitioners who avoided it either had a documented offer or current position '
                 'supporting the work, or framed the endeavor as employer-independent. One '
                 'described it as a career-long research goal that would not change with a change '
                 'of employer.'), "warn")
        + NOT_ADVICE
    )
    S.append(section("g-prong2", "Step 4", "Prove prong 2 with your own record",
                     "Well positioned to advance the endeavor. Mapped to the endeavor, not "
                     "presented as a career story.", body))

    # ---- 6. Step 5: prong 3 ------------------------------------------------
    body = (
        P('Prong 3 asks whether, on balance, it benefits the United States to waive the job offer '
          'and the labor certification. Give it its own heading and its own exhibits. Restating '
          'prongs 1 and 2 here is a recognised way to lose it: the AAO\'s answer is that those '
          'factors "relate to the first two <em>Dhanasar</em> prongs" and do not address the '
          'separate third prong.')

        + P('The factors, from the governing precedent and the Policy Manual, are examples rather '
            'than a checklist: whether it would be impractical to obtain a labor certification '
            'given your qualifications or the endeavor; the benefit to the United States from '
            'your contributions even if other qualified US workers were available; whether the '
            'national interest is sufficiently urgent to warrant forgoing the process; whether '
            'the process might prevent an employer hiring someone whose skills exceed the '
            'minimum for the occupation; economic impact; job creation.')

        + note('One factor carries almost every decision that was granted',
               P('Benefit even assuming other qualified US workers are available. The closing '
                 'sentence in most of the wins is a near-template: the petitioner offers '
                 'contributions of such value that, on balance, they would benefit the United '
                 'States even assuming other qualified US workers are available. The stated '
                 'inputs are consistently the degree, the field-level benefits of progress in '
                 'the area, and the documented past record.'), "good")

        + collapsible('One thing a letter can say here that almost never gets said',
                      P('In a handful of decisions that were granted, the AAO relied on letters '
                        'that "provide a reasoned analysis of why the labor certification process '
                        'is not well suited for discovering highly skilled scientists and '
                        'researchers." That is a specific, available argument about the PROCESS '
                        'rather than about you, and most letters never touch it.'))

        + collapsible('Two arguments that fail here specifically',
                      P('<strong>Urgency, argued thinly.</strong> This prong is a near-miss '
                        'factory. In one dismissal the AAO accepted that the endeavor was '
                        'nationally important and still held the record did not establish that '
                        'the interest "is so urgent that it warrants forgoing the labor '
                        'certification process". The gap it named was that the letters never said '
                        'the interest could not wait.') +
                      P('<strong>"My position is temporary, so certification is impractical."</strong> '
                        'Rejected with reasoning worth reading in full: the student and '
                        'postdoctoral classifications exist precisely so that people can study '
                        'and train temporarily, so the temporary nature of that training is not '
                        'itself an argument for permanent immigration benefits.'))

        + note('You will often never find out what the officer thought of this prong',
               P('Because all three prongs must be met, failing one ends the petition, so the AAO '
                 'usually stops at the first failure and says so. Depending on how you count the '
                 'phrasing, between 1,039 and 3,140 of the 3,633 dismissals signal that at least '
                 'one prong was never decided. Silence about prongs 2 and 3 is not approval of '
                 'them, and rebuilding a petition on that assumption is a real risk.'), "warn")
        + NOT_ADVICE
    )
    S.append(section("g-prong3", "Step 5", "Show why waiving the job offer benefits the US",
                     "Prong 3 asks a different question from the first two: not whether your "
                     "work matters, but whether it is worth letting you skip the job offer and "
                     "the labor-market test that everyone else has to go through. Restating "
                     "prongs 1 and 2 here is a recognised way to lose it.", body))

    # ---- 7. Step 6: letters ------------------------------------------------
    body = (
        P('Letters are the slowest thing to obtain and the easiest to get wrong. Start months '
          'before you intend to file. You cannot reliably obtain a new independent letter inside '
          'the window you get to answer a request for evidence.')

        + P('The AAO applies one test to every letter: does it give a specific, concrete example '
            'of how your work changed what somebody else did. 547 dismissed appeals contain a '
            'finding that letters were conclusory, general, or failed to explain the point at '
            'issue.')

        + H3('The squeeze, and how the winning letters escaped it')
        + P('There is a genuine bind here. An insider knows your work but is not independent. A '
            'stranger is independent but has only read your CV. Letters from collaborators, '
            'advisors and colleagues were held to prove only internal use. Independent letters '
            'failed the other way, with the AAO noting that the writers gave no indication of '
            'personal knowledge of the work beyond a citation history.')
        + note('What the letters in the granted decisions did differently',
               P('They were written by people who were not collaborators and who described '
                 '<strong>their own use</strong> of the work. Decisions quote authors saying '
                 'their own group\'s published paper was built on the petitioner\'s method, or '
                 'that they modified their own protocols, or that they used the petitioner\'s '
                 'algorithm as the mathematical basis for their own design.') +
               P('That is the brief to give a recommender: not "please say I am excellent", but '
                 '"please describe what you did differently because of this work".'), "good")

        + collapsible('Superlatives are treated as worthless',
                      P('Phrases the AAO has quoted back and rejected as unexplained include '
                        '"significantly advanced the field", "groundbreaking, setting a new '
                        'standard", and "revolutionized the field". The stock finding is that the '
                        'author "does not elaborate", "does not offer specific examples", or '
                        '"does not explain what findings he relied upon".') +
                      P('The register the AAO praises in the wins is oddly specific: letters '
                        'describing the work and the proposed endeavor "in personalized and '
                        'meaningful detail".'))

        + collapsible('Independence is a weighting factor, not a bar',
                      P('One decision that was granted included a letter from the petitioner\'s '
                        'own former doctoral advisor, and still succeeded, because the letters '
                        'sat alongside independent corroboration: third-party government policy '
                        'documents and citation rankings. The letters were not carrying the '
                        'weight alone.') +
                      P('So do not discard an insider letter. Label it honestly, and make sure '
                        'something that is not a letter corroborates the same proposition.'))

        + checklist([
            "For each letter, write down the one factual proposition it is offered to prove.",
            "Then ask what corroborates that proposition if the letter did not exist. If the "
            "answer is nothing, the letter is carrying too much.",
            "Ask independent recommenders for a description of their own use of your work.",
            "Keep independent letters clearly distinguished from employer and collaborator "
            "letters. Do not blur the two.",
            "Consider one letter that addresses why the labor certification process is poorly "
            "suited to finding people who do this kind of work. It speaks to prong 3.",
        ])
        + NOT_ADVICE
    )
    S.append(section("g-letters", "Step 6", "Get letters that answer the legal question",
                     "The slowest item to obtain, and the one most often wasted on praise.",
                     body))

    # ---- 8. Step 7: the package -------------------------------------------
    body = (
        note('The requirement almost every self-petitioner misses',
             P('A national interest waiver removes PERM and the Department of Labor '
               'certification. It does not remove the labor certification FORM. USCIS states '
               'that a national interest waiver petition "must be accompanied by a completed '
               'Form ETA-9089, Appendix A" and "a signed Form ETA-9089, Final Determination", '
               'uncertified, filed straight to USCIS. The requirement arrived in January 2025.') +
             P('This is not a technicality. 115 dismissed appeals cite the regulation on it, and '
               'in one the AAO wrote that for this reason alone the petition was not approvable.') +
             P('Do not look for it in the Form I-140 instructions. Those are edition 06/07/24 and '
               'predate the requirement by seven months, so they never mention Appendix A or the '
               'Final Determination at all. That is not a contradiction, just an older document. '
               'The current ' + EB2_PAGE + ' states the requirement twice, and the January 2025 '
               'Federal Register notice is where it comes from.'), "warn")

        + collapsible('Exactly what to sign, and the one place the two agencies differ',
                      P('The Final Determination is a two-page document and the signature goes on '
                        'the second page. DOL\'s own note on the form says: sign and submit "a '
                        'fully executed copy of page 2 along with Form ETA-9089 and the '
                        'appropriate appendices", and that the Final Determination is for '
                        'submission "ONLY when submitting Form I-140 to USCIS in support of a '
                        'Schedule A or National Interest Waiver".') +
                      P('That is worded more broadly than USCIS\'s own list, which names Appendix '
                        'A and the signed Final Determination and stops there. Appendix A is '
                        'Foreign Worker Information, and it is the only one of the four appendices '
                        'that fits a self-petition: B is additional worksite information, C is '
                        'supplemental information, and D is special recruitment for college and '
                        'university teachers.') +
                      P('USCIS receives the filing, so its list is the one that governs. Including '
                        'the base Form ETA-9089 as well costs nothing and satisfies the broader '
                        'wording, which is what a cautious filing does when two agencies describe '
                        'the same package differently.'))

        + H3('What goes in the envelope')
        + checklist([
            "Form I-140, current edition, signed, every page from the same edition.",
            "Form ETA-9089 Appendix A, completed, and a signed Final Determination page. "
            "Uncertified is correct here.",
            "The filing fee, plus the Asylum Program Fee as a separate payment. See Step 8.",
            "Form I-907 and its fee, if you are using premium processing.",
            "A petition letter that walks through EB-2 eligibility first, then prong 1, then "
            "prong 2, then prong 3, citing exhibits by number.",
            "One numbered exhibit per document, sequential, no sub-lettering.",
            "An exhibit index at the front: number, title, what it proves. Build it last.",
            "A certified English translation behind every non-English document, under the same "
            "exhibit number.",
            "A complete copy of everything, kept by you, and tracked delivery with the number "
            "recorded.",
        ])

        + note('Structure is not decoration',
               P('An adjudicator who cannot find the evidence you cited has effectively not '
                 'received it. Organise the letter by the four questions in order, because that '
                 'is the order the decision will be written in. A petition organised as a career '
                 'narrative produces the prong 1 and prong 2 mix-up automatically.'), "good")

        + collapsible('Three filing-mechanics failures that are rare and absolute',
                      P('<strong>Missing certified translations.</strong> A foreign-language '
                        'document without a full certified English translation is not evidence. '
                        '56 dismissed appeals cite the rule.') +
                      P('<strong>A defective representation form.</strong> In one case an appeal '
                        'filed on a Form G-28 bearing "/S/" instead of the petitioner\'s '
                        'signature was summarily dismissed as improperly filed. The merits were '
                        'never reached.') +
                      P('<strong>Paying the wrong fee.</strong> An incorrect fee gets the package '
                        'rejected rather than corrected, and a rejection loses your filing date. '
                        'In one motion decision a fee error pushed a refiling past its deadline '
                        'and it was dismissed as untimely, with no discretion available.'))
        + NOT_ADVICE
    )
    S.append(section("g-package", "Step 7", "Assemble the package",
                     "Including the two labor-certification pages that most self-petitioners do "
                     "not know they need.", body))

    # ---- 9. Step 8: filing -------------------------------------------------
    body = (
        H3('Government fees')
        + table(["What you pay", "Amount", "Notes"],
                [[I140 + " filing fee",
                  '<span data-fee="i140Paper">$715</span> by mail, '
                  '<span data-fee="i140Online">$665</span> online',
                  "Filing online saves $50."],
                 ["Asylum Program Fee",
                  '<span data-fee="asylumProgramFeeSelf">$300</span>',
                  "Due WITH the I-140 and not part of it. $300 is the rate for a "
                  "self-petitioner. $600 if an employer files as a regular petitioner, $0 for a "
                  "nonprofit. Paying $600 is an overpayment; paying nothing is a rejection."],
                 ["<strong>Minimum to file</strong>",
                  "<strong>$1,015 by mail, $965 online</strong>",
                  "The two rows above, together."],
                 [I907 + " premium processing",
                  '<span data-fee="i907Premium">$2,965</span>',
                  "Optional. Paid separately from the filing fee, and not waivable."],
                 ["Form I-485, later",
                  '<span data-fee="i485Paper">$1,440</span> by mail, '
                  '<span data-fee="i485Online">$1,390</span> online',
                  "Only once a visa number is available to you. Applicant over 14."]],
                "From " + G1055 + ", the official USCIS fee schedule, Edition 05/29/26. Fees "
                "change. Read the schedule on the day you file rather than trusting any table, "
                "including this one.", label="Government fees for an EB-2 NIW self-petition")

        + H3('Premium processing, and the number that is usually quoted wrongly')
        + note('For a national interest waiver it is 45 business days, not 15',
               P('Three official sources say so, and they agree. The regulation sets a separate '
                 'timeframe per classification, and the two EB-2 entries sit next to each other: '
                 'ordinary EB-2 with a labor certification is 15 business days, and EB-2 '
                 'involving a waiver, which is this, is 45. The USCIS premium processing page '
                 'splits it the same way. So does the table in the Form I-907 instructions, '
                 'which lists "EB-2 (E21 non-NIW)" at 15 days and "EB-1 (E13) or EB-2 (E21 NIW)" '
                 'at 45. The widely quoted 15 days is a real number that belongs to the other '
                 'EB-2.') +
               P('A business day excludes weekends and federal holidays, so 45 of them is '
                 'roughly nine to ten calendar weeks. The fee is the same either way.'), "warn")

        + note('You may file it yourself on a self-petition',
               P('This looks contradictory in the sources and is not. The fee schedule and the '
                 'Form I-907 instructions both say the form "may not be filed by a beneficiary '
                 'or co-applicant of the primary form". But the operative test in the same '
                 'instructions is different: "You, or your attorney or accredited '
                 'representative, may request Premium Processing Service <strong>only if you '
                 'filed the corresponding immigration benefit request</strong>."') +
               P('On a national interest waiver you did file it. The Form I-140 instructions say '
                 'so in terms, listing who may file that petition: "any employer, individual, or '
                 'third party may file this petition, <strong>including the petition\'s '
                 'beneficiary</strong>", for extraordinary ability or for a national interest '
                 'waiver. So you are the petitioner, and the bar on beneficiaries is aimed at '
                 'the ordinary case where somebody else filed and the beneficiary tries to '
                 'upgrade it.') +
               P('USCIS says the same thing directly. Asked whether a beneficiary may request '
                 'premium processing, its premium processing page answers "No, except in cases '
                 'where the petitioner is eligible to file a self-petition", where the petitioner '
                 'and the beneficiary are the same person. Note the narrower point in the same '
                 'place: the beneficiary cannot sign or file the form in the ordinary case, but '
                 'anyone, including the beneficiary, may pay the fee.'), "good")
        + collapsible('Three mechanics that change what premium processing actually buys',
                      P('<strong>The clock may not start on delivery.</strong> For the 45-day '
                        'tier the regulation starts it only when all prerequisites, the form and '
                        'the fees have been received. Paying for speed does not buy speed on an '
                        'incomplete filing.') +
                      P('<strong>A request for evidence resets it to zero.</strong> Not a pause. '
                        'A fresh 45 business days from the date your response is received.') +
                      P('<strong>A request for evidence counts as USCIS meeting the deadline.</strong> '
                        'An approval, a denial, a notice of intent to deny, or a request for '
                        'evidence all satisfy the window. So premium processing buys a fast first '
                        'look, not a fast outcome, and never a better outcome.'))

        + H3('What approval actually gets you')
        + P('A priority date, which is a place in a queue, not a green card. For a national '
            'interest waiver the priority date is the day you properly filed the I-140 with all '
            'initial evidence and the correct fee.')
        + note('Nothing in your petition affects how long the queue is',
               P('The wait is set by annual statutory caps, total demand, and your country of '
                 'birth, through the monthly Visa Bulletin. A brilliant petition and a barely '
                 'adequate one, filed the same day by two people born in the same country, wait '
                 'exactly as long. Plan around that rather than against it, and see the '
                 '<a href="tools.html#tools-history">history and trends charts</a> for how the '
                 'lines have actually moved.'), "good")
        + NOT_ADVICE
    )
    S.append(section("g-file", "Step 8", "File it, and decide on premium processing",
                     "What it costs, what the 45-day figure really is, and what approval does "
                     "and does not give you.", body))

    # ---- 10. Step 9: RFE ---------------------------------------------------
    body = (
        P('A request for evidence is not a denial. It means the record does not yet establish '
          'eligibility and USCIS is giving you a chance to complete it. Roughly half the '
          'decisions in the corpus mention one, so it is ordinary rather than ominous.')

        + P('A notice of intent to deny is a different and more serious document. It means the '
            'officer has already formed an adverse view and is telling you what it is. It is the '
            'more informative notice and it gives you less time.')

        + table(["Notice", "Time to respond", "What it means"],
                [["Request for evidence",
                  "84 days, up to 12 weeks, plus 3 if mailed. <strong>No extensions are "
                  "permitted.</strong>",
                  "The record is incomplete."],
                 ["Notice of intent to deny", "30 days, plus 3 if mailed.",
                  "The officer intends to refuse and has told you the reasoning."]],
                "Response windows from the USCIS Policy Manual. Officers are prohibited by "
                "regulation from granting more time on a request for evidence, so the date on "
                "the notice is the date.", label="Request for evidence compared with notice of intent to deny")

        + note('The single most avoidable loss in the corpus happens here',
               P('The filing describes one endeavor. The request for evidence asks for proof of '
                 'national importance. The reply reaches for something stronger and, in '
                 'reaching, describes a <strong>different</strong> endeavor. The change itself '
                 'then becomes the reason to refuse. In one decision the filing said the plan '
                 'was to work for US companies in the field and the reply said the plan was to '
                 'open and operate a company; the AAO declined to consider the changed endeavor '
                 'at all, and the business plan and formation documents submitted to save the '
                 'petition all post-dated the filing.') +
               P('If the endeavor as filed is not the endeavor you can prove, the answer is a new '
                 'petition, not a redescription. 504 dismissed appeals cite the authorities on '
                 'this.'), "warn")

        + collapsible('Answer it completely, and in one submission',
                      P('A partial response is treated as a request for a decision on the record '
                        'as it stands, and USCIS will not send a second notice. Withholding '
                        'evidence that precludes a material line of inquiry is itself a ground '
                        'for refusal.') +
                      P('There is also now authority letting an adjudicator refuse evidence '
                        'produced for the first time on appeal where you were already put on '
                        'notice of the gap, usually by the request for evidence itself. The '
                        'citation count is still small, so treat the trend as worth watching '
                        'rather than settled. Either way, the request for evidence is the last '
                        'full opportunity, not a preliminary round.'))

        + collapsible('What you may and may not add',
                      P('Your response can only prove eligibility as it stood on the filing date. '
                        'A degree finished afterwards cannot rescue the petition, and neither can '
                        'a fifth year of experience completed afterwards.') +
                      P('New citations to work that was already published are a different matter, '
                        'because the work existed on the filing date. The distinction the '
                        'decisions draw is between new facts creating eligibility, which is '
                        'excluded, and progress on the endeavor you already described, which is '
                        'credited.'))
        + NOT_ADVICE
    )
    S.append(section("g-rfe", "Step 9", "If a request for evidence arrives",
                     "Ordinary, answerable, and the place where the most avoidable loss in the "
                     "record happens.", body))

    # ---- 11. Step 10: denied -----------------------------------------------
    body = (
        P('You have three options: appeal, file a fresh petition, or stop. The published record '
          'is unusually clear about the first one, and it is worth looking at before you spend '
          'money on it.')

        + table(["Outcome of an appeal", "Count", "Share"],
                [["Dismissed", "3,633", "86.6%"],
                 ["Remanded, which is <strong>not</strong> a win", "428", "10.2%"],
                 ["Sustained", "135", "3.2%"]],
                "Of the 4,196 appeals decided on the merits in this corpus, 2015 to 2026. "
                "Motions to reopen or reconsider are a different and harder posture: 6 granted "
                "of 714. These are shares of appealed denials, not of petitions, and they are "
                "not an approval rate.", label="Outcomes of EB-2 NIW appeals decided on the merits")

        + note('And the recent rate is lower than the overall figure suggests',
               P('The sustained share was 14.3% across 2015 to 2020, on 426 decisions. Across '
                 '2023 to 2026 it is 1.7%, on 3,233. The early counts are small and the recent '
                 'ones are not, so the number to plan against is the recent one. Why it fell is '
                 'not established by this data, and should not be guessed at.'), "warn")

        + H3('The distinction that actually decides it')
        + '<div class="plain-explain"><div class="pe-label">One sentence</div>'
          '<p>Appealing is a bet on the record you already filed. Refiling is a bet on a record '
          'you can still change.</p></div>'
        + P('Two features of the process make the first bet unattractive. Eligibility is fixed at '
            'the filing date, so an appeal cannot be improved by anything that happened since. '
            'And review starts afresh, so the appeal body can find grounds the original refusal '
            'never raised, and can withdraw a finding that had gone your way. 269 dismissals '
            'record it withdrawing one of the service center\'s determinations.')

        + note('When an appeal is genuinely the right tool',
               P('When your complaint is about the DECISION rather than about the evidence. The '
                 'decision did not explain itself. It analysed the wrong endeavor, the wrong '
                 'occupation, or the wrong field. It imported prong 2 factors into the prong 1 '
                 'analysis. It made a finding that contradicts a document in the record.') +
               P('That is what the great majority of the 428 remands are about, and it is what '
                 'the rules require you to identify: a specific erroneous conclusion of law or '
                 'statement of fact. Where the honest description of your position is "the '
                 'evidence was stronger than the officer thought", 439 dismissals show what '
                 'happens to that argument.'), "good")

        + collapsible('What a remand is, since it is the realistic good outcome',
                      P('The earlier decision is withdrawn and the service center has to decide '
                        'the case again. No visa is granted and no eligibility is established. '
                        'Remands here are overwhelmingly about the adjudicator\'s failure to '
                        'explain rather than about your evidence being sufficient.') +
                      P('It can also produce a fresh request for evidence, and 120 remands '
                        'contain the AAO expressly saying it expresses no opinion on the ultimate '
                        'resolution. That sentence appears in zero dismissals. It exists '
                        'specifically to stop people reading a remand as a win.'))

        + collapsible('Deadlines and the fee, if you do appeal',
                      P('It is filed on ' + I290B + '. The deadline is 30 calendar days after '
                        'service of the decision, or 33 if USCIS mailed it. Service by mail is '
                        'complete on the date of mailing, not the date you receive it, and the '
                        'filing date is the date USCIS receives it, not the date you post it.') +
                      P('There is no extension of the appeal deadline itself. The fee is $800. A '
                        'late appeal must be rejected as improperly filed and retains no filing '
                        'date. A motion to reopen or reconsider carries the same 30 or 33 day '
                        'deadline, and its brief and evidence must be filed with it rather than '
                        'later.'))

        + note('One consideration this page cannot help you with',
               P('An unfavourable decision can have consequences for your lawful status, and '
                 'filing a motion does not postpone the decision\'s effect. Nothing in this '
                 'corpus tells you how that should weigh against the merits of appealing. That '
                 'is exactly the question to take to a licensed immigration attorney rather than '
                 'to a statistics page.'), "warn")
        + NOT_ADVICE
    )
    S.append(section("g-denied", "Step 10", "If it is denied: appeal, refile, or stop",
                     "What the published record supports, and the one distinction that decides "
                     "it.", body))

    # ---- 12. The mistakes --------------------------------------------------
    body = (
        P('Ranked by how often the relevant language appears in the 3,633 dismissed appeals. '
          'Read this as a list of things to check your draft against.')

        + table(["#", "The mistake", "Dismissed appeals", "Fixed in"],
                [["1", "Argued the field mattered rather than the specific endeavor",
                  "1,729 (47.6%)", '<a href="#g-onething">The one mistake</a>'],
                 ["2", "Offered credentials as proof of the endeavor's national importance",
                  "893 (24.6%)", '<a href="#g-prong1">Step 3</a>'],
                 ["3", "Never established the underlying EB-2 classification",
                  "664 (18.3%)", '<a href="#g-eb2">Step 1</a>'],
                 ["4", "Described the endeavor too vaguely", "566 (15.6%)",
                  '<a href="#g-endeavor">Step 2</a>'],
                 ["5", "Letters that praised the person instead of answering the question",
                  "547 (15.1%)", '<a href="#g-letters">Step 6</a>'],
                 ["6", "Changed or added to the endeavor after filing", "504 (13.9%)",
                  '<a href="#g-rfe">Step 9</a>'],
                 ["7", "Appealed without engaging the actual grounds of refusal", "439 (12.1%)",
                  '<a href="#g-denied">Step 10</a>'],
                 ["8", "Projections with no method behind them", "380 (10.5%)",
                  '<a href="#g-prong1">Step 3</a>'],
                 ["9", "Argued a labor shortage in the occupation", "325 (8.9%)",
                  '<a href="#g-prong1">Step 3</a>'],
                 ["10", "Missing labor-certification form, translations, or a valid "
                  "representation form", "115, 56, 24", '<a href="#g-package">Step 7</a>']],
                "Counts are decisions containing the relevant language at least once, over the "
                "3,633 dismissed appeals. Rows overlap and do not sum. Each count is a proxy for "
                "the error rather than an adjudicated finding of it, and row 1 is the most "
                "affected by that because the phrase is partly a recital of the legal standard. "
                "See the sources section.", label="The mistakes that lose petitions, ranked by frequency")

        + note('The two structural ones are worth separating from the rest',
               P('Rows 2 and 4 are not writing problems. A petition organised as a career story '
                 'will produce row 2 automatically, because a career story is evidence about the '
                 'person and prong 1 asks about the work. And an endeavor described at the level '
                 'of an occupation will produce rows 1 and 4 together.') +
               P('Both are fixed by structure before drafting, not by editing afterwards.'),
               "good")
        + NOT_ADVICE
    )
    S.append(section("g-mistakes", "Diagnostics", "The mistakes that lose petitions",
                     "Ranked from the published refusals, with where on this page each one is "
                     "addressed.", body))

    # ---- 13. Getting help --------------------------------------------------
    body = (
        note('This page does not recommend, rate, or criticise any law firm',
             P('That is deliberate rather than evasive. A verdict about a firm goes stale, and it '
               'is useless for the firm nobody has reviewed. A checklist you run yourself works '
               'on any firm, in any year, including the one a colleague just recommended.'),
             "good")

        + H3('Score the intro call')
        + P('Book at least three. Score during the call rather than from memory afterwards. Full '
            'points for a specific answer the firm will put in writing, half for a vague or '
            'verbal-only answer, zero for a deflection.')
        + table(["What to check", "Ask this", "Points"],
                [["A named attorney is assigned, and you speak to them before paying",
                  "Which licensed attorney will sign my petition, and can I speak with them "
                  "before I sign anything?", "12"],
                 ["They name your weakest prong, specifically, on the call",
                  "Having heard my profile, which of the three prongs is weakest for me, and "
                  "why?", "12"],
                 ["A flat fee in writing, with the scope itemised",
                  "Please send the fee in writing, listing whether petition drafting, a response "
                  "to a request for evidence, a response to a notice of intent to deny, a "
                  "refile, and an appeal are each inside it.", "12"],
                 ["What they do when a request for evidence lands",
                  "Will you send me the complete notice exactly as USCIS issued it, not a "
                  "summary? If the officer asks for independent letters, will you add them?",
                  "10"],
                 ["A licensed attorney drafts the petition letter",
                  "Who writes the first draft: you, a paralegal, an offshore team, or a "
                  "template? Who reviews it before filing?", "10"],
                 ["The guarantee is a clause you can read",
                  "Show me the guarantee clause. Is it a cash refund or a free refile? What "
                  "percentage? What voids it?", "9"],
                 ["They insist on independent recommenders, and say who drafts letters",
                  "Who drafts the recommendation letters, how many independent recommenders do "
                  "you require, and how do you help me find them?", "8"],
                 ["You check the signing attorney's licence yourself",
                  "Nothing to ask. Get the full name in writing, then search your state bar's "
                  "public attorney lookup.", "7"],
                 ["What happens if your job or endeavor changes",
                  "If I change employers, or the endeavor shifts before filing or during a "
                  "request for evidence, what happens to the work done and to what I have paid?",
                  "6"],
                 ["They will include evidence you supply that they did not ask for",
                  "If I hand you evidence you did not request, will it go in the petition?",
                  "5"],
                 ["They know to look for a government or agency interest letter",
                  "Would a letter from a federal agency or national laboratory help my prong 1 "
                  "and prong 3? Have you obtained one before?", "4"],
                 ["They get the premium processing facts right",
                  "What is the premium processing timeline for a national interest waiver, and "
                  "does upgrading affect the guarantee?", "3"],
                 ["The engagement agreement is readable before any payment",
                  "Please send the full agreement so I can read it before I pay.", "2"]],
                "Total 100.", label="Scorecard for an intro call with a law firm")
        + table(["Score", "What to do"],
                [["80 to 100", "Strong. Read the agreement line by line, confirm the written "
                  "items actually arrived in writing, and proceed if they did."],
                 ["55 to 79", "Ask more. Send the unanswered items by email and re-score from "
                  "the reply. A firm that answers well in writing after a mediocre call is fine. "
                  "One that will not put it in writing has answered you."],
                 ["Below 55", "Keep interviewing. A low score is rarely about competence. It is "
                  "about a sales process that will not commit to specifics, and specifics are "
                  "the only thing you can hold anyone to later."]], label="How to read your scorecard total")
        + note('Three hard stops, whatever the total',
               P('Do not sign if you scored zero on the named attorney, on the written itemised '
                 'scope, or on who drafts the petition. Those three are the terms of the deal. '
                 'Everything else is quality.'), "warn")

        + H3('What a "guarantee" actually is')
        + P('"Approval guarantee" is a marketing label, not a defined term, and it describes '
            'several different commercial structures with very different value. Two things are '
            'true across all of them: government filing fees are never part of any firm '
            'guarantee and USCIS does not refund them on a refusal, and a guarantee is worth '
            'only what the written clause says.')
        + collapsible('The common structures, and the question that cuts through each',
                      P('<strong>Cash refund of the professional fee.</strong> Ask what exact '
                        'amount comes back, what it is a percentage of, and how many days after '
                        'the refusal you receive it. A percentage of "attorney fee net of costs" '
                        'is a different number from a percentage of what you wired.') +
                      P('<strong>Free refile, no money back.</strong> Ask who pays the second '
                        'government filing fee and whether there is a deadline to keep it. '
                        'Genuinely valuable, since refiling often beats appealing, but it is not '
                        'a refund.') +
                      P('<strong>Tiered, where the guaranteed tier is by invitation.</strong> Ask '
                        'which tier you are being offered and what would have to be true for you '
                        'to be offered the guaranteed one. A success rate calculated inside a '
                        'tier that only admits cases the firm expects to win measures the '
                        'admission decision. That is arithmetic, not an accusation.') +
                      P('<strong>Guarantee with voiding events.</strong> Ask for the full list, '
                        'then check it for upgrading to premium processing, supplying evidence '
                        'the firm did not approve, changing employer or endeavor, and missing an '
                        'internal deadline.') +
                      P('<strong>An eligibility screen described as a guarantee.</strong> Ask '
                        'whether it is a promise about your outcome or a promise that they '
                        'decline cases they expect to lose. Both are legitimate. Only one pays '
                        'you anything.') +
                      P('And for any structure: who decides whether the guarantee triggered, and '
                        'does a withdrawal, a rejection for a fee error, or an abandonment count '
                        'as a refusal for that clause?'))

        + H3('What it costs')
        + P('Government fees are fixed and published, and are in Step 8. Attorney fees are '
            'negotiated and vary by roughly a factor of five.')
        + table(["Tier", "Observed range", "What you are buying"],
                [["Self-prepared", "$0 in professional fees",
                  "You write it. Real costs remain: translations, credential evaluation, "
                  "copying and courier."],
                 ["Consultation or review only",
                  "Often free for a 30-minute intro call. Paid review pricing not reliably "
                  "observed.",
                  "Strategy without representation. A legitimate way to buy an approach and then "
                  "execute it yourself."],
                 ["Full petition on a flat fee", "Roughly $5,000 to $9,000",
                  "Drafting and filing. Whether a response to a request for evidence sits inside "
                  "this number is the question that decides your real cost."],
                 ["Premium or boutique", "Roughly $10,000 to $25,000",
                  "Senior attorney time and more hand-holding. Buy access and accountability at "
                  "this tier, not reassurance."],
                 ["Response to a request for evidence, bought separately",
                  "Roughly $4,000 to $9,000",
                  "The number nobody budgets for. Settle it before you sign."]],
                "Ranges last checked September 2026. Basis, stated because it is not strong: "
                "prices firms publish in their own advertising, and figures posted publicly by "
                "petitioners describing quotes they received. That sample is anonymous, "
                "self-selected and impossible to audit, and quoted fees move with the profile "
                "being quoted. Use these to recognise an outlier, not as a rate card, and never "
                "as a reason to argue a particular firm's price is wrong. No figure here is "
                "attached to any firm.", label="Attorney fee tiers, as observed ranges")
        + collapsible('What moves a quote up or down the range',
                      P('<strong>Up:</strong> an industry rather than research profile, few '
                        'publications, filing from outside the United States, a prior refusal on '
                        'the record, an endeavor spanning more than one area, needing the firm to '
                        'find recommenders for you, a hard deadline because status is expiring.') +
                      P('<strong>Down:</strong> a research profile with clear publication '
                        'evidence, independent letters already in hand, a narrow endeavor you '
                        'have already written, filing online and assembling your own exhibits, '
                        'producing the first draft yourself.') +
                      P('One structural point that explains the spread: a firm that screens hard '
                        'and takes mostly strong cases carries less risk per case and can price '
                        'accordingly. The useful consequence for you is that if a firm at the low '
                        'end accepts your case, that is real information about your case. If it '
                        'declines, that is also information. Neither is a judgement about the '
                        'firm.'))

        + H3('Finding somebody, and the free check nobody does')
        + P('The ' + AILA + ' member directory is free to search and lets you filter by practice '
            'area, language and location. Read what it says about itself: it is not a lawyer '
            'referral service, and it does not vet or recommend. It tells you who is a member '
            'practising in your area, not who is good.')
        + note('Then spend five minutes on the state bar',
               P('Take the full name of the attorney who will sign your petition and search your '
                 'state bar\'s public attorney lookup for licence status and disciplinary '
                 'history. It is free, it takes minutes, and it is the only quality signal '
                 'available to you that is neither anonymous nor self-reported. Depth of '
                 'published discipline history varies by state.'), "good")

        + H3('Preparing it yourself')
        + P('Self-preparation is a real option rather than a fallback, and self-filed petitions '
            'do get approved. Read that with the obvious caveat: nobody posts about the '
            'self-filed petition that was refused, so the visible success rate of self-filing is '
            'not its actual success rate.')
        + collapsible('What it actually demands',
                      P('<strong>Reading first.</strong> ' + PM_NIW + ', the ' + DHANASAR +
                        ' framework it applies, the current Form I-140 instructions, and a set of '
                        'decisions in your own field. That last one is the highest-value free '
                        'hour available to you, and the '
                        '<a href="niw-decisions.html">decision browser</a> exists to make it '
                        'possible.') +
                      P('<strong>Time.</strong> Months, not a weekend, and the drafting is not '
                        'the longest part. Letters are.') +
                      P('<strong>A narrow endeavor, rewritten until it is narrow.</strong> You '
                        'will rewrite that paragraph more than anything else.') +
                      P('<strong>Independent letters you source yourself,</strong> reached '
                        'through introductions rather than cold email, describing specific use of '
                        'your work. Expect declines. Start months out.') +
                      P('<strong>The mechanics exactly right.</strong> Current form edition, the '
                        'right classification box, the ETA-9089 Appendix A with a signed Final '
                        'Determination, and the correct total fee including the Asylum Program '
                        'Fee line. An error here is a rejection, not a correction.'))
        + note('Who should not attempt it alone',
               '<ul><li>Anyone whose lawful status ends on a fixed date with no room to absorb a '
               'rejection or a request for evidence.</li>'
               '<li>Anyone with a prior refusal, a notice of intent to deny, or a withdrawn '
               'petition on the record. The second attempt is harder and the stakes are '
               'higher.</li>'
               '<li>Anyone whose petition has to be sequenced against something else: a pending '
               'application to adjust status, a home-residency waiver, a consular route, a change '
               'of employer. The timing judgement matters more than the drafting, and that is '
               'what counsel is for.</li>'
               '<li>Anyone who cannot write clear technical prose about their own work in '
               'English, or who has nobody willing to critique the draft honestly.</li>'
               '<li>Anyone planning to have a language model write it and file the output '
               'unread. An invented citation in a petition is a serious problem.</li></ul>',
               "warn")
        + note('The middle path most people should consider',
               P('Draft it yourself, then pay a licensed attorney for a review before you file. '
                 'Use free consultations to learn the approach and to hear where different '
                 'attorneys think you are weak. Disagreement between two firms about your case '
                 'is itself useful information, and it costs an hour each.'), "good")
        + NOT_ADVICE
    )
    S.append(section("g-help", "Getting help", "Hiring counsel, or not",
                     "How to score any firm yourself, what a guarantee really is, what it "
                     "costs, and when to do it alone.", body))

    # ---- 14. Full checklist ------------------------------------------------
    body = (
        P('Everything above, in one list, organised by what each item proves. Print it or keep it '
          'beside your drafting document.')
        + H3('A. You qualify for EB-2')
        + checklist([
            "Highest degree certificate and official transcript.",
            "Credential evaluation for any foreign degree, complete before filing.",
            "Certified English translation behind every non-English document.",
            "Employer letters covering five years of progressive experience, if using that "
            "route. On letterhead, signed, with dates, titles and duties.",
            "If using exceptional ability: evidence for at least three of the six categories, "
            "plus an argument on the final merits determination.",
        ])
        + H3('B. Prong 1: the endeavor has substantial merit and national importance')
        + checklist([
            "Your written endeavor paragraph. Specific work, not an occupation.",
            "Government publications, strategies or priority lists naming the area of work.",
            "Federal or state agency programme descriptions covering it.",
            "Standards-body documents, published research or data establishing the importance of "
            "the problem.",
            "Evidence the work has effects beyond a single company.",
            "Any letter from a government body, national laboratory or public agency describing "
            "why the work matters to their mission. Rare, slow, strong.",
        ])
        + H3('C. Prong 2: you are well positioned to advance it')
        + checklist([
            "CV, and degrees or training relevant to the endeavor.",
            "Your own results: publications, patents, released products, deployed systems, "
            "datasets, standards contributions.",
            "Citation or usage evidence, restricted to work connected to the endeavor, framed as "
            "a rate relative to the field.",
            "Independent recommendation letters, from people with no employment or financial "
            "relationship to you.",
            "Employer and collaborator letters, clearly distinguished from those.",
            "A plan, paired with evidence of progress already made against it.",
            "Evidence of interest in your work from parties who are not your employer.",
        ])
        + H3('D. Prong 3: waiving the job offer benefits the United States on balance')
        + checklist([
            "Anything showing it would be impractical to obtain a labor certification given your "
            "qualifications or the endeavor.",
            "Evidence of benefit from your contributions specifically, framed to survive the "
            "point that other US workers may also be available.",
            "Evidence of urgency, if there genuinely is any.",
            "Evidence you hold knowledge or skills exceeding the minimum for the occupation.",
            "Economic impact or job-creation evidence, if applicable.",
            "Do not rest this section on a labor shortage.",
        ])
        + H3('E. Forms, fees and mechanics')
        + checklist([
            "Form I-140, current edition, signed, all pages the same edition.",
            "Form ETA-9089 Appendix A, and a signed Final Determination. Uncertified.",
            "Filing fee, plus the Asylum Program Fee as a separate payment.",
            "Form I-907 and its fee, only if using premium processing.",
            "Petition letter ordered: EB-2 eligibility, prong 1, prong 2, prong 3.",
            "Numbered exhibits, sequential, with an index built last.",
            "A complete copy kept by you, and tracked delivery with the number recorded.",
        ])
        + NOT_ADVICE
    )
    S.append(section("g-checklist", "Checklist", "The full checklist",
                     "Everything above in one place, grouped by what each document proves.",
                     body))

    # ---- 15. Sources and limits -------------------------------------------
    body = (
        P('Two kinds of statement appear on this page and they carry different weight. Legal and '
          'procedural facts come from official sources, each linked where it is used. '
          'Statistics come from a local index of published appeal decisions, described below.')

        + H3('Official sources')
        + checklist([
            PM_NIW + ", which is the adjudication guidance USCIS applies.",
            DHANASAR + ", the precedent that sets the three-prong test. The single most useful "
            "thing to read.",
            EB2_PAGE + ", for what must accompany the petition.",
            G1055 + ", the fee schedule, Edition 05/29/26. Fees change; read it on the day.",
            I140 + ", " + I907 + " and " + I290B + " form pages, for current editions and "
            "instructions.",
        ])

        + H3('Where the statistics come from')
        + P('A local index of <strong>4,987</strong> decisions published by the USCIS '
            'Administrative Appeals Office in the EB-2 advanced-degree and exceptional-ability '
            'category, spanning January 2015 to July 2026. That is roughly 97% of what the '
            'public USCIS listing exposes for that window. Each decision was downloaded as a '
            'PDF, its text extracted, and its fields read with fixed text patterns. '
            '<strong>No language model is involved at any stage</strong>, so nothing here is '
            'summarised or inferred. A field that could not be read was left blank rather than '
            'guessed. You can read the aggregate view on the '
            '<a href="niw-appeals.html">appeal outcomes page</a> and every decision one at a '
            'time in the <a href="niw-decisions.html">decision browser</a>.')

        + note('What this record structurally cannot tell you',
               '<ul><li><strong>Any approval rate.</strong> Every decision here is an appeal of a '
               'refusal. USCIS does not publish approved petitions, so no NIW approval rate '
               'exists in any official source. Nothing on this page is one.</li>'
               '<li><strong>Whether refiling beats appealing.</strong> Refilings are not '
               'published and no identifier survives across filings, so any such comparison '
               'would be invented. What the record does support is the narrower point in Step '
               '10.</li>'
               '<li><strong>What share of refusals get appealed.</strong> The population of '
               'refusals is not published, so there is no denominator.</li>'
               '<li><strong>Why the sustained share fell after 2020.</strong> The pattern is in '
               'the data. The explanation is not, and is not guessed at here.</li>'
               '<li><strong>Anything about your case.</strong> Base rates are not '
               'predictions.</li></ul>', "warn")

        + collapsible('Honest limits on the counts themselves',
                      P('<strong>Selection, twice over.</strong> These are people who were '
                        'refused and then chose to pay to appeal. That is not a random sample of '
                        'petitioners, and the direction and size of the bias are unknown.') +
                      P('<strong>Every mistake count is a proxy.</strong> It measures the '
                        'presence of the language associated with an error, not an adjudicated '
                        'finding that the petition committed it. The most affected is the '
                        'field-versus-endeavor count, because that sentence is partly a recital '
                        'of the legal standard, which is why this page leans on the gap between '
                        'the refused and granted columns instead of the raw share.') +
                      P('<strong>Rows overlap.</strong> One decision can contain several errors, '
                        'so the counts do not sum.') +
                      P('<strong>Scanned-document noise.</strong> These are scans and the text '
                        'extraction misreads characters, digits in regulatory citations worst of '
                        'all. Counts that do not anticipate a particular misreading are '
                        'undercounts.') +
                      P('<strong>Sparse fields.</strong> Roughly a third of decisions carry no '
                        'machine-readable failed prong and a fifth no self-described occupation, '
                        'so those are reported as counts rather than rates, over the decisions '
                        'where the field was actually found.'))

        + collapsible('Things worth re-checking before you rely on them',
                      P('Current processing times for the I-140 and the I-485. These move '
                        'monthly, so no figure is quoted anywhere on this page. Read the USCIS '
                        'processing-times tool yourself.') +
                      P('Whether DOL wants the base Form ETA-9089 as well as Appendix A. USCIS '
                        'names Appendix A and a signed Final Determination, twice on its EB-2 '
                        'page and once in the Federal Register notice. The note on DOL\'s own '
                        'forms page is worded more broadly: sign and submit "a fully executed '
                        'copy of page 2 along with Form ETA-9089 and the appropriate appendices". '
                        'USCIS is the agency receiving the filing, so its list governs, but '
                        'including the base form costs nothing and covers the broader wording. '
                        'See step 7.') +
                      P('Current Visa Bulletin cut-off dates, and which chart USCIS says '
                        'adjustment applicants may use this month. Both change monthly.'))

        + P('<strong>The standard of proof, since it comes up constantly.</strong> Preponderance '
            'of the evidence: more likely than not. The AAO adds two riders worth remembering, '
            'that eligibility "is to be determined not by the quantity of evidence alone but by '
            'its quality", and that "assertions themselves do not constitute evidence".')
        + NOT_ADVICE
    )
    S.append(section("g-sources", "Method", "Sources and limits",
                     "What is official, what is counted, and what this record cannot tell you.",
                     body))

    return "".join(S)


# ---------------------------------------------------------------------------
def page():
    header, strip, footer = site_shell()
    sections = build()
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%s &mdash; Green Card Navigator</title>
<meta name="description" content="A step-by-step guide to self-petitioning an EB-2 national interest waiver: the two eligibility tests, how to write the endeavor, evidence for each of the three prongs, the forms and fees, and what to do after a request for evidence or a denial.">
<link rel="canonical" href="https://www.greencardnav.com/niw-guide.html">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="stylesheet" href="styles.css">
</head>
<body class="paths-page">
<a class="skip-link" href="#maincontent">Skip to content</a>
%s
<div class="container" id="maincontent" role="main" tabindex="-1">
<div class="paths-layout">
%s
<div class="paths-content">
<h1 class="hub-title">%s</h1>
%s
%s
</div>
</div>
</div>
%s
<script src="immigration-data.js"></script>
<script src="rulebook.js"></script>
<script src="app.js"></script>
</body>
</html>
""" % (TITLE, header, toc_html(), TITLE, strip, sections, footer)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="write niw-guide.html")
    args = ap.parse_args()

    html = page()
    words = len(__import__("re").sub(r"<[^>]+>", " ", html).split())
    print("niw-guide.html : %d chars, roughly %d words of copy" % (len(html), words))
    print("  sections     : %d" % len(TOC))
    for bad in ("no ETA 9089", "certified-expired"):
        if bad in html:
            raise SystemExit("guard: unexpected string %r in output" % bad)
    if "approval rate" not in html:
        raise SystemExit("guard: the page must state that nothing here is an approval rate")

    if not args.commit:
        print("Dry run: nothing written. Re-run with --commit.")
        return 0
    io.open(OUT, "w", encoding="utf-8").write(html)
    print("wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
