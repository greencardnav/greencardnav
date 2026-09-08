#!/usr/bin/env python3
"""Offline tests for the proposed AAO juriscraper scraper.

These exist because the first version of `aao.py` was verified against
juriscraper's own suite and then destroyed with `/tmp`, taking the verification
with it. These tests need neither the juriscraper package nor network access, so
they survive in the repo and can be run any time:

    python3 contrib/juriscraper/test_aao.py

Section [5] runs against `aao_example.html`, a real listing page fetched
2026-09-06, so the XPath is checked against actual markup and not only against a
fixture I wrote to match my own assumptions.

They do NOT replace juriscraper's harness -- see README.md for what still has to
be run upstream. They cover the things that actually broke during the rebuild:

  1. Date parsing. The first rebuild truncated to value[:19], stripping the "Z"
     from ISO input so it could never match. `_process_html` then dropped every
     case for want of a date and returned zero results with no error -- a silent
     total failure.
  2. Row filtering. Non-PDF links must be skipped; rows must parse from either
     the <time datetime> attribute or the visible text.
  3. The reconstructed assumption that <time datetime> is the primary date source
     is WRONG for this listing -- live markup has zero of them (asserted in [5]).
     The visible-text fallback carries every date.
"""

import sys
import types
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _stub_juriscraper():
    """Import aao.py without the juriscraper package installed."""
    pkg = types.ModuleType("juriscraper")
    mod = types.ModuleType("juriscraper.OpinionSiteLinear")

    class OpinionSiteLinear:
        def __init__(self, *a, **k):
            self.cases = []
            self.html = None

        def _download(self):
            raise AssertionError("tests must not hit the network")

    mod.OpinionSiteLinear = OpinionSiteLinear
    sys.modules["juriscraper"] = pkg
    sys.modules["juriscraper.OpinionSiteLinear"] = mod
    sys.path.insert(0, HERE)
    import aao
    return aao


FIXTURE = """<div>
  <div class="views-row">
    <div class="views-item-title">
      <a href="/sites/default/files/err/D7/ABC123456_01B2203.pdf">Matter of A-B-</a>
    </div>
    <div class="views-field-field-display-date">
      <time datetime="2024-03-15T00:00:00Z">March 15, 2024</time>
    </div>
  </div>
  <div class="views-row">
    <div class="views-item-title"><a href="/not-a-decision.html">skip me</a></div>
    <div class="views-field-field-display-date">
      <time datetime="2024-01-01T00:00:00Z">January 1, 2024</time>
    </div>
  </div>
  <div class="views-row">
    <div class="views-item-title">
      <a href="/sites/default/files/err/B5/DEF999888_02C1101.pdf">Matter of C-D-</a>
    </div>
    <div class="views-field-field-display-date">June 2, 2023</div>
  </div>
  <div class="views-row">
    <div class="views-item-title">
      <a href="/sites/default/files/err/B5/NODATE111_03.pdf">Matter of No-Date-</a>
    </div>
    <div class="views-field-field-display-date">not a date at all</div>
  </div>
</div>"""

failures = []


