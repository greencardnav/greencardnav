#!/usr/bin/env python3
"""
post_slack.py - POST the daily green-card news digest to a Slack Workflow Builder
(/triggers/) webhook as a FLAT dict of named DATA variables (or print it, when
no webhook is configured).

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
This is the automatable "Step 3 NOTIFY" for the DAILY news layer. The Claude-
assisted fetch step writes a STRUCTURED news-results JSON (conforming to
news_results_schema.json); news_digest.py dedups + ranks it, writes a dated
markdown digest, and writes a .news_slack_payload_<date>.txt file containing a
FLAT JSON dict of named variables. This script POSTs that dict as the webhook
body; a WFB webhook maps the dict's top-level keys to workflow variables.

    fetch (Claude) -> news_results.json -> news_digest.py (dedup + digest + payload)
                                        -> post_slack.py (this file: POST variables)

STRUCTURE-IN-STEP PATTERN (why we send DATA, not formatting)
------------------------------------------------------------
Proven by live tests against the real Slack workspace (do NOT re-litigate):
content sent as a WFB Text VARIABLE VALUE is NOT parsed as mrkdwn - `*bold*`
renders literal asterisks and `<url|label>` gets stripped to a bare unfurling
URL. So the rich frame (bold labels, numbering, hyperlinks) is TYPED into the
workflow's "Send a message" step's composer, and the pipeline sends ONLY plain
DATA as named variables. See SLACK_WORKFLOW_SETUP.md for the exact composer
layout to type and the list of variables to declare.

The variable set (built by build_slack_variables here and, identically, in
news_digest.build_slack_variables):
  date, summary, more, digest, and for i in 1..5:
  item{i}_headline, item{i}_source, item{i}_why, item{i}_url, item{i}_flag.
Values are plain text with NO mrkdwn and NO <url|label> link syntax.

TWO INPUT PATHS
---------------
--payload <file>: the .news_slack_payload_<date>.txt file. If it parses as a
  JSON object (the current flat variable dict), it is POSTed DIRECTLY as the
  webhook body. If it is not JSON (a legacy pre-rendered plain-text blob), it is
  wrapped as {"text": <contents>} with broken <url|label>/[label](url) link
  syntax stripped to bare URLs.
--news-results <file>: the structured news-results JSON. The flat variable dict
  is regenerated from its fields and POSTed as the body.

HONEST BOUNDARY
---------------
The webhook URL is a SECRET, read ONLY from the environment (SLACK_WEBHOOK_URL by
default). It is NEVER hardcoded and MUST NOT be committed. If the env var is
unset OR --dry-run is passed, this script prints the JSON body that WOULD be
POSTed to stdout and exits 0 - so local/dev/CI runs without the secret behave
sanely and the output is eyeball-testable. NO emojis anywhere.

Personal-learning project. NOT legal advice, NOT official guidance.

Usage:
  python3 post_slack.py [--news-results <path> | --payload <path>]
                        [--webhook-env SLACK_WEBHOOK_URL]
                        [--digest-path <path for the "digest" variable>]
                        [--sources <news_sources.json>] [--dry-run]

stdlib only: argparse, json, os, re, sys, urllib.request, pathlib.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

USER_AGENT = "green-card-monitor/1.0 (personal learning project)"
TIMEOUT_SECONDS = 20

# Ranking maps (mirrors news_digest.py so the Slack order matches the digest).
IMPORTANCE_RANK = {"high": 3, "medium": 2, "low": 1}
TOPIC_RANK = {
    "rule-making": 9,
    "visa-bulletin": 8,
    "policy": 7,
    "h1b-lottery": 6,
    "h1b-cap": 5,
    "priority-dates": 4,
    "litigation": 3,
    "processing-times": 2,
    "rfe-trends": 1,
}


# --------------------------------------------------------------------------- #
# Derivations (kept in sync with news_digest.py - post_slack cannot import it) #
# --------------------------------------------------------------------------- #
def why_it_matters(item):
    """A one-line, factual 'why it matters' derived mechanically from the item's
    fields. Mirrors news_digest.why_it_matters so the Slack line matches the
    digest. The news-results JSON does NOT carry this field - it is derived."""
    if item.get("affects_facts"):
        return ("Suggests a rulebook fact changed - triggers the monthly facts "
                "refresh for review.")
    topic = item.get("topic")
    cat = item.get("category", "this category")
    mapping = {
        "rule-making": "A rule change can alter filing requirements, fees, or eligibility for %s." % cat,
        "visa-bulletin": "Bulletin movement changes priority-date positions for %s." % cat,
        "policy": "A policy shift can change how %s petitions are adjudicated." % cat,
        "h1b-lottery": "Affects H-1B registration/selection odds and timing.",
        "h1b-cap": "Affects H-1B cap availability and cap-subject filing windows.",
        "priority-dates": "Directly affects wait-time expectations for %s applicants." % cat,
        "litigation": "A lawsuit outcome can change or pause %s processing." % cat,
        "processing-times": "Changes expected timelines for %s cases." % cat,
        "rfe-trends": "A shift in RFE patterns changes evidence expectations for %s filings." % cat,
    }
    return mapping.get(topic, "Relevant context for %s planning." % cat)


def item_key(item):
    """Stable dedup key for an item, matching news_digest.item_key: prefer the
    fetcher-assigned id, else a hash of source_id + headline + published_date.
    Used for within-message dedup so the same story never appears twice (the
    example JSON intentionally repeats one item to exercise this)."""
    iid = item.get("id")
    if isinstance(iid, str) and iid.strip():
        return iid.strip()
    basis = "|".join([
        str(item.get("source_id", "")),
        str(item.get("headline", "")),
        str(item.get("published_date", "")),
    ])
    return "hash:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def rank_sort_key(item):
    """Sort key for items. Higher sorts FIRST (sorted reverse=True). affects_facts
    is the top key so those items are surfaced first, matching the requested
    'affects-facts at the top' behavior; then importance, tier, topic."""
    affects = 1 if item.get("affects_facts") else 0
    importance = IMPORTANCE_RANK.get(item.get("importance"), 0)
    tier = item.get("tier")
    tier_rank = (4 - tier) if isinstance(tier, int) else 0
    topic_rank = TOPIC_RANK.get(item.get("topic"), 0)
    return (affects, importance, tier_rank, topic_rank)


def build_source_index(sources_path):
    """Map source_id -> friendly display name from news_sources.json. Missing or
    malformed file is non-fatal (falls back to showing the raw source_id)."""
    p = Path(sources_path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    index = {}
    for tier_list in data.get("tiers", {}).values():
        if isinstance(tier_list, list):
            for src in tier_list:
                if isinstance(src, dict) and src.get("id"):
                    index[src["id"]] = src.get("name", src["id"])
    return index


def source_name(item, source_index):
    """Human-readable source LABEL. Preference order: (1) a readable source
    string the item already carries, (2) the display name mapped from
    news_sources.json by source_id, (3) the raw source_id itself."""
    for key in ("source", "source_name", "source_label"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    sid = item.get("source_id", "")
    return source_index.get(sid, sid or "unknown source")


# --------------------------------------------------------------------------- #
# Variable building (structure-in-step pattern)                                #
# --------------------------------------------------------------------------- #
# Mirrors news_digest.build_slack_variables - post_slack cannot import it, so the
# two must be kept in sync. The rich frame (bold labels, numbering, hyperlinks)
# is TYPED into the workflow's 'Send a message' step; here we emit DATA only, as
# a FLAT dict of named string variables the WFB /triggers/ webhook maps to
# workflow variables. Values carry NO mrkdwn and NO <url|label> link syntax
# (verified: a value sent as a WFB Text variable is not parsed as mrkdwn).
SLACK_ITEM_SLOTS = 3  # Top-N items surfaced as WFB variables (3 items x 4 + 3 overhead = 15 vars).


def _plain(s):
    """Collapse whitespace and trim so a value is a single line of plain text,
    safe as one Workflow Builder variable value. No mrkdwn markup is added."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _headline_with_flag(it):
    """Plain, single-line headline with a leading '[AFFECTS FACTS] ' prefix
    folded in when the item may change a rulebook fact. Mirrors
    news_digest._headline_with_flag."""
    headline = _plain(it.get("headline", "(no headline)"))
    if it.get("affects_facts"):
        return "[AFFECTS FACTS] " + headline
    return headline


