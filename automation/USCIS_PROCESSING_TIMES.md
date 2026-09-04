# USCIS Processing Times - the legitimate (OAuth) path, and why this field is not automated

Personal-learning project. NOT legal advice, NOT official guidance.

## TL;DR

USCIS form processing times (e.g. Form I-140, Form I-485) are the ONE field in this
tool that is **not automated**, on purpose. There is a real official API for it, but
it is OAuth-gated - obtaining a token is a one-time credential request through the
USCIS developer program, not a scrape. Until those credentials are requested and
granted, the tool LINKS OUT to `egov.uscis.gov/processing-times` (which it already
does in `rulebook.json` -> `i140.regular_processing_source_url`) and the numeric
value stays human-entered / non-verified. This is an **open, documented gap with a
known legitimate resolution** - not a solved automated source.

## Why we do NOT scrape it

Two dead ends, both verified live (2026-08-10):

1. **The egov page + its PDF are bot-walled (HTTP 403).** `egov.uscis.gov/processing-times`
   and the downloadable processing-times PDF return 403 to a plain stdlib client AND to
   a headless browser (the page serves only a Cloudflare "verify you are human"
   interstitial). Bypassing that bot protection is out of bounds. So `fetch_feeds.py`
   and `fetch_bulletin.py` deliberately never touch it. This matches the honest boundary
   already stated in `SETUP.md`.

2. **The official API exists but is OAuth-gated.** `api.uscis.gov/processing-times`
   (and the internal-facing `api-int.uscis.gov/processing-times`) is a REAL official
   USCIS API. Hitting it unauthenticated returns **HTTP 401 with a `WWW-Authenticate:
   Bearer` challenge** (verified live) - i.e. it wants an OAuth 2.0 bearer token. It is
   not open, and there is no unauthenticated read path.

## The legitimate path: request API credentials via the USCIS developer program

USCIS runs a developer program that issues OAuth client credentials for its public
APIs (the same mechanism behind their Case Status API). The processing-times API is
part of that program. The legitimate, in-bounds way to automate this field is:

1. Register / request access at the USCIS developer portal: **developer.uscis.gov**
   (the USCIS Developer Program). This is a one-time human credential request, exactly
   like requesting access to their Case Status API.
2. You receive an OAuth 2.0 **client id + client secret**.
3. At runtime, exchange those for a short-lived **bearer token** via the program's
   OAuth token endpoint (client-credentials grant), then call
   `GET api.uscis.gov/processing-times/...` with `Authorization: Bearer <token>`.
4. The response is structured JSON (form + office/service-center + time range), which
   could then be folded into the monthly facts flow the same way bulletin values are -
   human-gated through `RUNBOOK.md`, never auto-applied.

Key honesty points:
- This is a **credential request, not a scrape**. Nothing about it evades bot
  protection; it uses the front door USCIS provides for programmatic access.
- Until the credentials are obtained, this stays a **manual field**. The tool already
  links out to `egov.uscis.gov/processing-times` (see `rulebook.json`
  `i140.regular_processing_note` / `regular_processing_source_url`), and
  `i140.regular_processing_verified` stays `false`.
- Low leverage anyway: an 8-vs-11-month I-140 is negligible against a multi-year
  priority-date wait (as `rulebook.json` itself notes). So this gap is honest to leave
  open while the credential request is pending.

## What is NOT this

- This is separate from the **Visa Bulletin** facts, which `fetch_bulletin.py` DOES
  approximate via its 3-source quorum (two public-domain community mirrors + the
  Internet Archive of the official page). `fetch_bulletin.py` intentionally does not
  touch USCIS processing times.
- The GovDelivery email-subscription idea in `SETUP.md` section 5 is a different
  (also-legitimate) residual-killer for official alerts; it is not the processing-times
  API and does not replace the OAuth path above.

## Status

Open gap. Resolution known and legitimate (one-time developer.uscis.gov credential
request). Not yet requested. Field remains link-out + non-verified until then.
