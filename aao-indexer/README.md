# aao-indexer

Your own deterministic index of USCIS Administrative Appeals Office non-precedent decisions.

Research tooling. The scripts live in this repo so they are version-controlled and
recoverable; the data does not.

---

## Read this before wiring anything up

**This is a manual research tool. It is NOT part of the site's automation, and it must
never be wired into it.**

`aao_index.py fetch` requests `uscis.gov` with a browser User-Agent. That is fine for
read-only research a human runs and watches. It is explicitly **not** allowed in the
site's monthly refresh pipeline: `automation/RUNBOOK.md` and
`automation/BULLETIN_PDF_FINDINGS.md` record that `uscis.gov` and `travel.state.gov` sit
behind a Cloudflare bot wall, and that the automation reaches government sources only
through **archive.org**, never by presenting a browser UA. Keep that boundary:

- Nothing in `automation/` may import or shell out to `aao_index.py`.
- No cron, launchd job, or GitHub Action may run `fetch`.
- If a scheduled AAO refresh is ever wanted, it goes through archive.org like the Visa
  Bulletin flow does, or it does not happen.

Nothing here is published to the Amplify site today. The generated `out/dashboard.html`
is a local artifact you open from disk. Publishing it as a real page would mean a
deliberate conversion to the gcnav shell (nav, canonical/OG meta, sitemap, search index,
smoke + mobile + axe coverage), not dropping the self-contained file into the web root.

## What is versioned and what is not

Committed: `aao_index.py`, `dashboard.py`, this README.

Gitignored, and why:

| Path | Size | Why it stays out |
|---|---|---|
| `cache/` | ~2.6 GB | Public AAO PDFs, re-downloadable from USCIS. Never belongs in git. |
| `out/dashboard.html` | ~345 KB | Regenerated from `decisions.json` in about a second. |
| `out/decisions.json`, `out/decisions.csv` | ~560 KB | Carries per-case identifiers lifted from the published PDFs, and **this repo is public**. Rebuild with `parse`, which reads the local cache and needs no network. |

So the expensive artifact (the crawl) is local, the sensitive artifact is local, and the
logic — the part that is actually hard to recreate — is in git.

**Working layout.** The canonical copies are here in the repo. `~/aao-indexer/` holds
`cache/` and `out/` plus symlinks back to these three files, so you can keep running the
tool from there against the existing 2.6 GB cache. `os.path.abspath` does not resolve
symlinks, so `HERE` still resolves to `~/aao-indexer` and the data paths are unchanged.
Edit the files here; there is only one copy.

---

## Where every one of those sites gets its data

Short answer: **one free public dataset, and nothing else.**

```
https://www.uscis.gov/administrative-appeals/aao-decisions/aao-non-precedent-decisions
    ?uri_1=<category>&m=All&y=All&items_per_page=100&page=<0-based>
```

| `uri_1` | Category | What lives there |
|---|---|---|
| `18` | B5 — Advanced Degree / Exceptional Ability | EB-2, **including NIW** |
| `19` | B2 — Extraordinary Ability | EB-1A |

Each row links a PDF whose filename *is* the case identifier, e.g.
`OCT272025_03B5203.pdf` = decided 27 Oct 2025, third B5 decision that day. Those are the exact
identifiers casereviewer.ai displays (`MAY072026_03B5203`), which is how you can tell it is the same
source.

**The pipeline every one of these tools runs:**

1. Crawl the listing above.
2. Download the PDFs.
3. Hand each PDF to an LLM to summarize and categorize.
4. Store the summary, link the original PDF.

That is not a guess. The author of casereviewer.ai described it himself in public:
*"Download the pdf from the AAO website. Give it to ChatGPT to summarize with a prompt. Post the
summary to the website, add all relevant categories and also include a link to the original pdf ...
So apart from getting the summary everything else is manual."*

So there is **no proprietary data anywhere in this space.** The differentiation is purely in the
parsing and presentation, which is why building our own is worth an hour.

### Reconciling the case counts

- USCIS reports **~8,934** rows under `uri_1=18`.
- casereviewer.ai reports **4,167** EB-2 NIW cases.

Both can be true: `uri_1=18` holds **both** NIW and non-NIW EB-2 decisions, so 4,167 is a plausible
NIW-only subset. This tool does not take a label on faith — it records whether each decision
actually contains the phrase "national interest waiver" (`is_niw`) so you can filter on the
document's own words.

---

## Why this exists rather than using theirs

**Their summaries are LLM-generated, and there is a confirmed error.** In casereviewer.ai's own
launch thread a reader found a case labelled as denied where the PDF showed the prongs were met and
the appeal sustained. The author acknowledged it, fixed it, and now links the source PDF on every
entry precisely because *"mistakes like this are possible."*

**So this tool contains no LLM.** Every field is a regex over the decision's own words. It also
stores `outcome_evidence`, the literal matched text, so any row can be audited against the PDF in
seconds. A field it cannot parse is left **empty rather than guessed**. Cost: zero, versus the
$30–$40 in API calls an equivalent open-source script needs for a full run.