def select_top_picks(ranked_items):
    """Choose the day's TOP 3 items. Mirrors news_digest.select_top_picks.

    LLM-judgment path: if any items carry top_pick_rank (int 1..3, set by the
    fetch session), honor it. Gaps filled from mechanical rank_sort_key order.
    Mechanical fallback: if no item carries top_pick_rank, return top 3."""
    slots = [None, None, None]
    picked = set()
    any_rank = False
    for it in ranked_items:
        r = it.get("top_pick_rank")
        if isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= 3:
            any_rank = True
            if slots[r - 1] is None:
                slots[r - 1] = it
                picked.add(item_key(it))
    if not any_rank:
        return ranked_items[:3]
    fill = (it for it in ranked_items if item_key(it) not in picked)
    for i in range(3):
        if slots[i] is None:
            nxt = next(fill, None)
            if nxt is None:
                break
            slots[i] = nxt
            picked.add(item_key(nxt))
    return [s for s in slots if s is not None]


def build_slack_variables(news, digest_pointer, source_index):
    """Build the FLAT dict of named string variables from the structured
    news-results dict. Mirrors news_digest.build_slack_variables exactly:
    within-message dedup, rank highest-first, select_top_picks (LLM top_pick_rank
    with mechanical fallback), TOP 3 items each contributing
    headline/source/url/why, plus date/summary/digest = 15 variables total.
    [AFFECTS FACTS] is folded into the headline; no separate _flag or _more key.
    Unused item slots are filled with empty strings."""
    run_date = news.get("run_date", "unknown-date")

    items = []
    seen = set()
    for it in news.get("items", []):
        if not isinstance(it, dict):
            continue
        key = item_key(it)
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    items.sort(key=rank_sort_key, reverse=True)

    picks = select_top_picks(items)
    affects_total = sum(1 for it in items if it.get("affects_facts"))
    remaining = len(items) - len(picks)

    if items:
        summary = ("%d top pick%s; %d affects-facts."
                   % (len(picks), "" if len(picks) == 1 else "s", affects_total))
        if remaining > 0:
            summary += " %d more in the full digest." % remaining
    else:
        summary = ("No new in-scope immigration news today (EB-1/EB-2/EB-3/H-1B). "
                   "Nothing fabricated to fill the digest.")

    variables = {
        "date": _plain(run_date),
        "summary": _plain(summary),
        "digest": _plain(digest_pointer),
    }

    for i in range(1, SLACK_ITEM_SLOTS + 1):
        if i <= len(picks):
            it = picks[i - 1]
            variables["item%d_headline" % i] = _headline_with_flag(it)
            variables["item%d_source" % i] = _plain(source_name(it, source_index))
            variables["item%d_url" % i] = _plain(it.get("url") or "")
            variables["item%d_why" % i] = _plain(why_it_matters(it))
        else:
            variables["item%d_headline" % i] = ""
            variables["item%d_source" % i] = ""
            variables["item%d_url" % i] = ""
            variables["item%d_why" % i] = ""

    return variables


