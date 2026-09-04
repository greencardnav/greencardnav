#!/usr/bin/env python3
"""
ingest_email.py - EMAIL-INGESTION path for the green card monitor.

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
This closes the ONE gap the unattended fetchers cannot reach: the bot-walled
official sources (USCIS case processing times, the DOS Visa Bulletin release
page, DOL OFLC notices) that 403 a scripted client (see fetch_feeds.py /
SETUP.md "honest boundary"). Those same agencies publish AUTHORIZED email
alerts via GovDelivery. A human subscribes a dedicated inbox ONCE (a click +
double-opt-in confirmation - see EMAIL_SETUP.md); this script then reads the
NEW alert emails over IMAP and converts them into the SAME structured JSON the
rest of the pipeline already speaks:

  --as news   -> items conforming to news_results_schema.json, consumed by
                 news_digest.py exactly like fetch_feeds.py output.
  --as facts  -> a facts-style snapshot conforming to fetch_results_schema.json
                 (Visa Bulletin release / processing-time / fee email) that a
                 HUMAN reviews before diff_proposal.py. This NEVER auto-applies
                 to rulebook.json.

HONEST BOUNDARY (read this)
---------------------------
  - Subscribing is a ONE-TIME HUMAN action. No script can subscribe: GovDelivery
    requires clicking the signup, picking topics, and confirming a double-opt-in
    email. This tool does NOT and cannot subscribe.
  - Reading is automated. This is an AUTHORIZED channel: the agency sends the
    email to an inbox that opted in. There is NO scraping and NO bot-bypass -
    the bot-walled pages are never touched. The Visa Bulletin email is the
    authorized way to receive the bulletin that the 403-walled page blocks; the
    USCIS processing-time emails close the gap that has no API.
  - IMAP is strictly READ-ONLY. We use .fetch (never .store flags) and never
    delete or mark messages read on the server, so the inbox is left untouched
    for the user to also read. Idempotency is tracked locally in
    email_seen_ledger.json (by Message-ID), not by mutating the mailbox.
  - Facts from email are HUMAN-REVIEWED before any rulebook change, the same
    gate as everything else (RUNBOOK.md).

AUTH
----
The IMAP password is read ONLY from the GC_IMAP_PASSWORD environment variable -
NEVER hardcoded, NEVER passed on the CLI (a CLI arg would leak into shell
history and the process table). For Gmail this must be an App Password (requires
2FA); a regular account password will not work for IMAP. If the variable is
unset, the script prints setup guidance and exits 0 (does not crash, does not
connect). See EMAIL_SETUP.md.

Scope: EB-1, EB-2, EB-3, and H-1B ONLY. Personal-learning project. NOT legal
advice, NOT official guidance.

Usage:
  python3 ingest_email.py [--out PATH] [--as news|facts] [--since-days 3]
                          [--host imap.gmail.com] [--user ADDR]
                          [--mailbox INBOX] [--dry-run]

stdlib only: imaplib, email, ssl, json, re, html.parser, hashlib, datetime,
argparse, os, sys, pathlib.
"""

import argparse
import datetime
import email
import email.utils
import hashlib
import imaplib
import json
import os
import re
import ssl
import sys
from email.header import decode_header, make_header
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER_PATH = HERE / "email_seen_ledger.json"

DEFAULT_HOST = "imap.gmail.com"
DEFAULT_MAILBOX = "INBOX"
DEFAULT_SINCE_DAYS = 3
TIMEOUT_SECONDS = 30
ENV_PASSWORD = "GC_IMAP_PASSWORD"

# Senders we trust as GovDelivery / official-alert / practitioner newsletter
# origins. Matched as a substring against the message From header (lowercased).
# GovDelivery relays official agency alerts from these envelope domains; the
# agency tokens catch cases where the display/from carries the agency name.
KNOWN_SENDER_TOKENS = [
    "govdelivery.com",
    "public.govdelivery.com",
    "subscriptions.uscis.dhs.gov",
    "uscis.dhs.gov",
    "uscis.gov",
    "state.gov",
    "travel.state.gov",
    "dol.gov",
    "flag.dol.gov",
    # Law-firm / practitioner newsletter senders (tier-2 authorities that also
    # deliver by email). Kept narrow and explicit - not a generic allowlist.
    "fragomen.com",
    "bal.com",
    "murthy.com",
    "aila.org",
]

