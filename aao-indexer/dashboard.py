#!/usr/bin/env python3
"""
dashboard.py - render out/decisions.json into a self-contained HTML dashboard.

    python3 dashboard.py            # writes out/dashboard.html
    open out/dashboard.html

Design constraints, deliberately:
  * ONE file, zero external requests. No CDN, no chart library, no fonts, no
    analytics. Charts are hand-rolled SVG and CSS bars. It opens offline and no
    third party learns you looked at it. (The site we are imitating loads two
    Google Analytics properties.)
  * Every number is computed from decisions.json, which is itself parsed
    deterministically from the source PDFs. No LLM anywhere in the chain.
  * Where our data cannot support a panel, the panel says so rather than
    rendering a plausible-looking empty chart.
"""

import collections, html, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SRC = os.path.join(OUT, "decisions.json")

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

# Each precedent's full citation, what it actually holds, and a link to the primary
# text. Every citation below was read out of the decision PDFs in our own corpus (so it
# is what the AAO literally cites, not a secondhand summary), and every URL was checked
# to return HTTP 200. Two of the seven are NOT AAO decisions, which is worth knowing:
#   - Bagamasbad is a 1976 SUPREME COURT per curiam, not an immigration decision at all.
#   - Furtado is a 2024 BIA decision, so it sits in the AG/BIA volumes, not the
#     DHS/AAO/INS series. It is also the newest thing the AAO leans on here.
# "key" is the field suffix in decisions.json (cite_<key>); the apostrophe in
# Christo's is stripped there, so the key and the display label differ.
PRECEDENTS = {
    "Chawathe": {
        "label": "Chawathe",
        "cite": "Matter of Chawathe, 25 I&amp;N Dec. 369 (AAO 2010)",
        "for": "the preponderance-of-the-evidence burden",
        "held": "Sets the standard of proof. You must show eligibility is more likely than "
                "not, roughly a coin flip plus one, not beyond doubt. Nearly every decision "
                "recites it, which is why it sits at the top of this table alongside "
                "Dhanasar rather than because it is doing any analytical work.",
        "url": "https://www.justice.gov/eoir/vll/intdec/vol25/3700.pdf",
    },
    "Dhanasar": {
        "label": "Dhanasar",
        "cite": "Matter of Dhanasar, 26 I&amp;N Dec. 884 (AAO 2016)",
        "for": "the three-prong NIW framework",
        "held": "The case that defines the modern NIW test: the endeavor has substantial "
                "merit and national importance, you are well positioned to advance it, and "
                "on balance it benefits the US to waive the job offer and labor "
                "certification. Read this one first.",
        "url": "https://www.justice.gov/media/871246/dl?inline",
    },
    "Bagamasbad": {
        "label": "Bagamasbad",
        "cite": "INS v. Bagamasbad, 429 U.S. 24 (1976)",
        "for": "authority to decline to reach later prongs",
        "held": "A Supreme Court per curiam, not an immigration decision: agencies are not "
                "required to make findings on issues whose decision is unnecessary to the "
                "result. Where the AAO cites it, it has almost certainly stopped after "
                "prong 1 and never evaluated prongs 2 and 3 at all.",
        "url": "https://www.law.cornell.edu/supremecourt/text/429/24",
    },
    "Christos": {
        "label": "Christo&rsquo;s",
        "cite": "Matter of Christo&rsquo;s, Inc., 26 I&amp;N Dec. 537 (AAO 2015)",
        "for": "de novo review",
        "held": "The AAO reviews the whole record afresh rather than checking the service "
                "center for clear error. That cuts both ways: it can find new grounds to "
                "deny, and it can withdraw a prong the service center already granted you.",
        "url": "https://www.justice.gov/sites/default/files/eoir/pages/attachments/2015/04/16/3831.pdf",
    },
    "Katigbak": {
        "label": "Katigbak",
        "cite": "Matter of Katigbak, 14 I&amp;N Dec. 45 (Reg&rsquo;l Comm&rsquo;r 1971)",
        "for": "eligibility fixed at the time of filing",
        "held": "You must have met every requirement on the day you filed. Qualifications "
                "earned afterwards do not count, no matter how strong. This is why filing "
                "too early is expensive.",
        "url": "https://www.justice.gov/eoir/vll/intdec/vol14/2125.pdf",
    },
    "Izummi": {
        "label": "Izummi",
        "cite": "Matter of Izummi, 22 I&amp;N Dec. 169 (Assoc. Comm&rsquo;r 1998)",
        "for": "cannot cure eligibility after filing",
        "held": "The companion to Katigbak: you cannot make material changes after filing to "
                "bring a deficient petition into compliance. Changing the described endeavor "
                "mid-case is the trap this catches.",
        "url": "https://www.justice.gov/eoir/vll/intdec/vol22/3360.pdf",
    },
    "Furtado": {
        "label": "Furtado",
        "cite": "Matter of Furtado, 28 I&amp;N Dec. 794 (BIA 2024)",
        "for": "new evidence first raised on appeal",
        "held": "A 2024 BIA decision, and the newest authority in this table. It lets the "
                "AAO refuse to consider evidence produced for the first time on appeal when "
                "you were already put on notice of the gap, typically by an RFE. Answer the "
                "RFE fully; the appeal is not a second chance to file.",
        "url": "https://www.justice.gov/eoir/media/1352416/dl?inline",
    },
}

PHRASE_LABEL = {
    "not_industry":     "&ldquo;not the importance of the industry, field, or profession&rdquo;",
    "teaching_analogy": "the <em>Dhanasar</em> teaching-activities analogy",
    "conclusory":       "&ldquo;conclusory&rdquo;",
    "generalized":      "&ldquo;generalized&rdquo;",
    "beyond_employer":  "impact must extend &ldquo;beyond his employer, company, clients, or customers&rdquo;",
    "inconsistent":     "&ldquo;inconsistent&rdquo;",
    "speculative":      "&ldquo;speculative&rdquo;",
    "material_change":  "&ldquo;material change&rdquo;",
    "unsupported":      "&ldquo;unsupported&rdquo;",
}

