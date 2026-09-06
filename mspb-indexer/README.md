# mspb-indexer

A deterministic index of decisions published by the U.S. Merit Systems Protection
Board (MSPB), the agency that hears federal employees' appeals of adverse personnel
actions — removals, suspensions, demotions, retirement-benefit denials, whistleblower
reprisal claims.

This is the **second corpus in a method**, not a standalone tool. The first is
[`../aao-indexer`](../aao-indexer), over USCIS immigration appeal decisions.

## Why a second corpus

The claim being tested is that outcomes and reasoning in federal administrative
adjudication can be extracted **deterministically** — regular expressions over the
agency's own words, with the matched span stored so any row is auditable, and no model
anywhere in the pipeline.

One corpus cannot support that claim. Two agencies with the same structural shape
(published written decisions, an outcome, a deciding office, stated reasoning) and
entirely unrelated subject matter can. If the approach only worked on immigration it
would be a trick rather than a method.

MSPB also supports analysis the immigration corpus cannot:

| | AAO | MSPB |
|---|---|---|
| Records | 4,990 | **10,669** |
| Deciding offices with usable n | 2 (Texas, Nebraska) | **9 regional offices** |
| Employing-agency dimension | none | **yes** (VA, OPM, USPS, Army, DHS, …) |
| Access | paginated HTML listing | **single JSON manifest** |
| Names in source | redacted by USCIS | **published in full** |

## The identity problem

This is the substantive difference between the two corpora and it drove the design.

USCIS redacts before publishing: its decisions say "Petitioner" and caption as
`MATTER OF S-`. **MSPB does not.** Every record in its manifest carries the appellant's
first and last name, and roughly a third of the filenames embed the full name.

Those names are already public, so nothing here is a secrecy question. But a
structured, searchable index of named individuals' employment disputes is not the same
artifact as the same names scattered across ten thousand agency PDFs — aggregation
collapses the practical obscurity that makes the originals relatively harmless.

So this tool **discards identity at parse time** rather than publishing it and hoping
nobody aggregates:

- `APL_FIRST_NAME`, `APL_LAST_NAME`, `META_KEYWORDS`, `META_TITLE`, `DOCNAME`,
  `FILE_NAME` and `META_AUTHOR` are read **only to redact** and never written to output.
- Names learned from the manifest are scrubbed from every text span the tool stores, so
  quoted evidence cannot leak an identity the structured fields dropped.
- The PDF cache is keyed by **docket plus a short digest**, not the source filename —
  otherwise the cache directory would itself be a listing of who appealed.
- `parse` runs a **per-record de-identification check** and prints a loud warning if any
  record's own appellant name reaches its free text.

**Docket numbers are kept.** A docket number is a case citation, not a name — the same
thing a law review footnote carries — and it preserves auditability: any row can be
checked against the source decision. It also encodes the regional office, which is the
analytical point.

Dropping the names costs nothing. Every question worth asking here is about offices,
agencies, outcomes and reasoning.

## Usage

```
python3 mspb_index.py manifest                    # download the decision manifest
python3 mspb_index.py fetch --sample 500          # reproducible stratified sample
python3 mspb_index.py fetch                       # everything (10,669 PDFs, ~3h)
python3 mspb_index.py parse                       # parse cache -> out/
python3 mspb_index.py report                      # aggregates to stdout
```

`--sample N` spreads the draw across `(year, office)` strata with a fixed seed, because
`--limit N` takes the head of a newest-first manifest and would tell you nothing about
whether the patterns hold on older text or in other offices.

Requires Python 3 standard library plus `pdftotext` (Poppler). No API keys, no packages.

## What it extracts

Outcome (`affirmed`, `reversed`, `remanded`, `vacated`, `mitigated`, `denied`,
`dismissed`, `settled`) with the matched span in `outcome_evidence`; the regional office
from the docket prefix; the employing agency; document type; 13 substantive-issue
counts (removal, whistleblower, USERRA, discrimination, jurisdiction, timeliness, …);
and 6 precedent-citation flags including *Douglas v. Veterans Administration*, the
source of the twelve penalty factors.

Every field is a regex. Unparsed fields are left **empty rather than guessed**.

## Limitations

- **The manifest's `DOCUMENT_CONTENT` is empty on all records**, so reasoning text
  requires fetching and converting the PDFs. Same shape as the AAO pipeline.
- **These are Board decisions, i.e. appeals** of regional-office initial decisions.
  Like the AAO corpus, nothing here supports claims about first-instance rates.
- **Coverage is uneven by year** — dense 2010–2016 and 2022–2026, nearly empty
  2017–2019. That reflects what MSPB has published, not a sampling choice. The Board
  lacked quorum for part of that gap.
- Some docket prefixes in the manifest are malformed (`D,AT`, `AT130368B`, a literal
  agency name). Those parse to an empty office rather than being coerced.
- `outcome` reads the Board's order language. Where a decision affirms in part and
  reverses in part, the first matching pattern wins; treat mixed dispositions with care.

## Source

    https://www.mspb.gov/decisions/nonprecedential.htm
    manifest: /decisions/nonprecedential/NonPrecedentialDecisions_Manifest-updmar2025.json

The site returns 403 to a bare scripted client, so requests carry a browser
user-agent — the same read a browser performs, at a deliberate 1-second delay, slower
than a human clicking through the search interface. Read-only research against public
documents. Not wired into any scheduled automation.

The PDF cache and derived output are gitignored: both are reproducible from the URL
above, and the cache is large.

## Not legal advice

Educational and research material. Not legal advice and not official guidance.