# ---------------------------------------------------------------------------
# Precise scope classification - MIRRORS fetch_feeds.py so email-derived items
# classify identically to fetched items (word-boundary, EB-1/EB-2/EB-3/H-1B
# only). Kept in sync deliberately; do not loosen to naive substring.
# ---------------------------------------------------------------------------
CATEGORY_PATTERNS = {
    "H-1B": [
        r"\bH-?1B\b", r"\bspecialty occupation\b", r"\bcap-?subject\b",
        r"\bH-?1B cap\b", r"\bH-?1B lottery\b", r"\bH-?1B registration\b",
    ],
    "EB-1": [
        r"\bEB-?1\b", r"\bextraordinary ability\b", r"\boutstanding researcher\b",
        r"\bmultinational (?:manager|executive)\b",
    ],
    "EB-2": [
        r"\bEB-?2\b", r"\bnational interest waiver\b", r"\bNIW\b",
        r"\badvanced degree\b",
    ],
    "EB-3": [
        r"\bEB-?3\b", r"\bskilled workers?\b",
    ],
}
CROSSCUTTING_PATTERNS = [
    r"\bemployment-based\b", r"\bemployment based\b", r"\bpriority dates?\b",
    r"\bvisa bulletin\b", r"\bPERM\b", r"\bprevailing wage\b",
    r"\blabor certification\b", r"\bI-140\b", r"\bI-485\b",
    r"\badjustment of status\b", r"\bpremium processing\b",
    r"\bform I-907\b", r"\bI-907\b", r"\bgreen cards?\b",
    r"\bemployment-based green card\b", r"\bgreen[- ]card backlog\b",
    r"\bprocessing times?\b", r"\bcase processing\b",
]


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_CATEGORY_RE = {cat: _compile(pats) for cat, pats in CATEGORY_PATTERNS.items()}
_CROSSCUT_RE = _compile(CROSSCUTTING_PATTERNS)

# Topic controlled vocabulary (must match news_results_schema.json enum).
TOPIC_PATTERNS = [
    ("visa-bulletin", ["visa bulletin"]),
    ("rule-making", ["final rule", "proposed rule", "rulemaking", "rule-making",
                     "notice of proposed", "interim rule", "nprm"]),
    ("h1b-lottery", ["lottery", "random selection", "registration selection",
                     "second selection", "cap registration"]),
    ("h1b-cap", ["cap-subject", "cap subject", "cap season", "h-1b cap",
                 "h1b cap", "cap-gap", "cap gap"]),
    ("litigation", ["lawsuit", "litigation", "court", "sues", "injunction",
                    "plaintiff", "ruling", "judge"]),
    ("rfe-trends", ["rfe", "request for evidence", "requests for evidence"]),
    ("priority-dates", ["priority date", "retrogress", "backlog", "date movement",
                        "final action date", "dates for filing"]),
    ("processing-times", ["processing time", "processing times", "pending",
                          "queue", "prevailing wage determination", "pwd",
                          "perm processing", "case processing"]),
]

HIGH_IMPORTANCE_TERMS = ["final rule", "proposed rule", "lottery",
                         "random selection", "fee", "fees", "new visa bulletin",
                         "premium processing", "priority date rule",
                         "wage-selection", "wage selection"]
MEDIUM_IMPORTANCE_TERMS = ["guidance", "policy manual", "rfe",
                           "request for evidence", "processing time",
                           "processing times", "clarifies", "updates"]

# affects_facts gate - a rulebook fact plausibly changed. For email items we
# fire it on ANY known official/GovDelivery sender (tier 1) that is in-scope AND
# mentions a rulebook-relevant token. Practitioner-newsletter senders (tier 2)
# never set it, matching fetch_feeds.py's tier gate.
AFFECTS_FACTS_PATTERNS = [
    r"\bfees?\b", r"\bpriority dates?\b", r"\bvisa bulletin\b",
    r"\bprevailing wage\b", r"\bPERM\b", r"\bfinal rule\b", r"\bH-?1B cap\b",
    r"\bprocessing times?\b",
]
_AFFECTS_FACTS_RE = _compile(AFFECTS_FACTS_PATTERNS)