def eq(label, got, want):
    ok = got == want
    print("  %-4s %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        print("       got  %r\n       want %r" % (got, want))
        failures.append(label)


def main():
    aao = _stub_juriscraper()
    S = aao.Site()

    print("\n[1] construction")
    eq("court_id is the module name", S.court_id, "aao")
    eq("status is Unpublished", S.status, "Unpublished")
    eq("url spans all categories", "uri_1=All" in S.url, True)
    eq("url requests all years", "y=All" in S.url, True)

    print("\n[2] date parsing -- every format the listing emits")
    for raw, want in [
        (["2024-03-15T00:00:00Z"], "2024-03-15"),   # ISO: defensive, absent on this source
        (["2024-03-15T00:00:00"], "2024-03-15"),
        (["2024-03-15"], "2024-03-15"),
        (["March 15, 2024"], "2024-03-15"),
        (["Mar 15, 2024"], "2024-03-15"),
        (["03/15/2024"], "2024-03-15"),
        ([""], None),
        (["garbage"], None),
        ([], None),
        (["", "2024-03-15"], "2024-03-15"),          # skips empties, keeps looking
    ]:
        eq("parse %r" % (raw,), S._parse_date(raw), want)

    print("\n[3] year facet is an ORDINAL, not a year")
    eq("2026 -> 1", S._year_ordinal(2026), "1")
    eq("2005 -> 22", S._year_ordinal(2005), "22")
    raised = False
    try:
        S._year_ordinal(2004)
    except ValueError:
        raised = True
    eq("out-of-range raises rather than silently returning nothing", raised, True)

    print("\n[4] row extraction")
    import lxml.html
    S.cases = []
    S.html = lxml.html.fromstring(FIXTURE)
    S._process_html()
    eq("2 of 4 rows kept (non-PDF and undated dropped)", len(S.cases), 2)
    if len(S.cases) == 2:
        a, b = S.cases
        eq("first row url", a["url"],
           "/sites/default/files/err/D7/ABC123456_01B2203.pdf")
        eq("synthetic row date via <time datetime>", a["date"], "2024-03-15")
        eq("first row name", a["name"], "Matter of A-B-")
        eq("docket is empty by design, not invented", a["docket"], "")
        eq("second row date from visible text", b["date"], "2023-06-02")
    eq("no non-PDF url survived",
       all(c["url"].lower().endswith(".pdf") for c in S.cases), True)
    eq("every kept case has a date",
       all(c["date"] for c in S.cases), True)

    print("\n[5] REAL markup (aao_example.html, fetched 2026-09-06)")
    real = os.path.join(HERE, "aao_example.html")
    if os.path.exists(real):
        S.cases = []
        S.html = lxml.html.parse(real).getroot()
        S._process_html()
        eq("extracts all 10 rows from the live fixture", len(S.cases), 10)
        eq("every case has an err/ pdf url",
           all("/sites/default/files/err/" in c["url"] and
               c["url"].lower().endswith(".pdf") for c in S.cases), True)
        eq("every case has an ISO date",
           all(len(c["date"]) == 10 and c["date"][4] == "-" for c in S.cases), True)
        eq("every case has a non-empty name",
           all(c["name"] and c["name"] != "Unnamed AAO decision" for c in S.cases), True)
        # These three would have caught the nested-fixture bug that FLP's harness
        # found and this suite originally missed: names were all remaining titles
        # concatenated, and a non-empty check plus a 42-char display hid it.
        eq("names are DISTINCT per row (catches row nesting)",
           len({c["name"] for c in S.cases}), len(S.cases))
        eq("no name carries a (PDF, size) suffix",
           not any("(PDF," in c["name"] for c in S.cases), True)
        eq("no name is absurdly long (concatenation smell)",
           max(len(c["name"]) for c in S.cases) < 200, True)
        eq("docket empty on all (AAO publishes none)",
           {c["docket"] for c in S.cases}, {""})
        # The listing emits NO <time datetime> -- the text fallback carries it.
        eq("live markup really has no <time datetime>",
           len(S.html.xpath("//time/@datetime")), 0)
    else:
        print("  SKIP no aao_example.html")

    print("\n[6] backscrape iterable")
    S.make_backscrape_iterable({})
    eq("one (start, end) pair", len(S.back_scrape_iterable), 1)
    eq("starts at first_opinion_date",
       S.back_scrape_iterable[0][0].year, 2005)

    print()
    if failures:
        print("%d FAILURE(S): %s" % (len(failures), ", ".join(failures)))
    else:
        print("all offline checks passed")
    return len(failures)


def test_offline_checks():
    """Entry point for pytest.

    Without this, `pytest test_aao.py` COLLECTS NOTHING and reports success --
    the checks below are a plain script (a `main()` plus an `eq()` helper), not
    `test_*` functions, so pytest finds no tests and exits 0. A file named
    `test_*.py` that silently runs zero tests is worse than no file: it reads as
    a green suite. Verified by running `pytest test_aao.py` and getting
    "no tests ran in 0.01s" while `python3 test_aao.py` ran all of them.
    """
    assert main() == 0, "%d offline check(s) failed -- see stdout" % len(failures)


if __name__ == "__main__":
    sys.exit(main())