OCC_GROUPS = [
    ("Software, IT and data", r'software|cloud|data scien|IT consultant|SAP|Oracle|cyber|DevOps|machine learning|artificial intel|programmer|developer|information system'),
    ("Engineering, other",    r'\bengineer'),
    ("Business and entrepreneurship", r'entrepreneur|business|manager|executive|CEO|COO|consultant|analyst|marketing|financ|account|procurement|supply|treasurer|controller|real estate'),
    ("Academic and research", r'postdoctoral|professor|researcher|research scientist|scholar|scientist'),
    ("Medicine and health",   r'physician|nurse|dentist|health|medical|clinic|epidemiolog|pharmac|therap|surgeon|psycholog'),
    ("Education",             r'teacher|educator|instructor|lecturer|coach'),
    ("Law and policy",        r'lawyer|attorney|legal|policy'),
    ("Arts, sport and other", r'artist|musician|designer|chef|athlete|pilot|dancer|photograph|architect'),
]

E = html.escape



# ---------------------------------------------------------------------------
# Hover definitions. The definition is a real nested <span> rather than a title
# attribute, so it is styled, keyboard-reachable and read by screen readers.
# ---------------------------------------------------------------------------
TIPS = {
 "dismissed": "The AAO agreed with the original decision. The appeal failed and the denial stands. "
              "This is the normal outcome.",
 "sustained": "The petitioner won outright. The AAO overturned the denial, so the petition is "
              "approved. By far the rarest outcome.",
 "remanded": "The AAO withdrew the original decision and sent the case back because the reasoning "
             "was inadequate. This is NOT a win. No visa is granted; the service center simply has "
             "to decide it again properly.",
 "motion dismissed": "A motion to reopen or reconsider was refused. Harder than an appeal: "
                     "reopening needs new facts with evidence, reconsidering needs proof the AAO "
                     "misapplied law or policy. Usually a later attempt after an appeal failed.",
 "abandoned": "Dismissed under 8 CFR 103.2(b)(13) because the petitioner did not pursue it. A "
              "procedural loss, not a loss on the merits.",
 "unparsed": "The script could not read a definite outcome from the decision's ORDER line, so it "
             "records nothing rather than guessing.",
 "AAO": "Administrative Appeals Office, the USCIS body that reviews appeals of denied petitions.",
 "prong": "One of the three tests from Matter of Dhanasar. All three must be met, and failing any "
          "one ends the petition.",
 "Prong 1": "Substantial merit and national importance of the proposed endeavor. This is where most "
            "petitions die.",
 "Prong 2": "Whether the petitioner is well positioned to advance the endeavor, judged on their "
            "track record rather than credentials alone.",
 "Prong 3": "Whether, on balance, it benefits the United States to waive the job offer and labor "
            "certification requirements.",
 "merits": "Decided on the substance of the case, rather than on a motion or a procedural point. "
           "The rate cards use merits decisions only so the denominator is comparable.",
}



MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def date_key(v):
    """YYYYMMDD for sorting. Empty dates sort last, not first, so the rows the
    parser could not read do not dominate an ascending sort."""
    m = re.match(r'([A-Z]{3})\.?\s*(\d{1,2}),\s*(\d{4})', (v or "").strip(), re.I)
    if not m:
        return "99999999"
    return "%s%02d%02d" % (m.group(3), MONTH_NUM.get(m.group(1).upper(), 0), int(m.group(2)))


def dash(v):
    """Escaped value, or an em-dash entity when empty.

    Do NOT write E(x or "&mdash;"): html.escape turns the ampersand into &amp;
    and the cell renders the literal text "&mdash;".
    """
    v = (v or "").strip()
    return E(v) if v else "&mdash;"


def t(term, label=None):
    d = TIPS.get(term)
    shown = label or term
    if not d:
        return E(shown)
    return ('<span class="gt" tabindex="0">%s<span class="gt-def">%s</span></span>'
            % (E(shown), E(d)))


def year_of(rec):
    m = re.match(r'([A-Z]{3})\.?\s*\d{1,2},\s*(\d{4})', rec.get("date", "") or "")
    return int(m.group(2)) if m else None


def bar(pct, tone="a"):
    pct = max(0.0, min(100.0, pct))
    return ('<span class="bar"><span class="fill t%s" style="width:%.1f%%"></span></span>'
            % (tone, pct))


def pct(n, d):
    return (100.0 * n / d) if d else 0.0


def card(label, value, sub):
    return ('<div class="card"><div class="k">%s</div><div class="v">%s</div>'
            '<div class="s">%s</div></div>' % (label, value, sub))


