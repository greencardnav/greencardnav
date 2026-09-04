#!/usr/bin/env python3
"""
wayback_fetch.py — fetch a public document from the Internet Archive's Wayback
Machine (archive.org), deterministically and with NO Cloudflare bypass.

WHY THIS EXISTS (the honest boundary)
-------------------------------------
travel.state.gov and uscis.gov are Cloudflare bot-walled: they 403 scripted
clients, and this project does NOT defeat that wall with stealth/TLS-spoof
tooling (see RUNBOOK.md / EMAIL_SETUP.md / bulletin_pdf_fetch.py). The Wayback
Machine, however, keeps its OWN archived copy of those public pages/PDFs and
serves them from archive.org over a plain, unauthenticated HTTP + JSON API that
does NOT bot-wall scripts. So we read the ARCHIVED copy from archive.org — a
legitimate public mirror — instead of hammering (or evading) the origin.

Verified 2026-08-26: the official Visa Bulletin PDFs ARE archived, e.g.
travel.state.gov/.../visabulletin_September2026.pdf was captured 2026-08-23 and
serves as application/pdf, 200, byte-for-byte parseable to the same numbers as
the human-downloaded official PDF.

WHAT IT DOES
------------
- `--check <original_url>`: query the Wayback availability API and report whether
  a snapshot exists (+ its timestamp/URL). Exit 0 if available, 3 if not.
- `--save <original_url> --out <path>`: download the ARCHIVED ORIGINAL bytes
  (using the Wayback `id_` raw modifier, which returns the captured file without
  the Wayback toolbar/rewriting) to <path>.

No LLM. stdlib only (urllib, json, argparse). No Cloudflare bypass — archive.org
is the source, and it is not bot-walled.

Personal-learning project. NOT legal advice, NOT official guidance.
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse

WAYBACK_AVAILABLE = "http://archive.org/wayback/available?url="
UA = "gc-monitor/1.0 (personal visa-bulletin tracker; archive.org read-only)"


def _get(url, binary=False, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "")
        status = getattr(r, "status", 200)
    return (data if binary else data.decode("utf-8", "replace")), ctype, status


def latest_snapshot(original_url):
    """Return {'available', 'url', 'timestamp', 'status'} for the closest Wayback
    snapshot of original_url, or None if there is no snapshot. `url` is rewritten
    to the `id_` raw-bytes form so a download returns the captured file itself."""
    q = WAYBACK_AVAILABLE + urllib.parse.quote(original_url, safe="")
    body, _ctype, _status = _get(q)
    info = json.loads(body)
    snap = (info.get("archived_snapshots") or {}).get("closest")
    if not snap or not snap.get("available"):
        return None
    ts = snap.get("timestamp", "")
    # Insert the `id_` modifier after the timestamp so archive.org serves the
    # ORIGINAL archived bytes (no toolbar/HTML rewriting) — essential for PDFs.
    raw_url = snap.get("url", "")
    if ts and ("/web/" + ts + "/") in raw_url:
        raw_url = raw_url.replace("/web/" + ts + "/", "/web/" + ts + "id_/", 1)
    return {"available": True, "url": raw_url, "timestamp": ts, "status": snap.get("status")}


def save(original_url, out_path):
    snap = latest_snapshot(original_url)
    if not snap:
        return None
    data, ctype, status = _get(snap["url"], binary=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return {"path": out_path, "bytes": len(data), "content_type": ctype,
            "http_status": status, "timestamp": snap["timestamp"], "snapshot_url": snap["url"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch a public doc from the Wayback Machine (no Cloudflare bypass).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", metavar="URL", help="Report whether a Wayback snapshot exists for URL.")
    g.add_argument("--save", metavar="URL", help="Download the archived original bytes of URL.")
    ap.add_argument("--out", help="Output path (required with --save).")
    args = ap.parse_args(argv)

    try:
        if args.check:
            snap = latest_snapshot(args.check)
            if snap:
                print(json.dumps({"available": True, **snap}))
                return 0
            print(json.dumps({"available": False, "url": args.check}))
            return 3
        else:
            if not args.out:
                ap.error("--save requires --out")
            res = save(args.save, args.out)
            if not res:
                print(json.dumps({"available": False, "url": args.save}))
                return 3
            print(json.dumps(res))
            # Guard: refuse to call a non-PDF/empty capture a success for .pdf targets.
            if args.save.lower().endswith(".pdf") and "pdf" not in (res["content_type"] or "").lower():
                sys.stderr.write("WARNING: archived capture is not application/pdf (%s)\n" % res["content_type"])
                return 4
            return 0
    except Exception as e:
        sys.stderr.write("wayback_fetch error: %s\n" % e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