# Map a sender domain to the pipeline source_id + tier used in the schemas.
# Tier 1 = official government (GovDelivery relays agency alerts); tier 2 =
# law-firm practitioner. Order matters (first substring match wins).
SENDER_SOURCE_MAP = [
    ("subscriptions.uscis.dhs.gov", "govdelivery-uscis", 1),
    ("uscis.dhs.gov", "govdelivery-uscis", 1),
    ("uscis.gov", "govdelivery-uscis", 1),
    ("travel.state.gov", "govdelivery-dos-visa-bulletin", 1),
    ("state.gov", "govdelivery-dos-visa-bulletin", 1),
    ("flag.dol.gov", "govdelivery-dol-oflc", 1),
    ("dol.gov", "govdelivery-dol-oflc", 1),
    ("fragomen.com", "fragomen-insights", 2),
    ("bal.com", "bal-alerts", 2),
    ("murthy.com", "murthy-news", 2),
    ("aila.org", "aila-news", 2),
    # Display-name fallbacks: GovDelivery frequently sends from a generic
    # public.govdelivery.com envelope with the agency named only in the display
    # name (e.g. "USCIS <uscis@public.govdelivery.com>"). Attribute by that
    # agency token BEFORE the generic govdelivery fallback below.
    ("uscis", "govdelivery-uscis", 1),
    ("visa bulletin", "govdelivery-dos-visa-bulletin", 1),
    ("department of state", "govdelivery-dos-visa-bulletin", 1),
    ("oflc", "govdelivery-dol-oflc", 1),
    ("foreign labor", "govdelivery-dol-oflc", 1),
    # Generic GovDelivery relay whose agency we could not pin from the From
    # header at all. Still tier 1 (GovDelivery only relays official alerts), with
    # a generic source_id so the digest can still attribute it.
    ("govdelivery.com", "govdelivery-official", 1),
]


# ---------------------------------------------------------------------------
# Minimal HTML-to-text using stdlib html.parser (no bs4). Drops <script>/<style>
# content, converts a few block tags to newlines, and unescapes entities.
# ---------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "head", "title"}
    _BREAK = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._skip_depth = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)
        if tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def get_text(self):
        return "".join(self._parts)


def html_to_text(html_str):
    """Strip HTML to plain text using only stdlib. Returns collapsed text."""
    parser = _TextExtractor()
    try:
        parser.feed(html_str)
    except Exception:  # noqa: BLE001 - malformed HTML must not kill the run
        pass
    return collapse_ws(parser.get_text()), parser.links


def collapse_ws(text):
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Header / date / id helpers (mirror fetch_feeds.py where shared).
# ---------------------------------------------------------------------------
def decode_hdr(raw):
    """Decode an RFC 2047 encoded header (=?utf-8?...?=) into a str."""
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:  # noqa: BLE001
        return str(raw).strip()


def normalize_title(title):
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


def stable_id(source_id, title, published_date):
    """Stable dedup id, IDENTICAL scheme to fetch_feeds.py so the news_digest
    ledger dedups the SAME story whether it arrived by email or by web fetch:
    sha1(source_id|normalized_title|published_date)[:16]."""
    basis = "%s|%s|%s" % (source_id, normalize_title(title), published_date or "")
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def parse_email_date(raw):
    """Parse an email Date header into YYYY-MM-DD, or None if unparseable."""
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt is not None:
            return dt.date().isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    return None


def sender_source(from_header):
    """Map a From header to (source_id, tier). Returns (None, None) if the
    sender is not a known official / practitioner origin."""
    f = (from_header or "").lower()
    for token, source_id, tier in SENDER_SOURCE_MAP:
        if token in f:
            return source_id, tier
    return None, None


def is_known_sender(from_header):
    f = (from_header or "").lower()
    return any(tok in f for tok in KNOWN_SENDER_TOKENS)


def classify_category(text):
    """In-scope category string, or None if out of scope (identical logic to
    fetch_feeds.py)."""
    t = text or ""
    matched = [cat for cat, res in _CATEGORY_RE.items()
               if any(r.search(t) for r in res)]
    crosscut = any(r.search(t) for r in _CROSSCUT_RE)
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return "cross-cutting"
    if crosscut:
        return "cross-cutting"
    return None


