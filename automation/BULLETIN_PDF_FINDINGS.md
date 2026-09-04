# Visa Bulletin PDF — findings (2026-08-18)

Investigated whether the direct PDF URL
`https://travel.state.gov/content/dam/visas/Bulletins/visabulletin_<Month><Year>.pdf`
is a firewall-free way to auto-refresh the tool's bulletin data.

## Headline: the PDF URL is NOT firewall-free. Auto-fetch from a script/CI does not work.

Verified with real requests on 2026-08-18:

| Client | Result |
|---|---|
| `curl` + courteous UA | **HTTP 403**, `server: cloudflare`, `__cf_bm` cookie, 4.5 KB HTML challenge (not a PDF) |
| `curl` + browser UA (Chrome/macOS) | **HTTP 403** (August, July, September all 403) |
| Python `urllib` + courteous UA | **HTTP 403 Forbidden** |

The `/content/dam/visas/Bulletins/...pdf` path sits behind the **same Cloudflare bot
management** as the HTML bulletin pages. It downloads in a normal browser only
because the browser executes Cloudflare's JS challenge. A headless script cannot,
and defeating a federal site's bot wall with stealth / TLS-fingerprint / CAPTCHA
tooling is out of bounds — so we do not attempt it.

**Conclusion:** this does not unlock unattended auto-refresh. The project's
deliberate human-gated monthly refresh (see `RUNBOOK.md`) stays.

## What the discovery IS good for

Two concrete wins, both real:

### 1. A one-hop deep link for the paste-in card (browser-side)
The URL pattern is stable and predictable, so instead of the 3-hop site navigation
(index → expand "Fiscal Year 20xx" → click newest month), the paste-in card can link
the user **straight to the current PDF**, which their browser opens fine. Newest-first
candidates (State publishes month N around the 9th of month N-1, so try next month
first, then current):

```
$ python3 automation/bulletin_pdf_fetch.py --urls --date 2026-08-18
September 2026 (next month)   .../visabulletin_September2026.pdf
August 2026 (current month)   .../visabulletin_August2026.pdf
```

The date→URL logic (`latest_bulletin_urls`) handles month names, 4-digit years, and
Dec→Jan fiscal/calendar rollover. Pure string work, no network — safe to use in the
browser tool to build the link. (Because next-month may 404 until it's posted, the
card should offer BOTH links, "newest first," and tell the user to click the newest
that opens.)

### 2. Offline parse of a human-downloaded PDF (no manual transcription)
`pdftotext` (poppler) **is installed** locally (`/opt/homebrew/bin/pdftotext`,
v26.07.0). So the human-in-the-loop flow becomes: open the PDF in a browser (Cloudflare
passes) → Save As → run `bulletin_pdf_fetch.py --parse file.pdf` → get rulebook JSON,
no hand-typing.

```
$ python3 automation/bulletin_pdf_fetch.py --parse ~/Downloads/visabulletin_August2026.pdf
{ "EB-1": { "India": {"final_action_date":"2022-10-15","date_for_filing":"2023-12-01"}, ... }, ... }
```

## Parser approach + validation

- `pdftotext -layout` (column-preserving) → slice the text between the
  "A. FINAL ACTION DATES FOR EMPLOYMENT-BASED…" and
  "B. DATES FOR FILING OF EMPLOYMENT-BASED…" headings → read the `1st`/`2nd`/`3rd`
  rows from each slice.
- Row regex anchors on the exact labels `1st|2nd|3rd` at line start, so the
  **"Other Workers" row (which follows 3rd, same India date) never matches**, and
  neither does `4th`. This was the main correctness trap and it's handled.
- Date tokens: `DDMONYY` → ISO `YYYY-MM-DD`; `C` → `"CURRENT"`; `U` → `null`.
- Columns map ROW / China / India / Mexico / Philippines; prefs map
  1st→EB-1, 2nd→EB-2, 3rd→EB-3.

**Validation status:** the parser logic (slicing + row regex + date tokens) was run
against the REAL August 2026 table text and produced the correct values:

| | FAD | DFF |
|---|---|---|
| EB-1 India | 2022-10-15 | 2023-12-01 |
| EB-2 India | Unavailable (null) | 2015-01-15 |
| EB-3 India | 2014-01-01 | 2015-01-15 |

It has NOT yet been run end-to-end against a real downloaded `.pdf` (couldn't fetch
one here — 403). Before trusting it, download one real bulletin PDF in a browser and
run `--parse` on it, since `pdftotext -layout` whitespace could differ slightly from
the test fixture (the regex tolerates variable whitespace, so this is low-risk but
worth one real check).

## Recommended integration

1. **Keep the paste-in feature** as the primary end-user path — it needs no tooling,
   works when everything else breaks, and lets users verify.
2. **Improve the paste-in link-out** to use the direct PDF URL(s) from
   `latest_bulletin_urls()` (one hop, browser-openable) instead of the 3-hop nav.
   (Wire this into `index.html` separately — not done here.)
3. **Refresh pipeline (local / human, not CI):** when doing the monthly refresh, a
   human downloads the PDF in a browser and runs `bulletin_pdf_fetch.py --parse` to
   generate the numbers, then feeds them through the existing
   `diff_proposal.py` → human review → `apply_proposal.py` gate. This removes manual
   transcription while KEEPING the human verification the runbook requires.
4. **Do NOT** wire the PDF fetch into GitHub Actions expecting it to succeed — it will
   403. If unattended auto-refresh is ever wanted, that's a separate problem (paid
   bulletin API, or an allowlisted fetch path) — not this URL.

## Risks
- **URL pattern can change** — State controls the `/content/dam/.../visabulletin_*.pdf`
  scheme; if they rename, both the deep link and the parser input break.
- **PDF layout can change** — the A/B heading text or column order could shift and
  break the slice/regex. The parser fails loudly (raises) rather than emitting wrong
  data, which is the safe behavior.
- **Human gate stays** — bulletin numbers are load-bearing; the runbook human-gates
  them for a reason (an automated mirror has disagreed with the official source
  before). Auto-applying parsed PDF output without review is not recommended.

## Files
- `automation/bulletin_pdf_fetch.py` — URL builder (`--urls`) + PDF parser (`--parse`).
- `automation/BULLETIN_PDF_FINDINGS.md` — this document.
