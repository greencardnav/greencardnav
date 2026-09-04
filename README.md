# Green Card Navigator

An independent, non-commercial educational tool for U.S. employment-based green
card timelines, built only on primary government sources.

Live at **https://www.greencardnav.com**

Not legal advice and not official guidance. Check with your employer's
immigration counsel or a licensed immigration attorney before making any
decisions.

---

## Why this exists

Most tools in this space either restate the Visa Bulletin without explaining what
it means for a given case, or summarise legal documents with a language model and
present the result as fact. Both leave the reader unable to check anything.

This one takes the opposite approach: every number is traceable to a named
government source, and every parsed field records the span of source text it came
from, so any row can be audited against the original document.

## What is in here

| Piece | What it does |
|---|---|
| Static site | 18 pages, no backend, no accounts, no server-side storage of anything you enter |
| Queue projector | Visa Bulletin cutoff history with a projected wait, per category and country |
| AAO decision indexer | Deterministic parse of 4,990 published USCIS Administrative Appeals Office non-precedent decisions |
| Data automation | Monthly and weekly fetch/diff/apply pipelines over official sources |
| Test suites | Static smoke checks, a headless-Chrome interactive audit with WCAG 2 A/AA, a mobile-viewport audit, and a persona regression matrix |

## Primary sources

Nothing here is scraped from an aggregator when a primary source exists.

- Department of State **Visa Bulletin** (fetched via the Internet Archive, since
  `travel.state.gov` blocks scripted clients)
- DOL **PERM disclosure data** (`flag.dol.gov`)
- USCIS **pending I-485 inventory**
- USCIS **Administrative Appeals Office** non-precedent decisions
- **Federal Register API** (queried by RIN, not by agency — agency-scoped queries
  silently miss rules filed under a different parent agency)
- **eCFR** (8 CFR, 20 CFR, 22 CFR)
- **CourtListener** for litigation dockets

Cloudflare-walled sources are never fetched by automation. Where a source blocks
scripted access, the pipeline either uses the Internet Archive's public capture
or the file is downloaded by hand and parsed locally. That boundary is
deliberate and documented in `automation/RUNBOOK.md`.

## The decision indexer

`aao-indexer/aao_index.py` builds a searchable index of published AAO decisions.

It has **no third-party dependencies** (Python standard library plus the
`pdftotext` binary) and makes **no model calls**. Every field is a regex over the
decision's own words, and the matched span is stored alongside the value, so a
row can be checked against the source PDF. A field it cannot parse is left empty
rather than guessed.

That design is a response to a specific failure mode: tools that summarise these
decisions with a language model have published outcome labels that contradict the
PDF. A deterministic parse can be wrong, but it can always be checked, and it
costs nothing to run.

Known limits, stated rather than hidden:

- Decision dates come from the USCIS filename where possible; body-text dates are
  a documented fallback and disagreements are flagged, not silently resolved
- OCR digit damage (`i`/`1`, `o`/`0`) is **flagged, not auto-corrected** — a
  "correction" produces a different wrong word, which is worse than a visible flag
- The `is_niw` field records whether a decision actually mentions a national
  interest waiver, so you can filter honestly instead of trusting a category label
- Per-case identifiers are deliberately not published

The raw PDF cache (~2.6 GB) and derived output are not committed. Both are
reproducible from the public USCIS listing; see `aao-indexer/README.md` for the
exact URL pattern.

## Reproducing the data

`automation/RUNBOOK.md` documents the full refresh: fetch, diff, human review,
apply, deploy. Two properties worth knowing:

- A cutoff cell already marked `verified: true` cannot be moved silently. Any
  change to one blocks the automated path and requires review.
- The monthly and weekly jobs are deterministic Python. No model is in the
  data path at any point.

## Licensing

Two licenses, on purpose:

- **Code** — MIT. See [`LICENSE`](LICENSE).
- **Data and written content** — CC BY 4.0. See [`LICENSE-DATA`](LICENSE-DATA).
  Use it freely, including commercially; just credit it.

Underlying federal government works are public domain and not claimed here.
[`NOTICE`](NOTICE) spells out exactly which files fall under which license.

If you use the decision dataset in research or writing, a citation is in
`LICENSE-DATA`, and I would genuinely like to hear about it.

## Corrections

If a number here disagrees with a primary source, the primary source is right.
Open an issue with the source document and I will fix it.