---

## Usage

```bash
python3 aao_index.py fetch --category niw --pages 4     # crawl + cache (resumable)
python3 aao_index.py parse                              # cache -> out/decisions.{csv,json}
python3 aao_index.py report                             # aggregates
python3 aao_index.py search --occupation software        # query the index
python3 aao_index.py search --prong 1 --outcome dismissed
python3 aao_index.py all --category niw --pages 4       # all three
```

Requires only the Python standard library plus `pdftotext` (poppler). No packages, no API keys.

`fetch` is resumable and skips anything already cached, so re-running is cheap. It crawls at a
1 second delay with a browser User-Agent. **This is interactive read-only research and is
deliberately not wired into any scheduled job** — the site automation goes through archive.org
instead, per `RUNBOOK.md`.

## What it extracts

| Field | How |
|---|---|
| `case_id`, `date` | The `In Re:` / `Date:` header |
| `outcome` | The `ORDER:` line — dismissed, sustained, remanded, abandoned, motion_* |
| `outcome_evidence` | The literal matched text, for auditing |
| `occupation` | The opening recital `"The Petitioner, a ___, seeks"`, intro only |
| `prongs_failed` | Tight per-prong failure language |
| `declined_to_reach` | Whether the AAO reserved prongs 2 and 3 as unnecessary |
| `is_niw`, `route`, `bach_plus_5` | Whether NIW; advanced degree vs exceptional ability; the bachelor's-plus-five-years route |
| `cite_*` | Chawathe, Dhanasar, Bagamasbad, Christo's, Katigbak, Izummi, Furtado |
| `ph_*` | Counts of recurring adverse language (conclusory, generalized, speculative, beyond_employer, ...) |

### Two parsing rules learned the hard way

1. **Never keyword-match a whole legal document.** A first attempt classified "software/IT" in 49 of
   51 decisions because patterns like `\bIT \b` hit boilerplate. Parse the *specific* recital
   instead.
2. **Reject sentence fragments.** The occupation fallback regex happily returned
   *"specific endeavor he proposes to undertake"*. Anything containing a pronoun or verb is now
   rejected outright rather than emitted as a job title.

## The precedents, verified from the text

Every citation below was read out of the decision PDFs in this corpus, so it is what the
AAO literally cites rather than a secondhand summary. Shares are across 566 decisions.
In the dashboard each name is a hover (full citation plus what it holds) and a link
straight to the primary text; every URL was checked to return HTTP 200.

| Precedent | Share | Cited for |
|---|---|---|
| [**Matter of Chawathe**, 25 I&N Dec. 369 (AAO 2010)](https://www.justice.gov/eoir/vll/intdec/vol25/3700.pdf) | 86.6% | The **preponderance of the evidence** burden |
| [**Matter of Dhanasar**, 26 I&N Dec. 884 (AAO 2016)](https://www.justice.gov/media/871246/dl?inline) | 77.0% | The **three-prong NIW framework** |
| [**INS v. Bagamasbad**, 429 U.S. 24 (1976)](https://www.law.cornell.edu/supremecourt/text/429/24) | 62.0% | Agencies need not make findings on issues unnecessary to the result — **this is the authority for declining to reach prongs 2 and 3** |
| [**Matter of Christo's, Inc.**, 26 I&N Dec. 537 (AAO 2015)](https://www.justice.gov/sites/default/files/eoir/pages/attachments/2015/04/16/3831.pdf) | 37.1% | **De novo** review |
| [**Matter of Katigbak**, 14 I&N Dec. 45 (Reg'l Comm'r 1971)](https://www.justice.gov/eoir/vll/intdec/vol14/2125.pdf) | 13.6% | Eligibility is **fixed at the time of filing** |
| [**Matter of Izummi**, 22 I&N Dec. 169 (Assoc. Comm'r 1998)](https://www.justice.gov/eoir/vll/intdec/vol22/3360.pdf) | 5.5% | You **cannot cure** eligibility after filing |
| [**Matter of Furtado**, 28 I&N Dec. 794 (BIA 2024)](https://www.justice.gov/eoir/media/1352416/dl?inline) | 1.2% | Refusing **new evidence first raised on appeal** when you had notice of the gap |

A ranking by citation count is mostly a ranking of **procedural boilerplate**, not of substantive
doctrine. Chawathe outranks Dhanasar only because every decision recites the burden standard.

**Two of the seven are not AAO decisions**, which is easy to miss:

- **Bagamasbad** is a 1976 **Supreme Court** per curiam, not an immigration decision at all.
  It is absent from the DHS/AAO/INS decisions index for that reason.
- **Furtado** is a 2024 **BIA** decision, so it lives in the AG/BIA volumes
  (`justice.gov/eoir/volume-28`, interim decision 4075) rather than the AAO series. It is
  also the newest authority the AAO leans on here.