# --------------------------------------------------------------------------- #
# Payload-file loading (--payload): JSON dict of variables OR legacy text        #
# --------------------------------------------------------------------------- #
_ANGLE_LINK = re.compile(r"<((?:https?://)[^>|]+)(?:\|[^>]*)?>")


def load_payload_body(text):
    """Turn the contents of a .news_slack_payload_<date>.txt file into the JSON
    body to POST. Returns (body_dict, is_json_dict).

    Current pipeline writes a FLAT JSON dict of named variables (from
    news_digest.build_slack_variables); a WFB /triggers/ webhook maps its
    top-level keys to workflow variables, so we POST that dict DIRECTLY.

    LEGACY fallback: older payload files held a pre-rendered plain-text blob. If
    the file is not a JSON object, wrap it as {"text": <contents>} (stripping any
    <url|label> / [label](url) link syntax, which renders as broken literal text
    through this path)."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        obj = None
    if isinstance(obj, dict):
        return obj, True
    # Legacy plain-text: strip broken link syntax down to bare URLs.
    repaired = _ANGLE_LINK.sub(r"\1", text)
    repaired = re.sub(r"\[[^\]]*\]\((https?://[^)]+)\)", r"\1", repaired)
    if not repaired.endswith("\n"):
        repaired += "\n"
    return {"text": repaired}, False


# --------------------------------------------------------------------------- #
# Posting                                                                       #
# --------------------------------------------------------------------------- #
def post_to_webhook(webhook_url, payload):
    """POST a JSON body to the Slack webhook. Returns (ok, message).

    `payload` is a dict. For the structured/variable path it is the FLAT dict of
    named variables a Workflow Builder (/triggers/) webhook maps to workflow
    variables. For the legacy path it is {"text": <mrkdwn>}. Either way the whole
    dict is the request body."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.getcode()
            resp_body = resp.read().decode("utf-8", errors="replace").strip()
    except Exception as exc:  # noqa: BLE001 - report the failure, non-zero exit
        return False, "failed to POST to Slack webhook: %s" % exc
    msg = "Posted to Slack webhook. HTTP status: %s" % status
    if resp_body and resp_body != "ok":  # Slack returns literal "ok" on success.
        msg += "\nWebhook response body: %s" % resp_body
    return (200 <= status < 300), msg


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Render the daily green-card news digest as rich Slack mrkdwn "
                    "and post it to an incoming webhook (URL read from an env var, "
                    "never hardcoded). Degrades gracefully to stdout when no webhook "
                    "is configured or --dry-run is set. Personal-learning tool; not "
                    "legal advice.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--news-results",
                     help="Path to the STRUCTURED news-results JSON (conforms to "
                          "news_results_schema.json). Regenerates the FLAT variable "
                          "dict from the structured fields and POSTs it as the "
                          "webhook body.")
    src.add_argument("--payload",
                     help="Path to the payload file news_digest.py writes "
                          "(.news_slack_payload_<date>.txt). If it is a JSON object "
                          "(the current flat variable dict), it is POSTed directly "
                          "as the webhook body; a legacy plain-text file is wrapped "
                          "as {\"text\": ...}.")
    ap.add_argument("--webhook-env", default="SLACK_WEBHOOK_URL",
                    help="Name of the env var holding the Slack incoming-webhook URL "
                         "(default: SLACK_WEBHOOK_URL). The URL is a secret, read from "
                         "the environment only - never hardcoded.")
    ap.add_argument("--digest-path", default=None,
                    help="Pointer to the full markdown digest, shown in the footer. "
                         "Defaults to news_digests/<run_date>.md.")
    ap.add_argument("--sources", default=str(HERE / "news_sources.json"),
                    help="Path to news_sources.json (default: automation/news_sources.json). "
                         "Used only for friendly source names; missing is non-fatal.")
    ap.add_argument("--max-items", type=int, default=10,
                    help="Accepted for backward compatibility. The variable payload "
                         "surfaces a fixed 5 item slots (the WFB ~20-variable cap), so "
                         "this flag no longer changes output.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the JSON body that WOULD be POSTed to stdout; never POST.")
    args = ap.parse_args(argv)

    # --- Build the JSON body to POST -----------------------------------------
    # Either path yields a dict: the FLAT variable dict a WFB /triggers/ webhook
    # maps to workflow variables, or a legacy {"text": ...} body.
    if args.news_results:  # Regenerate the variable dict from structured data.
        path = Path(args.news_results)
        if not path.exists():
            sys.stderr.write("ERROR: news-results file not found: %s\n" % path)
            return 2
        try:
            news = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            sys.stderr.write("ERROR: could not parse news-results JSON: %s\n" % exc)
            return 2
        if not isinstance(news, dict) or not isinstance(news.get("items"), list):
            sys.stderr.write("ERROR: news-results must be an object with an 'items' list.\n")
            return 2
        run_date = news.get("run_date", "unknown-date")
        digest_pointer = args.digest_path or ("news_digests/%s.md" % run_date)
        source_index = build_source_index(args.sources)
        payload = build_slack_variables(news, digest_pointer, source_index)
        is_json_dict = True
    else:  # Read the payload file: JSON variable dict (current) or legacy text.
        path = Path(args.payload)
        if not path.exists():
            sys.stderr.write("ERROR: payload file not found: %s\n" % path)
            return 2
        payload, is_json_dict = load_payload_body(path.read_text(encoding="utf-8"))

    # --- Post or print --------------------------------------------------------
    webhook_url = os.environ.get(args.webhook_env, "").strip()
    kind = ("flat variable dict (WFB maps top-level keys to workflow variables)"
            if is_json_dict else "legacy {\"text\": ...} body")
    body_text = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.dry_run or not webhook_url:
        if not args.dry_run:
            print("No Slack webhook configured (env var %s is unset)." % args.webhook_env)
            print("Not posting. The JSON body that WOULD be POSTed follows.")
        print("Detected payload type: %s." % kind)
        print("-" * 70)
        sys.stdout.write(body_text + "\n")
        print("-" * 70)
        if not args.dry_run:
            print("To enable posting, set %s to your Slack Workflow Builder "
                  "(/triggers/) webhook URL (a secret - do NOT commit it)."
                  % args.webhook_env)
        return 0

    ok, msg = post_to_webhook(webhook_url, payload)
    (print if ok else sys.stderr.write)(msg + ("\n" if not ok else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