def build(rows):
    n = len(rows)
    oc = collections.Counter(r["outcome"] or "unparsed" for r in rows)
    merits = [r for r in rows if r["outcome"] in ("dismissed", "sustained", "remanded")]
    nm = len(merits)
    om = collections.Counter(r["outcome"] for r in merits)

    H = []
    A = H.append

    # ---------------- head ----------------
    A("""<!DOCTYPE html>
<html lang="en" data-theme="light"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>AAO decisions dashboard (local)</title>
<style>
/* Design tokens copied verbatim from the Green Card Navigator stylesheet so this
   reads as part of the same system. Open Sans is deliberately NOT loaded: a web
   font would be a network request, and this file makes none. The system stack is
   gcnav's own declared offline fallback. */
:root{
  --neutral-950:#0f141a; --neutral-900:#161d26; --neutral-850:#232b37;
  --neutral-650:#424650; --neutral-600:#656871; --neutral-500:#8c8c94;
  --neutral-350:#c6c6cd; --neutral-250:#ebebf0; --neutral-150:#f6f6f9;
  --neutral-100:#f9f9fa; --white:#fff;
  --primary-600:#006ce0; --primary-700:#003c75; --primary-50:#f0fbff;
  --amber-400:#ff9900; --amber-500:#fa6f00;
  --success-600:#00802f; --success-50:#effff1;
  --error-600:#db0000;   --error-50:#fff5f5;
  --warning-900:#855900; --warning-50:#fffef0; --warning-border:#f7db8a;
  --best-text:#14532d; --typical-text:#7c2d12; --worst-text:#7f1d1d; --info-text:#01437d;
  --border:#dfe1e6; --border-strong:var(--neutral-350);
  --text:var(--neutral-950); --text-soft:var(--neutral-650); --muted:var(--neutral-600);
  --bg:var(--neutral-100); --card:var(--white);
  --radius-md:11px; --radius-sm:8px;
  --shadow-sm:0 1px 2px rgba(9,30,66,.07);
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
[data-theme="dark"]{
  --neutral-950:#f2f3f3; --neutral-850:#d4d8dd; --neutral-650:#aeb4bd;
  --neutral-600:#9298a1; --neutral-350:#3a4652; --neutral-250:#2f3b47;
  --neutral-150:#1f2731; --neutral-100:#0f141a;
  --primary-600:#4a9eff; --primary-700:#8cc2ff; --primary-50:#10263c;
  --amber-400:#ffb84d;
  --success-600:#4ade80; --success-50:#10261a;
  --error-600:#f87171;   --error-50:#2b1414;
  --warning-900:#e6b45c; --warning-50:#2a2410;
  --best-text:#4ade80; --typical-text:#e6b45c; --worst-text:#f87171; --info-text:#8cc2ff;
  --border:#2f3b47; --border-strong:#3a4652;
  --text:#e9ebed; --text-soft:#aeb4bd; --muted:#9298a1;
  --bg:#0f141a; --card:#1a232e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
 font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
 font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px 72px}
header{padding:26px 0 18px;border-bottom:1px solid var(--border);margin-bottom:26px;
 display:flex;align-items:flex-start;gap:20px;flex-wrap:wrap}
.hgroup{flex:1;min-width:280px}
h1{font-size:26px;margin:2px 0 6px;letter-spacing:-.5px;font-weight:700}
.eyebrow{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
 color:var(--primary-700)}
.meta{color:var(--muted);font-size:13.5px;margin:0;max-width:74ch}
h2{font-size:19px;margin:36px 0 6px;letter-spacing:-.25px}
h3{font-size:11px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.07em;
 color:var(--muted);font-weight:700}
h4{margin:0 0 5px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
p{margin:0 0 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));gap:13px;margin:18px 0 6px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-md);
 padding:15px 16px;box-shadow:var(--shadow-sm)}
.card .k{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.card .v{font-size:28px;font-weight:700;letter-spacing:-.6px;margin:4px 0 2px}
.card .s{font-size:12.5px;color:var(--muted);line-height:1.45}
.panel{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-md);
 padding:17px 19px;margin:14px 0;box-shadow:var(--shadow-sm)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:14px 0}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:2px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:0}
th{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:700}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{display:inline-block;width:120px;height:6px;background:var(--neutral-250);
 border-radius:3px;overflow:hidden;vertical-align:middle}
.fill{display:block;height:100%;border-radius:3px}
.ta{background:var(--primary-600)}
.tb{background:var(--success-600)}
.tc{background:var(--amber-400)}
.td{background:var(--neutral-500)}
.te{background:var(--primary-700)}
.no{color:var(--worst-text);font-weight:600}
.yes{color:var(--best-text);font-weight:600}
code{font-family:var(--mono);font-size:.88em;background:var(--neutral-150);
 padding:1px 5px;border-radius:4px}
.note{border:1px solid var(--border);border-left-width:3px;border-radius:var(--radius-md);
 padding:12px 15px;margin:15px 0;font-size:13.5px}
.note.warn{border-left-color:var(--error-600);background:var(--error-50);color:var(--worst-text)}
.note.good{border-left-color:var(--success-600);background:var(--success-50);color:var(--best-text)}
.note.gap{border-left-color:var(--warning-border);background:var(--warning-50);color:var(--typical-text)}
.note strong{color:inherit}
.chart{width:100%;height:auto;overflow:visible}
.chart text{font-size:10px;fill:var(--muted)}
.chart .gl{stroke:var(--neutral-250);stroke-width:1}
.ctl{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:12px 0 6px}
.ctl input,.ctl select{font:inherit;font-size:13px;padding:7px 10px;
 border:1px solid var(--neutral-500);border-radius:var(--radius-sm);
 background:var(--card);color:var(--text)}
.ctl input{flex:1;min-width:210px}
.hint{font-size:12.5px;color:var(--muted);margin:9px 0 0}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--border-strong);
 font-size:12.5px;color:var(--muted)}
.tog{display:flex;gap:2px;border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px;
 align-self:flex-start}
.tog button{border:0;background:none;color:var(--muted);cursor:pointer;font:inherit;font-size:12px;
 padding:5px 10px;border-radius:6px}
.tog button[aria-pressed="true"]{background:var(--primary-50);color:var(--primary-700);font-weight:600}
.pager{display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;padding:12px 0 4px;font-size:13px;color:var(--muted)}
.pager button{font:inherit;font-size:13px;padding:7px 14px;border:1px solid var(--neutral-500);border-radius:var(--radius-sm);background:var(--card);color:var(--text);cursor:pointer}
.pager button:hover:not(:disabled){border-color:var(--primary-600);color:var(--primary-700)}
.pager button:disabled{opacity:.45;cursor:default}
.pager button:focus-visible{outline:2px solid var(--primary-600);outline-offset:2px}
@media(max-width:420px){.pager{gap:8px}.pager button{padding:9px 12px}}
.gt{position:relative;border-bottom:1px dotted var(--primary-600);cursor:help;color:inherit;outline:none}
/* Precedent names are a hover AND a link, so the anchor itself must read as
   clickable rather than inheriting the .gt help cursor. */
.prec-link{color:var(--primary-700);font-weight:700;text-decoration:none;cursor:pointer}
.prec-link:hover,.prec-link:focus-visible{text-decoration:underline}
/* The backslash below MUST be doubled in the Python source. A single backslash makes
   Python read the first two digits as an octal escape and leave "97" as literal text,
   so the external-link arrow renders as the visible characters 97. Doubling it emits a
   real CSS escape for U+2197. (This comment deliberately avoids writing the sequence
   out, because doing so reproduces the very bug it describes.) */
.prec-link::after{content:"\\2197";margin-left:3px;font-size:.8em;font-weight:400;color:var(--muted)}
.gt:focus-visible{outline:2px solid var(--primary-600);outline-offset:2px;border-radius:2px}
.gt-def{display:none;position:absolute;left:0;bottom:calc(100% + 9px);z-index:60;
 width:max-content;max-width:min(320px,70vw);background:var(--neutral-950);color:var(--neutral-100);
 font-size:12.5px;line-height:1.5;font-weight:400;text-align:left;white-space:normal;
 padding:9px 12px;border-radius:var(--radius-sm);box-shadow:0 5px 16px rgba(9,30,66,.3)}
.gt-def::after{content:"";position:absolute;top:100%;left:15px;border:5px solid transparent;
 border-top-color:var(--neutral-950)}
.gt-def.gt-right{left:auto;right:0}.gt-def.gt-right::after{left:auto;right:15px}
.gt-def.gt-below{bottom:auto;top:calc(100% + 9px)}
.gt-def.gt-below::after{top:auto;bottom:100%;border-top-color:transparent;border-bottom-color:var(--neutral-950)}
/* :focus-within matters because the precedent cells wrap a real <a> — a Tab press
   lands on the anchor, not on the .gt span, and .gt:focus does not match when it is
   merely an ancestor of the focused element. Without this the popover is unreachable
   by keyboard on exactly the rows that have a link. */
.gt:hover .gt-def,.gt:focus .gt-def,.gt:focus-within .gt-def,.gt.gt-open .gt-def{display:block;animation:gtIn .13s ease both}
@keyframes gtIn{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.gt:hover .gt-def,.gt:focus .gt-def,.gt:focus-within .gt-def,.gt.gt-open .gt-def{animation:none}}
footer p{margin:0 0 9px;max-width:88ch}
footer .stamp{margin-top:13px;padding-top:10px;border-top:1px solid var(--border);
 font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.card .s a{color:var(--primary-600)}
th.s{cursor:pointer;user-select:none;white-space:nowrap}
th.s:hover{color:var(--primary-600)}
th.s:focus-visible{outline:2px solid var(--primary-600);outline-offset:-2px}
th.s::after{content:"";display:inline-block;width:0;height:0;margin-left:5px;
 vertical-align:middle;border-left:4px solid transparent;border-right:4px solid transparent;
 border-top:5px solid var(--neutral-350)}
th.s[aria-sort="ascending"]::after{border-top:0;border-bottom:5px solid var(--primary-600)}
th.s[aria-sort="descending"]::after{border-top:5px solid var(--primary-600)}
</style></head><body><div class="wrap">
<header>
<div class="hgroup">
<h1>AAO decisions dashboard</h1>
<p class="meta">What actually happens when a denied EB-2 or national interest waiver petition is
appealed, counted from the decisions themselves. Hover any underlined term for a definition.</p>
</div>
<div class="tog" role="group" aria-label="Theme">
  <button type="button" data-t="light" aria-pressed="false">Light</button>
  <button type="button" data-t="dark" aria-pressed="false">Dark</button>
  <button type="button" data-t="system" aria-pressed="true">System</button>
</div>
</header>""".replace("DECISION_COUNT", "{:,}".format(n)))

    # ---------------- stat cards ----------------
    A('<div class="cards">')
    A(card("Decisions indexed", "{:,}".format(n),
           'of <strong>5,122</strong> published for 2015 to 2026. '
           '<a href="https://www.uscis.gov/administrative-appeals/aao-decisions/'
           'aao-non-precedent-decisions?uri_1=18&amp;m=All&amp;y=All&amp;items_per_page=100" '
           'target="_blank" rel="noopener noreferrer">Browse the source listing</a>'))
    A(card("Dismissal rate", "%.0f%%" % pct(om["dismissed"], nm),
           "%d of %d decided on the merits" % (om["dismissed"], nm)))
    A(card("Remand rate", "%.0f%%" % pct(om["remanded"], nm),
           "%d sent back to be decided again" % om["remanded"]))
    sus = om["sustained"]
    A(card("Sustained rate",
           "%.0f%%" % pct(sus, nm) if sus else "0",
           "%d outright wins, the rarest outcome" % sus))
    A('</div>')

    if not sus:
        A('<div class="note warn"><h4>The number that should set expectations</h4>'
          '<strong>Zero</strong> sustained appeals in %d merits decisions. Not a low rate, none at '
          'all. A third-party index covering 4,167 NIW cases reports 2%%, and a separate corpus of '
          '143 found one in 129. Three independent counts agree that winning an NIW appeal outright '
          'is close to unheard of, which is the strongest argument for getting the petition right '
          'the first time and refiling rather than appealing.</div>' % nm)

    # ---------------- outcomes + prongs ----------------
    A('<div class="grid2">')
    A('<div class="panel"><h3>How appeals actually end</h3><table><tbody>')
    # Dismissal is the norm here, not an alarm, so it gets the neutral grey. Green
    # marks a remand, amber marks the rare outright win.
    tones = {"dismissed": "d", "remanded": "b", "sustained": "c",
             "motion_dismissed": "d", "abandoned": "d", "unparsed": "d"}
    for k, v in oc.most_common():
        A('<tr><td>%s</td><td class="num">%d</td><td>%s</td><td class="num">%.1f%%</td></tr>'
          % (t(k.replace("_", " ")), v, bar(pct(v, n), tones.get(k, "a")), pct(v, n)))
    A('</tbody></table><p class="hint">Motions to reopen or reconsider are a different '
      'posture from an appeal, so the rate cards above exclude them.</p></div>')

    A('<div class="panel"><h3>Which prong decided it</h3><table><tbody>')
    for p_ in (1, 2, 3):
        c = sum(1 for r in rows if str(p_) in (r["prongs_failed"] or ""))
        A('<tr><td>%s</td><td class="num">%d</td><td>%s</td><td class="num">%.1f%%</td></tr>'
          % (t("Prong %d" % p_), c, bar(pct(c, n), "c" if p_ == 1 else "a"), pct(c, n)))
    sole = sum(1 for r in rows if r["prongs_failed"] == "1")
    dec = sum(1 for r in rows if r["declined_to_reach"])
    none = sum(1 for r in rows if not r["prongs_failed"])
    A('<tr><td>Prong 1 as the sole ground</td><td class="num">%d</td><td>%s</td>'
      '<td class="num">%.1f%%</td></tr>' % (sole, bar(pct(sole, n), "c"), pct(sole, n)))
    A('<tr><td>' + t("AAO") + ' declined to reach later prongs</td><td class="num">%d</td><td>%s</td>'
      '<td class="num">%.1f%%</td></tr>' % (dec, bar(pct(dec, n), "a"), pct(dec, n)))
    A('<tr><td>No prong parsed</td><td class="num">%d</td><td>%s</td>'
      '<td class="num">%.1f%%</td></tr>' % (none, bar(pct(none, n), "a"), pct(none, n)))
    A('</tbody></table><p class="hint">A decision can fail more than one prong. '
      '&ldquo;No prong parsed&rdquo; is left blank rather than guessed.</p></div>')
    A('</div>')

    # ---------------- volume by year ----------------
    years = collections.Counter()
    ybyout = collections.defaultdict(collections.Counter)
    for r in rows:
        y = year_of(r)
        if y:
            years[y] += 1
            ybyout[y][r["outcome"] or "unparsed"] += 1
    if years:
        ys = sorted(years)
        mx = max(years.values())
        W, Hh, pad = 640, 190, 30
        bw = (W - pad * 2) / max(1, len(ys))
        A('<h2>Decision volume by outcome, by year</h2>')
        A('<div class="panel"><svg class="chart" viewBox="0 0 %d %d" role="img" '
          'aria-label="Stacked bars of decision volume by year">' % (W, Hh))
        for g in range(5):
            yy = pad + (Hh - pad * 2) * g / 4.0
            A('<line class="gl" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (pad, yy, W - pad, yy))
            A('<text x="%d" y="%.1f" text-anchor="end">%d</text>'
              % (pad - 4, yy + 3, round(mx * (4 - g) / 4.0)))
        colors = {"dismissed": "var(--neutral-500)", "remanded": "var(--success-600)",
                  "sustained": "var(--amber-400)", "motion_dismissed": "var(--neutral-350)",
                  "abandoned": "var(--neutral-350)", "unparsed": "var(--neutral-250)"}
        for i, y in enumerate(ys):
            x = pad + i * bw + bw * 0.16
            w = bw * 0.68
            acc = 0
            for k in ("dismissed", "motion_dismissed", "remanded", "sustained", "abandoned", "unparsed"):
                c = ybyout[y].get(k, 0)
                if not c:
                    continue
                h = (Hh - pad * 2) * c / float(mx)
                yy = Hh - pad - acc - h
                A('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                  % (x, yy, w, h, colors.get(k, "var(--n250)")))
                acc += h
            A('<text x="%.1f" y="%d" text-anchor="middle">%d</text>'
              % (x + w / 2, Hh - pad + 13, y))
        A('</svg><p class="hint">')
        A(' &nbsp;'.join('<span style="color:%s">&#9632;</span> %s' % (colors[k], k.replace("_", " "))
                         for k in ("dismissed", "motion_dismissed", "remanded", "sustained")))
        A('<br>Our index is weighted to the most recent decisions because the listing is sorted '
          'newest first, so this shows the shape of our sample, not a historical trend.</p></div>')

    # ---------------- precedents ----------------
    A('<h2>The precedents cited most, and what each is cited for</h2>')
    A('<div class="panel"><table><thead><tr><th>Precedent</th><th class="num">Decisions</th>'
      '<th class="num">Share</th><th>Rate</th><th>Cited for</th></tr></thead><tbody>')
    prec = []
    for name in PRECEDENTS:
        c = sum(1 for r in rows if r.get("cite_" + name))
        if c:
            prec.append((c, name))
    for c, name in sorted(prec, reverse=True):
        p = PRECEDENTS[name]
        # The name is both a hover (full citation + what it holds) and a link straight
        # to the primary text, so a reader can go from "cited in 351 decisions" to the
        # actual words in one click. The popover markup mirrors t() so the existing
        # edge-flip script positions it.
        A('<tr><td><span class="gt"><a href="%s" target="_blank" '
          'rel="noopener noreferrer" class="prec-link">%s</a>'
          '<span class="gt-def"><strong>%s</strong><br>%s<br>'
          '<em>Opens the full text on %s.</em></span></span></td>'
          '<td class="num">%d</td><td class="num">%.1f%%</td><td>%s</td><td>%s</td></tr>'
          % (p["url"], p["label"], p["cite"], p["held"],
             E(p["url"].split("/")[2].replace("www.", "")), c, pct(c, n),
             bar(pct(c, n), "e"), p["for"]))
    A('</tbody></table>')
    A('<div class="note good"><h4>Read this ranking carefully</h4>It is mostly a ranking of '
      '<strong>procedural boilerplate</strong>, not of substantive doctrine: Chawathe and '
      '<em>Dhanasar</em> sit within a percentage point of each other because nearly every '
      'decision recites both the burden of proof and the framework. The genuinely '
      'informative entry is <strong>Bagamasbad</strong>: that is the authority for declining to '
      'reach your remaining prongs, so wherever it appears the AAO probably never evaluated '
      'prongs 2 and 3 at all. Hover any name for the full citation and what it holds; click it '
      'to open the decision itself. Two are not AAO decisions at all &mdash; '
      '<strong>Bagamasbad</strong> is a 1976 Supreme Court per curiam, and '
      '<strong>Furtado</strong> is a 2024 BIA decision, the newest authority here.</div></div>')

    # ---------------- adverse language ----------------
    A('<h2>What the AAO actually says when it refuses</h2>')
    A('<p>Counted as the number of decisions containing each formulation at least once. No other '
      'tool in this space measures this.</p>')
    A('<div class="panel"><table><thead><tr><th>Formulation</th><th class="num">Decisions</th>'
      '<th class="num">Share</th><th>Rate</th></tr></thead><tbody>')
    ph = sorted(((sum(1 for r in rows if r.get("ph_" + k)), k) for k in PHRASE_LABEL), reverse=True)
    for c, k in ph:
        if not c:
            continue
        A('<tr><td>%s</td><td class="num">%d</td><td class="num">%.1f%%</td><td>%s</td></tr>'
          % (PHRASE_LABEL[k], c, pct(c, n), bar(pct(c, n), "a")))
    A('</tbody></table><p class="hint">The top line is the whole game: in a large share of these '
      'decisions the AAO had to explain that the importance of your <em>field</em> is not the '
      'question being asked.</p></div>')

    # ---------------- occupations ----------------
    gen = re.compile(r'member of the professions', re.I)
    real = [r for r in rows if r["occupation"] and not gen.match(r["occupation"])]
    counts = collections.Counter()
    assigned = {}
    for r in real:
        for name, pat in OCC_GROUPS:
            if re.search(pat, r["occupation"], re.I):
                counts[name] += 1
                assigned[r["file"]] = name
                break
        else:
            counts["Unclassified"] += 1
            assigned[r["file"]] = "Unclassified"
    A('<h2>Who actually appeals, by their own self-description</h2>')
    A('<p>Parsed from each decision&rsquo;s opening recital in <strong>%d of %d</strong> cases. '
      'The third-party index does not publish this breakdown at all.</p>' % (len(real), n))
    A('<div class="panel"><table><thead><tr><th>Group</th><th class="num">Cases</th>'
      '<th class="num">Share</th><th>Rate</th></tr></thead><tbody>')
    for k, v in counts.most_common():
        tone = "c" if k.startswith("Software") else "a"
        A('<tr><td>%s</td><td class="num">%d</td><td class="num">%.0f%%</td><td>%s</td></tr>'
          % (E(k), v, pct(v, len(real)), bar(pct(v, len(real)), tone)))
    A('</tbody></table>')
    ind = sum(counts[k] for k in counts if k.startswith(("Software", "Engineering", "Business")))
    acad = counts.get("Academic and research", 0)
    A('<div class="note warn"><h4>This is an industry docket, not a researcher&rsquo;s docket</h4>'
      'Software, engineering and business together are <strong>%d of %d (%.0f%%)</strong>. '
      'Academics are <strong>%d (%.0f%%)</strong>. Whatever you have read about the NIW being a '
      'route for researchers, the people losing appeals are overwhelmingly in industry.</div></div>'
      % (ind, len(real), pct(ind, len(real)), acad, pct(acad, len(real))))

    # ---------------- service centre ----------------
    sc = collections.Counter(r.get("service_center") or "" for r in rows)
    named = sum(v for k, v in sc.items() if k)
    if named:
        A('<h2>Which service center denied it</h2>')
        # "pre-2017 format" was backwards. Measured: ~100% named 2015-2024, 44% in 2025,
        # 0% in 2026. USCIS stopped naming the centre partway through 2025.
        A('<p>Named consistently from 2015 through 2024, then dropped: 44%% of 2025 decisions '
          'name it and none of the 2026 ones do. Covers <strong>%d of %d</strong> cases '
          '(%.0f%%). Partial by nature rather than by parser weakness, and left empty '
          'elsewhere rather than guessed.</p>' % (named, n, pct(named, n)))
        A('<div class="panel"><table><thead><tr><th>Service center</th>'
          '<th class="num">Appeals</th><th class="num">Share of named</th><th>Rate</th>'
          '</tr></thead><tbody>')
        for k, v in sc.most_common():
            if not k:
                continue
            A('<tr><td>%s</td><td class="num">%d</td><td class="num">%.0f%%</td><td>%s</td></tr>'
              % (E(k), v, pct(v, named), bar(pct(v, named), "a")))
        A('</tbody></table>')
        A('<p class="hint">One community claim is that the Texas center issues NIW RFEs at roughly '
          'ten times the Nebraska rate. Our counts lean the same way but nowhere near that '
          'strongly, and appeal volume is not the same measurement as RFE rate, so this neither '
          'confirms nor refutes it.</p></div>')

    # ---------------- gaps, stated honestly ----------------
    A('<h2>What this dashboard deliberately does not show</h2>')
    A('<div class="note gap"><h4>Panels we will not fake</h4><ul style="margin:6px 0 0;padding-left:20px">'
      '<li><strong>EB-1A criterion win rates.</strong> Those need each of the ten enumerated '
      'criteria parsed out of EB-1A decisions, and the index holds only a handful of EB-1A cases '
      'so far. Adding it means a criterion parser plus a crawl of <code>uri_1=19</code>.</li>'
      '<li><strong>Coverage is now near-complete, not a recent sample.</strong> An earlier version '
      'of this page said the index was concentrated in recent months and quoted a corpus of '
      '8,934. Both are superseded. Crawling year by year with the year filter set produced '
      '<strong>4,987</strong> decisions spanning 2015 to 2026, against roughly <strong>5,122</strong> '
      'the listing actually exposes for that window &mdash; about 97%. The 8,934 figure came from a '
      'page-summary reading that does not appear in the raw HTML and was never reproducible.</li>'
      '<li><strong>Fields the parser leaves empty.</strong> It records nothing rather than guessing, '
      'so some columns are sparse: no parsed prong for 35.8%, no self-described occupation for '
      '20.9%, no service center for 18.0%, and no date for 4.0% (mostly 2015 decisions whose header '
      'format differs). Percentages on this page are computed over the decisions where the field '
      'was actually found, so a sparse field means a smaller denominator, not a zero.</li></ul></div>')

    # ---------------- searchable table ----------------
    A('<h2>Every decision in the index</h2>')
    A('<div class="ctl">'
      '<input id="q" type="search" placeholder="Filter by occupation, case id, outcome…" '
      'aria-label="Filter decisions">'
      '<select id="fo" aria-label="Outcome"><option value="">All outcomes</option>'
      + "".join('<option>%s</option>' % E(k) for k in sorted(oc)) +
      '</select>'
      '<select id="fp" aria-label="Prong"><option value="">Any prong</option>'
      '<option value="1">Prong 1</option><option value="2">Prong 2</option>'
      '<option value="3">Prong 3</option></select>'
      '<select id="ps" aria-label="Rows per page">'
      '<option value="25" selected>25 per page</option>'
      '<option value="50">50 per page</option>'
      '<option value="100">100 per page</option>'
      '<option value="250">250 per page</option>'
      '</select>'
      '<span class="hint" id="cnt" aria-live="polite"></span></div>')
    # Every sortable/filterable value lives in a data-* attribute rather than being
    # read back out of textContent. That matters because the Outcome cell now carries
    # a hover definition, and its definition text WOULD otherwise be swept into
    # textContent - searching "denial" would then match every dismissed row.
    A('<div class="panel" style="padding-top:6px"><table id="tb"><thead><tr>'
      '<th class="s" data-k="case" aria-sort="ascending" tabindex="0" role="button">Case</th>'
      '<th class="s" data-k="date" tabindex="0" role="button">Date</th>'
      '<th class="s" data-k="outcome" tabindex="0" role="button">Outcome</th>'
      '<th class="s num" data-k="prongs" tabindex="0" role="button">Prongs</th>'
      '<th class="s" data-k="occ" tabindex="0" role="button">Self-described as</th>'
      '</tr></thead><tbody></tbody></table>')
    # Pager BELOW the table as well as above, so you are not scrolling back up on a phone.
    A('<div class="pager" id="pager">'
      '<button type="button" id="pprev" aria-label="Previous page">&larr; Prev</button>'
      '<span id="ppos" aria-live="polite" role="status"></span>'
      '<button type="button" id="pnext" aria-label="Next page">Next &rarr;</button>'
      '</div></div>')

    # The rows ship as JSON, not as 4,987 <tr> elements, and only the current page is
    # ever built into the DOM. Shipping the markup put 45,485 nodes on the page and cost
    # about 1.2s of render on a throttled phone before a reader saw anything - to display
    # 25 rows. Sorting and filtering now run over the array, so they are independent of
    # how many rows are on screen.
    payload = []
    for r in sorted(rows, key=lambda x: x["file"]):
        out = (r["outcome"] or "unparsed").replace("_", " ")
        case = r["file"].replace(".txt", "")
        occ = r["occupation"] or ""
        payload.append({
            "c": case,
            "d": r.get("date") or "",
            "dk": date_key(r.get("date")),
            "o": out,
            "p": r["prongs_failed"] or "",
            "j": occ,
        })
    A('<script type="application/json" id="rowdata">%s</script>'
      % json.dumps(payload, separators=(",", ":")).replace("</", "<\\/"))
    # Outcome tooltips were built server-side per row; the client needs the same text.
    A('<script type="application/json" id="tipdata">%s</script>'
      % json.dumps({k: v for k, v in TIPS.items()}, separators=(",", ":")).replace("</", "<\\/"))
    A('<p class="hint">Click any column heading to sort, click again to reverse. '
      'Hover an outcome for what it means. Rows the parser could not read show an '
      'em-dash and sort to the end rather than being dropped.</p>')

    A("""<footer>
<p><strong>Where these numbers come from.</strong> Every figure is counted from the USCIS decisions
themselves. A script downloads each decision as a PDF, extracts its text, and reads the fields out
using fixed text patterns. No language model is involved at any stage, so nothing here is summarized
or inferred. A field the script cannot read is left blank rather than guessed, and each row stores
the exact sentence it matched, so any number on this page can be traced back to its own PDF.</p>
<p><strong>Source.</strong> The USCIS Administrative Appeals Office publishes its non-precedent
decisions openly. This dashboard reads the EB-2 category, which is where national interest waiver
cases sit.</p>
<p><strong>Privacy.</strong> This is one file that makes no network requests at all. No analytics,
no web fonts, no external scripts. It works offline, and nobody can tell that you opened it.</p>
<p>Not legal advice. To refresh, run <code>aao_index.py fetch</code>, then
<code>aao_index.py parse</code>, then <code>dashboard.py</code>.</p>
<p class="stamp">Local data &middot; DECISION_COUNT decisions indexed &middot; parsed without a
language model</p>
</footer>
<script>
(function(){
 var K='aao_dash_theme';
 function ap(p){var e=p==='system'?((window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'):p;
  document.documentElement.setAttribute('data-theme',e);
  [].forEach.call(document.querySelectorAll('[data-t]'),function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-t')===p));});}
 [].forEach.call(document.querySelectorAll('[data-t]'),function(b){
  b.addEventListener('click',function(){try{localStorage.setItem(K,b.getAttribute('data-t'));}catch(e){} ap(b.getAttribute('data-t'));});});
 ap((function(){try{return localStorage.getItem(K)||'system';}catch(e){return 'system';}})());

 /* ------------------------------------------------------------------
    Table: paginated, and rendered from data rather than from markup.

    All 4,987 rows live in the #rowdata JSON payload. Filtering and sorting run
    over that array; only the current page's rows are ever built into the DOM.
    Shipping every row as markup meant 45,485 DOM nodes and roughly 1.2s of render
    on a 4x-throttled phone before anything was visible - to show 25 rows. It also
    made sorting a layout problem: 667ms per click, because each <tr> was appended
    into the live tbody one at a time. Sorting an array instead is independent of
    how many rows are displayed.

    250 is the deliberate ceiling on rows-per-page. Higher values re-introduce the
    render cost this exists to avoid, and nobody reads 1,000 rows at once.
    ------------------------------------------------------------------ */
 var DATA=JSON.parse(document.getElementById('rowdata').textContent),
     TIP=JSON.parse(document.getElementById('tipdata').textContent),
     q=document.getElementById('q'),fo=document.getElementById('fo'),
     fp=document.getElementById('fp'),ps=document.getElementById('ps'),
     cnt=document.getElementById('cnt'),tbody=document.querySelector('#tb tbody'),
     ppos=document.getElementById('ppos'),pprev=document.getElementById('pprev'),
     pnext=document.getElementById('pnext'),
     view=DATA.slice(), page=0, sortKey='case', sortDir='ascending';

 /* Precompute the lowercase haystack once per row instead of on every keystroke. */
 DATA.forEach(function(r){r._s=(r.c+' '+r.o+' '+r.j).toLowerCase();});

 function esc(x){return String(x==null?'':x).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
 function dash(x){return (x===''||x==null)?'—':esc(x);}

 /* Same markup t() emits server-side, so hover/focus/tap behave identically. */
 function tip(term){
  var d=TIP[term];
  if(!d) return esc(term);
  return '<span class="gt" tabindex="0">'+esc(term)+
         '<span class="gt-def">'+esc(d)+'</span></span>';}

 function sortView(){
  var mult=sortDir==='descending'?-1:1, k=sortKey;
  function keyOf(r){
   if(k==='case')return r.c.toLowerCase();
   if(k==='date')return r.dk;
   if(k==='outcome')return r.o;
   if(k==='prongs')return r.p;
   return (r.j||'').toLowerCase();}
  view.sort(function(a,b){
   var x=keyOf(a), y=keyOf(b);
   /* Blanks sink to the bottom in BOTH directions, so unparsed rows never lead. */
   var xe=(x===''||x==='99999999'), ye=(y===''||y==='99999999');
   if(xe!==ye) return xe?1:-1;
   if(x===y) return a.c<b.c?-1:1;              /* stable: tie-break on case id */
   return x<y?-1*mult:1*mult;});}

 function render(){
  var size=parseInt(ps.value,10)||25,
      pages=Math.max(1,Math.ceil(view.length/size));
  if(page>=pages) page=pages-1;
  if(page<0) page=0;
  var from=page*size, slice=view.slice(from,from+size), h='';
  for(var i=0;i<slice.length;i++){
   var r=slice[i];
   var cls=r.o.indexOf('dismiss')>-1?'no':(r.o==='sustained'?'yes':'');
   h+='<tr><td><code>'+esc(r.c)+'</code></td><td>'+dash(r.d)+'</td>'+
      '<td class="'+cls+'">'+tip(r.o)+'</td>'+
      '<td class="num">'+dash(r.p)+'</td><td>'+dash(r.j)+'</td></tr>';}
  tbody.innerHTML=h||'<tr><td colspan="5" class="hint">No decision matches those filters.</td></tr>';
  cnt.textContent=view.length===DATA.length
    ? DATA.length.toLocaleString()+' decisions'
    : view.length.toLocaleString()+' of '+DATA.length.toLocaleString()+' match';
  ppos.textContent=view.length
    ? 'Page '+(page+1)+' of '+pages+'  ·  showing '+(from+1)+'–'+(from+slice.length)
    : 'no results';
  pprev.disabled=(page===0); pnext.disabled=(page>=pages-1);
  wireTips(tbody);}

 function applyFilters(){
  var s=(q.value||'').toLowerCase().trim(), o=fo.value.replace(/_/g,' '), p=fp.value;
  view=DATA.filter(function(r){
   return (!s||r._s.indexOf(s)>-1) && (!o||r.o===o) && (!p||(r.p||'').indexOf(p)>-1);});
  sortView(); page=0; render();}

 [q,fo,fp].forEach(function(el){
  el.addEventListener('input',applyFilters); el.addEventListener('change',applyFilters);});
 /* Changing page size keeps you near the same records rather than dumping you on page 1. */
 ps.addEventListener('change',function(){
  var size=parseInt(ps.value,10)||25, first=page*(parseInt(ps.getAttribute('data-prev')||'25',10));
  page=Math.floor(first/size); ps.setAttribute('data-prev',ps.value); render();});
 ps.setAttribute('data-prev',ps.value);
 pprev.addEventListener('click',function(){if(page>0){page--;render();
  document.getElementById('tb').scrollIntoView({block:'start'});}});
 pnext.addEventListener('click',function(){page++;render();
  document.getElementById('tb').scrollIntoView({block:'start'});});

 var heads=[].slice.call(document.querySelectorAll('#tb thead th.s'));
 heads.forEach(function(th){
  function go(){
   var cur=th.getAttribute('aria-sort');
   sortDir=cur==='ascending'?'descending':'ascending';
   heads.forEach(function(o){o.removeAttribute('aria-sort');});
   th.setAttribute('aria-sort',sortDir);
   sortKey=th.getAttribute('data-k');
   sortView(); page=0; render();}
  th.addEventListener('click',go);
  th.addEventListener('keydown',function(e){
   if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});});

 /* render() calls wireTips(), declared below; function declarations hoist. */
 sortView(); render();

 /* Tooltips: class-driven so a tap works on touch (no hover), plus edge flipping so
    a bubble never leaves the viewport. */
 function place(sp){var d=sp.querySelector('.gt-def'); if(!d) return;
  d.classList.remove('gt-right','gt-below');
  var r=d.getBoundingClientRect();
  if(r.right>window.innerWidth-8) d.classList.add('gt-right');
  if(r.top<8) d.classList.add('gt-below');}
 function open(sp){sp.classList.add('gt-open');place(sp);}
 function close(sp){sp.classList.remove('gt-open');}
 /* Callable against a subtree, because table rows are now rendered on demand and
    their tooltips do not exist when this first runs. Guarded with a flag so
    re-wiring the same element never stacks duplicate listeners. */
 function wireTips(root){
  [].forEach.call((root||document).querySelectorAll('.gt'),function(sp){
   if(sp.__gtWired) return; sp.__gtWired=true;
   sp.addEventListener('mouseenter',function(){open(sp);});
   sp.addEventListener('mouseleave',function(){close(sp);});
   sp.addEventListener('focus',function(){open(sp);});
   sp.addEventListener('blur',function(){close(sp);});
   sp.addEventListener('click',function(e){e.preventDefault();
    var was=sp.classList.contains('gt-open');
    [].forEach.call(document.querySelectorAll('.gt.gt-open'),close);
    if(!was) open(sp);});
   sp.addEventListener('keydown',function(e){if(e.key==='Escape'){close(sp);sp.blur();}});});}
 wireTips(document);
})();
</script>
</div></body></html>""".replace("DECISION_COUNT", "{:,}".format(n)))
    return "\n".join(H)


def main():
    if not os.path.exists(SRC):
        print("no %s - run: python3 aao_index.py parse" % SRC); sys.exit(1)
    rows = json.load(io.open(SRC, encoding="utf-8"))
    dest = os.path.join(OUT, "dashboard.html")
    io.open(dest, "w", encoding="utf-8").write(build(rows))
    print("wrote %s  (%d decisions, %d bytes)"
          % (dest, len(rows), os.path.getsize(dest)))
    print("open it with:  open '%s'" % dest)


if __name__ == "__main__":
    main()
