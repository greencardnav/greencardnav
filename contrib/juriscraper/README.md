# contrib/juriscraper — proposed AAO scraper for Free Law Project

`aao.py` is a [juriscraper](https://github.com/freelawproject/juriscraper) scraper
for the **USCIS Administrative Appeals Office** non-precedent decisions.

It lives here rather than in a juriscraper checkout because the first version was
written in `/tmp` and destroyed when that was cleared. This directory is
version-controlled; `/tmp` is not. That is the entire reason the file is here.

## Why it's worth contributing

**Verified 2026-09-07 against juriscraper at commit `e4c2aef`:** there is no `aao`
scraper, and the string `aao` does not appear anywhere in the tree. The
`administrative_agency` package ships eight scrapers — `asbca`, `bia`, `bva`,
`mspb_p`, `mspb_u`, `olc`, `ttab`.

An earlier version of this file said FLP "declares 42 federal-special
jurisdictions and ships scrapers for 9 of them, `aao` is declared but has no
scraper." **The "declared" half was never verified against this repository** and
has been removed. Whether CourtListener's court table lists `aao` is a separate
question about a different repo that I have not checked. What is checkable, and
checked, is that juriscraper has no scraper for it.

There is also no bulk-data donation path, only code contributions, so a scraper is
the route this corpus would reach CourtListener.

## Verification status — READ THIS

**Verified against real markup AND through juriscraper's own test harness.**

```
python3 contrib/juriscraper/test_aao.py     # 33 checks, no network, no juriscraper needed
```

`test_aao.py` exists precisely because the original version's verification was
lost with `/tmp`. It covers construction, all six date formats, the ordinal year
facet including out-of-range rejection, row filtering against fixture markup, and
the backscrape iterable. It found **two real bugs during the rebuild**: the date
parser truncated to `value[:19]`, stripping the `Z` so ISO input could never match,
and `_process_html` then discarded every case for want of a date — returning zero
results with no error. A silent total failure that tests caught and inspection did
not.

`aao_example.html` is a **real listing page** fetched 2026-09-06 (results region
only, 10 rows). Against it the scraper extracts **10/10 cases** with correct ISO
dates, `err/*.pdf` URLs and titles. That fetch also corrected a reconstructed
assumption: the listing emits **zero** `<time datetime>` attributes, so the
visible-text date path is the real one and the attribute lookup is defensive only.
An earlier comment calling the attribute the "primary path" was wrong.

**FLP harness: PASSING.** Run 2026-09-07 against juriscraper at commit `e4c2aef`
in a venv (`pip install -e .`), with `aao.py` copied into
`juriscraper/opinions/united_states/administrative_agency/` and `"aao"` added to
that package's `__all__`:

```
tests/local/test_ScraperExampleTest.py -k admin
  -> 1 passed, 8 subtests passed
  -> "8 scrapers tested successfully against 8 example files, 0 speed warnings"
```

`aao_example.compare.json` here is the file FLP's harness generated and then
compared against: 10 entries, 10 distinct case names, no size suffixes.

**That harness caught a bug this project's own tests missed.** The first fixture
was cut out with a regex that did not balance closing `</div>` tags, so every
`views-row` nested the rows after it and each `case_name` came out as all
remaining titles concatenated. The offline suite passed anyway, because it only
asserted `name` was non-empty and the console output was truncated to 42
characters. The fixture is now built by serialising the real row elements with
lxml, and the suite asserts names are distinct, suffix-free and under 200 chars.
The scraper itself was never wrong — verified against the unmodified full page.

**Pagination is deliberately not implemented, and that matches FLP convention.**
An earlier version of this file listed it as required before submitting. Checked
against the repo: `mspb_p`, `mspb_u`, `bva`, `bia` and `ttab` contain **zero**
page or pagination handling. FLP scrapers read the current page each run and rely
on frequent runs plus `_download_backwards` for history, which is what this
scraper does. `_build_url` takes a `page` argument if a reviewer wants it.

Still open before submitting upstream:
- confirmation that `name` should carry the benefit category. The listing has no
  case caption — AAO redacts identity — so `name` currently holds the decision
  category, e.g. "Immigrant Petition for Alien Worker (Advanced Degree…)". That is
  the only human-readable label available, but FLP may want something else.

What it *is* built on: the query parameters and PDF-link pattern verified in
`../../aao-indexer/aao_index.py`, which fetches this listing successfully
(`uri_1`, `m=All`, `y=<ordinal>`, `items_per_page`, `page`; PDFs under
`/sites/default/files/err/`).

Before submitting upstream:

1. `git clone https://github.com/freelawproject/juriscraper && cd juriscraper`
2. `pip install -e .`
3. Copy `aao.py` to `juriscraper/opinions/united_states/administrative_agency/`
4. Add `"aao"` to that package's `__init__.py` `__all__`
5. Build the fixture pair `tests/examples/opinions/united_states/aao_example.html`
   and `aao_example.compare.json`
6. `python tests/tests.py` and fix what breaks
7. Sign the CLA (`legal@free.law`); juriscraper is BSD-2-Clause

## Two design decisions that will look wrong and aren't

**`docket` is the empty string.** AAO publishes no docket number — its decisions
are cited by the redacted `Matter of X-` caption plus the decision date, and the
receipt number is deliberately withheld from the published PDF. juriscraper
requires the key, so it is present but empty. Deriving a pseudo-docket from the
USCIS filename would produce something that *looks* like a citation while being an
artifact of file naming.

**The year facet takes an ordinal, not a year.** `y=1` is the current year, `y=2`
the previous one, up to 22 options. Passing `y=2024` returns zero rows **silently**
rather than erroring, so a naive year filter appears to work while scraping
nothing. `_year_ordinal()` converts and raises on out-of-range input instead.

## Not legal advice

Educational and research material. Not legal advice and not official guidance.