def classify_topic(text):
    t = (text or "").lower()
    for topic, pats in TOPIC_PATTERNS:
        if any(p in t for p in pats):
            return topic
    return "policy"


def classify_importance(text):
    t = (text or "").lower()
    if any(term in t for term in HIGH_IMPORTANCE_TERMS):
        return "high"
    if any(term in t for term in MEDIUM_IMPORTANCE_TERMS):
        return "medium"
    return "low"


def affects_facts_gate(text, tier, in_scope):
    """Fires ONLY for a tier-1 (official/GovDelivery), in-scope item mentioning a
    rulebook-relevant token. Tier-2 practitioner newsletters never set it."""
    if tier != 1 or not in_scope:
        return False
    t = text or ""
    return any(r.search(t) for r in _AFFECTS_FACTS_RE)


def first_sentences(text, n=2):
    """First ~n sentences of the body, for the news summary."""
    text = collapse_ws(text)
    if not text:
        return ""
    # Split on sentence-ending punctuation followed by whitespace.
    parts = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(parts[:n]).strip()
    return summary[:600]


def first_http_link(links):
    for href in links or []:
        if href.startswith("http://") or href.startswith("https://"):
            # Skip GovDelivery tracking/unsubscribe/preference links where we can.
            low = href.lower()
            if any(bad in low for bad in ("unsubscribe", "/subscriber/",
                                          "removal", "preferences")):
                continue
            return href
    # Fall back to the first link at all if only tracking links exist.
    for href in links or []:
        if href.startswith("http"):
            return href
    return ""


# ---------------------------------------------------------------------------
# Email body extraction: prefer text/plain, fall back to text/html stripped.
# ---------------------------------------------------------------------------
def extract_body(msg):
    """Return (body_text, links). Prefers text/plain; strips text/html if that
    is all that exists."""
    plain, html_body = None, None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            if ctype == "text/plain" and plain is None:
                plain = _decode_part(part)
            elif ctype == "text/html" and html_body is None:
                html_body = _decode_part(part)
    else:
        ctype = msg.get_content_type()
        payload = _decode_part(msg)
        if ctype == "text/html":
            html_body = payload
        else:
            plain = payload

    if plain:
        # A plain-text email may still carry URLs inline; harvest them.
        links = re.findall(r"https?://[^\s>)\]]+", plain)
        return collapse_ws(plain), links
    if html_body:
        return html_to_text(html_body)
    return "", []


def _decode_part(part):
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Ledger (idempotency by Message-ID). Never mutates the server mailbox.
# ---------------------------------------------------------------------------
def load_ledger():
    if not LEDGER_PATH.exists():
        return {"seen": []}
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("seen"), list):
            return data
    except (ValueError, OSError):
        pass
    return {"seen": []}


def save_ledger(ledger):
    LEDGER_PATH.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Parse one email message object into a normalized record (or None if dropped).
# ---------------------------------------------------------------------------
def parse_message(msg):
    """Return a dict with the parsed, classified fields, or None if the message
    is out of scope / from an unknown sender. Never raises on a single bad msg."""
    from_hdr = decode_hdr(msg.get("From"))
    if not is_known_sender(from_hdr):
        return {"_drop": "unknown-sender", "from": from_hdr}
    subject = decode_hdr(msg.get("Subject"))
    message_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
    pub = parse_email_date(msg.get("Date"))
    body, links = extract_body(msg)

    source_id, tier = sender_source(from_hdr)
    if source_id is None:
        source_id, tier = "govdelivery-official", 1

    # Classify on subject + body (subject is the strongest signal, like RSS).
    text = "%s\n%s" % (subject, body)
    category = classify_category(text)
    if category is None:
        return {"_drop": "out-of-scope", "subject": subject, "from": from_hdr}

    topic = classify_topic(text)
    importance = classify_importance(text)
    affects = affects_facts_gate(text, tier=tier, in_scope=True)
    summary = first_sentences(body, 2) or subject
    url = first_http_link(links)

    return {
        "message_id": message_id,
        "from": from_hdr,
        "subject": subject,
        "published_date": pub,
        "source_id": source_id,
        "tier": tier,
        "category": category,
        "topic": topic,
        "importance": importance,
        "affects_facts": affects,
        "summary": summary,
        "url": url,
        "body": body,
    }


def to_news_item(rec):
    """Map a parsed record to a news_results_schema.json item."""
    confidence = "high" if rec["tier"] == 1 else "medium"
    return {
        "id": stable_id(rec["source_id"], rec["subject"], rec["published_date"]),
        "headline": rec["subject"] or "(no subject)",
        "url": rec["url"] or "",
        "source_id": rec["source_id"],
        "published_date": rec["published_date"],
        "category": rec["category"],
        "topic": rec["topic"],
        "summary": rec["summary"],
        "importance": rec["importance"],
        "affects_facts": rec["affects_facts"],
        "confidence": confidence,
        "tier": rec["tier"],
    }


def to_facts_finding(rec):
    """Map a facts-relevant email to a fetch_results_schema.json finding. This
    is a HUMAN-REVIEW hand-off fragment, NOT an auto-apply value. We record it
    against the uscis-processing-times / visa-bulletin field with confidence
    'low' so the harness lists it under could-not-verify and a human decides.
    We never invent a precise found_value from prose, so found_value is null and
    the observed text lives in notes for the reviewer."""
    topic = rec["topic"]
    if topic == "visa-bulletin":
        field_path = "bulletin.categories"  # human maps to the specific cell
        note_lead = "Visa Bulletin release email"
    elif topic == "processing-times":
        field_path = "i140.regular_processing_months"
        note_lead = "USCIS processing-times email"
    elif "fee" in (rec["subject"] + rec["summary"]).lower():
        field_path = "fees"
        note_lead = "Fee-change email"
    else:
        field_path = "bulletin.categories"
        note_lead = "Rulebook-relevant email"
    notes = ("%s from %s (%s). Subject: %s | Excerpt: %s | Link: %s. "
             "HUMAN REVIEW REQUIRED - not an auto-apply value; a human maps this "
             "to the specific rulebook field and hand-authors the fetch-results "
             "value before diff_proposal.py."
             % (note_lead, rec["source_id"], rec["published_date"] or "no-date",
                rec["subject"], (rec["summary"] or "")[:200], rec["url"] or "n/a"))
    return {
        "field_path": field_path,
        "found_value": None,
        "sources": [rec["source_id"]],
        "tier": rec["tier"],
        "confidence": "low",
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# IMAP connect + read-only search/fetch. Never issues .store / flag changes.
# ---------------------------------------------------------------------------
def imap_since_criterion(since_days, run_date):
    """Build an IMAP SINCE date string (DD-Mon-YYYY) for `since_days` back."""
    try:
        base = datetime.date.fromisoformat(run_date)
    except (TypeError, ValueError):
        base = datetime.datetime.now(datetime.timezone.utc).date()
    cutoff = base - datetime.timedelta(days=max(0, since_days))
    return cutoff.strftime("%d-%b-%Y")


def fetch_messages(host, user, password, mailbox, since_days, run_date, log):
    """Connect over SSL, SELECT the mailbox read-only, SEARCH SINCE cutoff, and
    FETCH full messages. Returns a list of email.message.Message. READ-ONLY: we
    pass readonly=True to select and use .fetch, never .store."""
    context = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, timeout=TIMEOUT_SECONDS, ssl_context=context)
    messages = []
    try:
        conn.login(user, password)
        # readonly=True -> EXAMINE not SELECT: the server will not set \Seen on
        # fetched messages, so the user's inbox is left untouched.
        conn.select(mailbox, readonly=True)
        since = imap_since_criterion(since_days, run_date)
        log("IMAP SEARCH SINCE %s in %s" % (since, mailbox))
        typ, data = conn.search(None, "SINCE", since)
        if typ != "OK":
            log("IMAP SEARCH returned %s" % typ)
            return messages
        ids = data[0].split() if data and data[0] else []
        log("IMAP matched %d message(s) since %s" % (len(ids), since))
        for mid in ids:
            typ, msg_data = conn.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            for part in msg_data:
                if isinstance(part, tuple) and part[1]:
                    messages.append(email.message_from_bytes(part[1]))
                    break
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return messages


# ---------------------------------------------------------------------------
def print_setup_guidance():
    """Printed when GC_IMAP_PASSWORD is unset. Clear, actionable, exit 0."""
    print("=" * 72)
    print("ingest_email.py - IMAP password not set")
    print("=" * 72)
    print("The %s environment variable is not set, so this script will NOT"
          % ENV_PASSWORD)
    print("connect to any mail server. (The password is NEVER taken on the CLI -")
    print("that would leak it into shell history and the process table.)")
    print("")
    print("For a dedicated Gmail inbox (see automation/EMAIL_SETUP.md):")
    print("  1. Enable 2-Step Verification on the account.")
    print("  2. Create an App Password: https://myaccount.google.com/apppasswords")
    print("     (a normal password will NOT work for IMAP).")
    print("  3a. Store it in the macOS Keychain:")
    print("        security add-generic-password -s gc-imap -a <addr> -w <app-pw>")
    print("      and export it for a run:")
    print('        export %s="$(security find-generic-password -s gc-imap -w)"'
          % ENV_PASSWORD)
    print("  3b. OR export it directly for this shell:")
    print('        export %s="your-16-char-app-password"' % ENV_PASSWORD)
    print("  3c. OR (GitHub Actions) add a repo secret named %s and map it to"
          % ENV_PASSWORD)
    print("      the step env, exactly like SLACK_WEBHOOK_URL in SETUP.md.")
    print("")
    print("Then re-run, e.g.:")
    print("  python3 ingest_email.py --as news --user <addr> --since-days 3")
    print("")
    print("With no password set you can still do a safe --dry-run to preview the")
    print("plan (it will not connect). Exiting 0 (this is a normal, safe state).")


def build_news_output(run_date, items, notes):
    return {
        "run_date": run_date,
        "window_days": 1,
        "fetched_by": "ingest_email.py",
        "fetch_notes": notes,
        "items": items,
    }


def build_facts_output(run_date, findings, notes, bulletin_month):
    return {
        "run_date": run_date,
        "bulletin_month_found": bulletin_month,
        "fetched_by": "ingest_email.py",
        "fetch_notes": notes,
        "findings": findings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="EMAIL-INGESTION path for the green card monitor. Reads NEW "
                    "GovDelivery / official-alert emails from a dedicated inbox "
                    "over READ-ONLY IMAP and converts in-scope (EB-1/EB-2/EB-3/"
                    "H-1B) messages into the pipeline's structured JSON: --as news "
                    "(news_results_schema.json, for news_digest.py) or --as facts "
                    "(fetch_results_schema.json, human-reviewed before "
                    "diff_proposal.py). Subscribing is a one-time human action "
                    "(see EMAIL_SETUP.md); this only READS. IMAP password comes "
                    "ONLY from the %s env var. Personal-learning tool; not legal "
                    "advice." % ENV_PASSWORD)
    ap.add_argument("--out", default=None,
                    help="Output JSON path. Default: automation/"
                         "email_results_<news|facts>.json.")
    ap.add_argument("--as", dest="mode", choices=["news", "facts"],
                    default="news",
                    help="Emit news items (default) or a facts snapshot fragment.")
    ap.add_argument("--since-days", type=int, default=DEFAULT_SINCE_DAYS,
                    help="Look back this many days for new mail (default %d)."
                         % DEFAULT_SINCE_DAYS)
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help="IMAP host (default %s)." % DEFAULT_HOST)
    ap.add_argument("--user", default=None,
                    help="IMAP username / email address of the dedicated inbox.")
    ap.add_argument("--mailbox", default=DEFAULT_MAILBOX,
                    help="Mailbox/label to read (default %s)." % DEFAULT_MAILBOX)
    ap.add_argument("--date", default=None,
                    help="Canonical run date YYYY-MM-DD (default: today, UTC).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not write output or update the ledger. With no "
                         "password, print the plan without connecting; with a "
                         "password, connect and print parsed subjects without "
                         "writing anything.")
    ap.add_argument("--verbose", action="store_true",
                    help="Log IMAP steps to stderr.")
    args = ap.parse_args(argv)

    run_date = args.date or datetime.datetime.now(
        datetime.timezone.utc).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", run_date):
        sys.stderr.write("ERROR: --date must be YYYY-MM-DD, got %r\n" % run_date)
        return 2
    if args.since_days < 0:
        sys.stderr.write("ERROR: --since-days must be >= 0\n")
        return 2

    def log(msg):
        if args.verbose:
            sys.stderr.write("[ingest_email] %s\n" % msg)

    out_path = Path(args.out) if args.out else (
        HERE / ("email_results_%s.json" % args.mode))
    password = os.environ.get(ENV_PASSWORD)

    # --- No password: print setup guidance (or a dry-run plan) and exit 0. ---
    if not password:
        if args.dry_run:
            print("=" * 72)
            print("ingest_email.py DRY-RUN (no %s set - will NOT connect)"
                  % ENV_PASSWORD)
            print("=" * 72)
            print("Would connect to : %s as %s" % (args.host,
                                                   args.user or "<--user unset>"))
            print("Would read       : mailbox %r, messages SINCE %s"
                  % (args.mailbox,
                     imap_since_criterion(args.since_days, run_date)))
            print("Would emit       : --as %s -> %s" % (args.mode, out_path))
            print("Would filter to  : senders containing one of %s"
                  % ", ".join(KNOWN_SENDER_TOKENS[:6]) + ", ...")
            print("Scope            : EB-1/EB-2/EB-3/H-1B only (word-boundary).")
            print("READ-ONLY IMAP   : uses EXAMINE + .fetch; never .store/delete.")
            print("Idempotency      : ledger %s (by Message-ID)." % LEDGER_PATH.name)
            print("")
            print("No password set, so nothing was fetched. Set %s to run for "
                  "real (see below)." % ENV_PASSWORD)
            print("")
        print_setup_guidance()
        return 0

    if not args.user:
        sys.stderr.write(
            "ERROR: --user (the dedicated inbox address) is required when %s is "
            "set.\n" % ENV_PASSWORD)
        return 2

    # --- Connect and fetch (real credentials present). ---
    try:
        messages = fetch_messages(args.host, args.user, password, args.mailbox,
                                  args.since_days, run_date, log)
    except imaplib.IMAP4.error as exc:
        sys.stderr.write(
            "ERROR: IMAP login/select failed: %s\n"
            "  - For Gmail, confirm 2FA is on and %s is an APP PASSWORD (not the "
            "account password).\n"
            "  - Confirm --user and --host are correct.\n" % (exc, ENV_PASSWORD))
        return 1
    except (OSError, ssl.SSLError) as exc:
        sys.stderr.write("ERROR: could not reach IMAP host %s: %s\n"
                         % (args.host, exc))
        return 1

    ledger = load_ledger()
    seen = set(ledger.get("seen", []))

    parsed_records = []
    dropped_unknown = 0
    dropped_scope = 0
    dropped_seen = 0
    for msg in messages:
        try:
            rec = parse_message(msg)
        except Exception as exc:  # noqa: BLE001 - one bad message never kills run
            log("parse error on a message: %s" % exc)
            continue
        if rec is None:
            continue
        if rec.get("_drop") == "unknown-sender":
            dropped_unknown += 1
            continue
        if rec.get("_drop") == "out-of-scope":
            dropped_scope += 1
            continue
        # Idempotency: skip messages already processed (by Message-ID). A missing
        # Message-ID falls back to the stable content id so it still dedups.
        key = rec["message_id"] or ("nomid:" + stable_id(
            rec["source_id"], rec["subject"], rec["published_date"]))
        rec["_ledger_key"] = key
        if key in seen:
            dropped_seen += 1
            continue
        parsed_records.append(rec)

    affects_count = sum(1 for r in parsed_records if r["affects_facts"])

    # --- Dry-run WITH a password: connect + print, but write nothing. ---
    if args.dry_run:
        print("=" * 72)
        print("ingest_email.py DRY-RUN (connected; NOTHING written)")
        print("=" * 72)
        print("Host/user        : %s as %s" % (args.host, args.user))
        print("Mailbox/since    : %r SINCE %s"
              % (args.mailbox, imap_since_criterion(args.since_days, run_date)))
        print("Messages fetched : %d" % len(messages))
        print("Dropped          : %d unknown-sender, %d out-of-scope, %d "
              "already-seen" % (dropped_unknown, dropped_scope, dropped_seen))
        print("New in-scope     : %d (%d affects_facts)"
              % (len(parsed_records), affects_count))
        print("")
        print("Sample parsed subjects (would emit --as %s):" % args.mode)
        for r in parsed_records[:10]:
            print("  [%s/%s/%s%s] %s"
                  % (r["source_id"], r["category"], r["topic"],
                     "/affects_facts" if r["affects_facts"] else "",
                     (r["subject"] or "(no subject)")[:80]))
        if not parsed_records:
            print("  (none)")
        print("")
        print("Ledger + output NOT modified (dry-run).")
        return 0

    # --- Real run: build output, write it, update the ledger. ---
    if args.mode == "news":
        items = [to_news_item(r) for r in parsed_records]
        notes = (
            "Email-ingested via ingest_email.py from a dedicated GovDelivery-"
            "subscribed inbox (AUTHORIZED subscriptions, READ-ONLY IMAP - no "
            "scraping, no bot-bypass). Fetched %d message(s) since %s; dropped %d "
            "unknown-sender, %d out-of-scope, %d already-seen. %d in-scope item(s); "
            "%d flagged affects_facts. Subscribing was a one-time human action; "
            "reading is automated."
            % (len(messages),
               imap_since_criterion(args.since_days, run_date),
               dropped_unknown, dropped_scope, dropped_seen,
               len(items), affects_count))
        output = build_news_output(run_date, items, notes)
    else:
        # facts mode: only messages that plausibly touch a rulebook fact.
        facts_recs = [r for r in parsed_records if r["affects_facts"]]
        findings = [to_facts_finding(r) for r in facts_recs]
        # Report the newest bulletin month we can infer, else the run month.
        bulletin_month = run_date[:7]
        for r in facts_recs:
            if r["topic"] == "visa-bulletin" and r["published_date"]:
                bulletin_month = r["published_date"][:7]
                break
        notes = (
            "Email-ingested facts snapshot via ingest_email.py (AUTHORIZED "
            "GovDelivery subscription, READ-ONLY IMAP). %d rulebook-relevant "
            "email(s) of %d in-scope. Every finding is confidence 'low' with a "
            "null found_value ON PURPOSE: this is a HUMAN-REVIEW hand-off - a "
            "human reads the notes, maps to the exact rulebook field, and hand-"
            "authors the value before diff_proposal.py. Nothing here auto-applies "
            "to rulebook.json." % (len(findings), len(parsed_records)))
        output = build_facts_output(run_date, findings, notes, bulletin_month)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Update the ledger with every NEW message we processed (by Message-ID).
    for r in parsed_records:
        seen.add(r["_ledger_key"])
    ledger["seen"] = sorted(seen)
    save_ledger(ledger)

    # ---- stdout summary ----
    print("=" * 72)
    print("ingest_email.py - %s (--as %s)" % (run_date, args.mode))
    print("=" * 72)
    print("Host/user        : %s as %s" % (args.host, args.user))
    print("Messages fetched : %d (SINCE %s)"
          % (len(messages), imap_since_criterion(args.since_days, run_date)))
    print("Dropped          : %d unknown-sender, %d out-of-scope, %d already-seen"
          % (dropped_unknown, dropped_scope, dropped_seen))
    if args.mode == "news":
        print("New items        : %d (%d affects_facts)"
              % (len(output["items"]), affects_count))
    else:
        print("Facts findings   : %d (human-review, low-confidence hand-off)"
              % len(output["findings"]))
    print("Ledger entries   : %d (by Message-ID; server mailbox untouched)"
          % len(ledger["seen"]))
    print("Output           : %s" % out_path)
    if args.mode == "news" and not output["items"]:
        print("NOTE: 0 new items. A quiet inbox is a real state - wrote a valid "
              "empty items[] (nothing fabricated).")
    if args.mode == "news":
        print("")
        print("Next: python3 news_digest.py --news-results %s --date %s"
              % (out_path.name, run_date))
    else:
        print("")
        print("Next (HUMAN): review the findings, then follow RUNBOOK.md ->"
              " diff_proposal.py. Nothing auto-applies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
