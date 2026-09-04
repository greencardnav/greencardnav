#!/usr/bin/env python3
"""
news_digest.py - the MECHANICAL half of the green card tool's DAILY news-monitoring workflow.

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
The daily immigration-news layer has two halves with an HONEST, hard boundary -
the same split as the monthly facts harness (diff_proposal.py / apply_proposal.py):

  1. THE FETCH STEP (Claude-assisted, NOT pure-cron).
     USCIS/DOS/DOL/Federal Register are Cloudflare-walled or rate-limited to
     scripts and headless browsers. Reaching them plus law-firm practitioner
     sites requires Claude's WebFetch tool, and a cron has no access to that.
     So a human/Claude session gathers the news and writes a news-results JSON
     conforming to news_results_schema.json. A cron CANNOT do this.

  2. THE MECHANICAL STEPS (pure Python stdlib, fully automatable) - THIS SCRIPT.
     It CONSUMES the news-results JSON. It never scrapes anything. It dedups each
     item against a persistent "seen" ledger so the SAME story is never surfaced
     twice, ranks the new items by importance, writes a dated markdown digest,
     and emits a Slack DM payload file. The posting to Slack is a separate Claude
     step (Python has no creds).

  3. THE HONEST CRON JOB: a daily REMINDER (news_remind.sh) to run the fetch.
     It never fetches or changes anything.

This is a DAILY news stream. It is SEPARATE from the MONTHLY facts refresh. It
does NOT write rulebook.json. When an item is affects_facts:true (a new bulletin,
a fee change, a new rule), the digest flags it at the top: that is the trigger to
run the monthly facts flow (automation/RUNBOOK.md -> diff_proposal.py) which is
where rulebook.json actually gets updated after human approval.

Personal-learning project. NOT legal advice. NOT official guidance.
Scope: EB-1, EB-2, EB-3, and H-1B ONLY.

Usage:
  python3 news_digest.py --news-results <path> [--date YYYY-MM-DD]
                         [--ledger <path>] [--out <news_digests_dir>]

stdlib only: json, datetime, pathlib, argparse, hashlib, re, sys, urllib
"""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Shared community taxonomy + classifiers live in fetch_feeds.py so the fetcher
# and the community.json writer read ONE source of truth and never drift. Guarded
# so news_digest still runs (writing a schema:2 file with an empty taxonomy and a
# 'general' fallback) if fetch_feeds is unavailable for any reason.
try:
    from fetch_feeds import (COMMUNITY_TAXONOMY, classify_categories,
                             community_fine_topic)
except Exception:  # noqa: BLE001 - degrade gracefully, never crash the digest
    COMMUNITY_TAXONOMY = []

    def classify_categories(title, subreddit):  # type: ignore
        return ["general"]

    def community_fine_topic(title):  # type: ignore
        return None

DISCLAIMER = ("Personal-learning project. NOT legal advice. NOT official "
              "guidance. Scope: EB-1, EB-2, EB-3, and H-1B only.")

# Ranking maps. Higher sorts first.
IMPORTANCE_RANK = {"high": 3, "medium": 2, "low": 1}
# Rule-making / policy changes rank above commentary within the same importance.
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
# Digest sections, in display order.
CATEGORY_ORDER = ["H-1B", "EB-1", "EB-2", "EB-3", "cross-cutting"]
CATEGORY_TITLES = {
    "H-1B": "H-1B",
    "EB-1": "EB-1",
    "EB-2": "EB-2",
    "EB-3": "EB-3",
    "cross-cutting": "Cross-cutting",
}


# Community items (crowd-sourced Reddit/forum date reports) are marked by a
# 'community-reddit-' (or generic 'community-') source_id prefix set by
# fetch_feeds.py. They are TIER 3 / LOW confidence anecdotes: rendered in a
# SEPARATE, disclaimered section, never eligible for the Slack top-3 picks, and
# never carry affects_facts. This is the one place the prefix convention is
# interpreted on the render side.
def _is_community(item):
    sid = item.get("source_id", "")
    return isinstance(sid, str) and sid.startswith("community-")


def _community_source_label(item, source_index):
    """Human label for a community item's origin, e.g. 'r/h1b'."""
    sid = item.get("source_id", "") or ""
    if sid.startswith("community-reddit-"):
        return "r/" + sid[len("community-reddit-"):]
    src = source_index.get(sid, {}) if source_index else {}
    return src.get("name") or sid or "community"


# Community snapshot is a ROLLING WINDOW, not a first-seen feed: it shows every
# community item published in the last COMMUNITY_WINDOW_DAYS, so the section stays
# populated between runs instead of only showing items newly-seen on one day.
COMMUNITY_WINDOW_DAYS = 21
# Raised from 12 -> 60 so filtering to a specific category/subreddit still has
# content. Per-subreddit and per-category caps keep one chatty sub from crowding
# out a category.
COMMUNITY_MAX_ITEMS = 60
COMMUNITY_MAX_PER_SUB = 8
COMMUNITY_MAX_PER_CATEGORY = 15
COMMUNITY_SCHEMA_VERSION = 2


def _community_date(s):
    """Parse an item date (ISO or 'YYYY-MM-DD...') to a date; None if unparseable."""
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _community_subreddit(item):
    """Derive the bare subreddit name (no 'r/') for a community item, from an
    already-attached 'subreddit' field, else the 'community-reddit-<sub>'
    source_id, else the 'r/<sub>' display source. '' if none."""
    sub = (item.get("subreddit") or "").strip()
    if sub:
        return sub
    sid = item.get("source_id", "") or ""
    if sid.startswith("community-reddit-"):
        return sid[len("community-reddit-"):]
    src = (item.get("source") or "").strip()
    if src.startswith("r/"):
        return src[2:]
    return ""


def write_community_json(all_items, source_index, out_path):
    """Write a same-origin community.json snapshot next to index.html for the
    green card tool to load. ROLLING WINDOW: draws from ALL community items fetched
    this run (not just ones new-to-the-ledger) and MERGES them with whatever is
    already in community.json, keeping everything from the last COMMUNITY_WINDOW_DAYS.
    Merging means a quiet or rate-limited fetch day does not blank the section —
    items persist until they age out of the window.

    schema:2 — each item carries optional subreddit / categories / topic and the
    file carries a taxonomy block. Categories/topic/subreddit are RECOMPUTED here
    from title+subreddit (via fetch_feeds.classify_categories) for every item —
    fresh AND prior-on-disk — so the whole file stays aligned to the current
    taxonomy and old schema:1 items are upgraded in place. Always writes a valid
    file; the shape is backward-compatible (title/url/source/date preserved)."""
    fresh = [{
        "title": it.get("headline", "(no headline)"),
        "url": (it.get("url") or "").strip(),
        "source": _community_source_label(it, source_index),
        "date": it.get("published_date", ""),
        "subreddit": _community_subreddit(it),
    } for it in all_items if _is_community(it)]

    # Reuse whatever is already on disk so a zero-item fetch does not wipe it.
    prior = []
    try:
        existing = json.loads(Path(out_path).read_text(encoding="utf-8"))
        if isinstance(existing, dict) and isinstance(existing.get("items"), list):
            prior = existing["items"]
    except Exception:
        prior = []

    today = datetime.datetime.now(datetime.timezone.utc).date()
    cutoff = today - datetime.timedelta(days=COMMUNITY_WINDOW_DAYS)
    by_url = {}
    # prior first, then fresh, so a fresh copy overwrites a stale one on the same URL.
    for it in (prior + fresh):
        url = (it.get("url") or "").strip()
        d = _community_date(it.get("date"))
        if not url or d is None or d < cutoff:
            continue
        title = it.get("title", "(no headline)")
        subreddit = _community_subreddit(it)
        # Recompute categories + fine topic authoritatively so the file always
        # reflects the current taxonomy (also upgrades old schema:1 items).
        categories = classify_categories(title, subreddit)
        topic = community_fine_topic(title)
        entry = {
            "title": title,
            "url": url,
            "source": it.get("source", "community"),
            "date": it.get("date", ""),
            "subreddit": subreddit,
            "categories": categories,
        }
        if topic:
            entry["topic"] = topic
        by_url[url] = entry

    ordered = sorted(by_url.values(), key=lambda x: x.get("date", ""), reverse=True)

    # Apply per-sub and per-category caps (and the overall cap) on the
    # date-descending list, so the freshest items win the limited slots.
    items = []
    per_sub = {}
    per_cat = {}
    for it in ordered:
        if len(items) >= COMMUNITY_MAX_ITEMS:
            break
        sub = it.get("subreddit") or "?"
        if per_sub.get(sub, 0) >= COMMUNITY_MAX_PER_SUB:
            continue
        cats = it.get("categories") or ["general"]
        # Drop only if EVERY one of its categories is already full.
        if cats and all(per_cat.get(c, 0) >= COMMUNITY_MAX_PER_CATEGORY
                        for c in cats):
            continue
        items.append(it)
        per_sub[sub] = per_sub.get(sub, 0) + 1
        for c in cats:
            per_cat[c] = per_cat.get(c, 0) + 1

    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema": COMMUNITY_SCHEMA_VERSION,
        "taxonomy": COMMUNITY_TAXONOMY,
        "items": items,
    }
    try:
        Path(out_path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    except Exception:
        pass  # never let snapshot-writing break the digest run
    return payload


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_ledger(path):
    """Load the persistent seen-ledger. Shape: {"seen": ["id", ...]}. If absent
    or malformed, return an empty ledger (the caller creates it on write)."""
    p = Path(path)
    if not p.exists():
        return {"seen": []}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"seen": []}
    if not isinstance(obj, dict) or not isinstance(obj.get("seen"), list):
        return {"seen": []}
    return obj


def item_key(item):
    """The stable dedup key for an item. Prefer the fetcher-assigned id; fall
    back to a hash of source_id + headline + published_date so an item without a
    usable id still dedups deterministically day over day."""
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
    """Sort key for NEW items. Higher tuple sorts FIRST (we sort reverse=True):
      1. importance (high > medium > low)
      2. affects_facts True first
      3. tier (1 > 2 > 3)  -> stored as (4 - tier) so tier 1 is largest
      4. topic rank (rule-making/policy above commentary)
    """
    importance = IMPORTANCE_RANK.get(item.get("importance"), 0)
    affects = 1 if item.get("affects_facts") else 0
    tier = item.get("tier")
    tier_rank = (4 - tier) if isinstance(tier, int) else 0
    topic_rank = TOPIC_RANK.get(item.get("topic"), 0)
    return (importance, affects, tier_rank, topic_rank)


def md_link(text, url):
    text = (text or "").replace("]", r"\]")
    return "[%s](%s)" % (text, url)


def confidence_tier_tag(item):
    return "confidence: %s | tier: %s" % (
        item.get("confidence", "?"), item.get("tier", "?"))


def _build_digest_markdown_legacy(run_date, new_items, deduped_count, source_index):
    """LEGACY markdown builder. Kept for revert purposes; not called by main.
    Replaced by build_digest_html as of 2026-08-13."""
    affects = [it for it in new_items if it.get("affects_facts")]
    lines = []
    lines.append("# Immigration News Digest - %s" % run_date)
    lines.append("")
    lines.append("> %s" % DISCLAIMER)
    lines.append("")
    lines.append("## Counts")
    lines.append("- new items: %d" % len(new_items))
    lines.append("- deduped as already-seen: %d" % deduped_count)
    lines.append("- affects_facts (may require a rulebook refresh): %d" % len(affects))
    lines.append("")

    if not new_items:
        lines.append("## No new items today")
        lines.append("")
        lines.append("No new in-scope immigration news (EB-1/EB-2/EB-3/H-1B) was "
                     "found for this run, or everything found was already reported "
                     "on a prior day. Nothing fabricated to fill the digest.")
        lines.append("")
        return "\n".join(lines) + "\n"

    # ---- AFFECTS FACTS callout at the very top ----
    lines.append("## AFFECTS FACTS - may require a rulebook refresh")
    lines.append("")
    if not affects:
        lines.append("_None today._ No item suggests a rulebook fact changed.")
        lines.append("")
    else:
        lines.append("These items suggest a fact in `rulebook.json` may have "
                     "changed (a new Visa Bulletin, a fee change, a new rule). "
                     "They TRIGGER the monthly facts flow - run "
                     "`automation/RUNBOOK.md` -> `diff_proposal.py` to update the "
                     "rulebook after human approval. The news layer does NOT write "
                     "the rulebook itself.")
        lines.append("")
        for it in affects:
            src = source_index.get(it.get("source_id"), {})
            src_name = src.get("name", it.get("source_id", "?"))
            lines.append("- %s" % md_link(it.get("headline", "(no headline)"), it.get("url", "")))
            lines.append("  - category: %s | topic: %s | %s"
                         % (it.get("category", "?"), it.get("topic", "?"),
                            confidence_tier_tag(it)))
            lines.append("  - source: %s (published %s)"
                         % (src_name, it.get("published_date", "?")))
            lines.append("  - %s" % it.get("summary", ""))
        lines.append("")

    # ---- Sections by category ----
    for cat in CATEGORY_ORDER:
        cat_items = [it for it in new_items if it.get("category") == cat]
        if not cat_items:
            continue
        lines.append("## %s" % CATEGORY_TITLES[cat])
        lines.append("")
        for it in cat_items:
            src = source_index.get(it.get("source_id"), {})
            src_name = src.get("name", it.get("source_id", "?"))
            flag = " [AFFECTS FACTS]" if it.get("affects_facts") else ""
            lines.append("### %s%s" % (it.get("headline", "(no headline)"), flag))
            lines.append("")
            lines.append("- %s" % md_link("source link", it.get("url", "")))
            lines.append("- source: %s | published: %s | topic: %s | importance: %s"
                         % (src_name, it.get("published_date", "?"),
                            it.get("topic", "?"), it.get("importance", "?")))
            lines.append("- %s" % it.get("summary", ""))
            lines.append("- Why it matters: %s" % why_it_matters(it))
            lines.append("- %s" % confidence_tier_tag(it))
            lines.append("")

    return "\n".join(lines) + "\n"


def _html_escape(s):
    """Minimal HTML entity escaping for untrusted text."""
    if not s:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


class _TextExtractor(HTMLParser):
    """Strip HTML tags and extract visible text from a page body."""

    SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "aside"}

    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self):
        return " ".join(self._parts)


def _fetch_article_text(url, max_bytes=80_000, timeout=10):
    """Fetch a page and extract visible text content. Returns up to ~2000 chars
    of article body text. Returns empty string on any failure."""
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "green-card-monitor/1.0 (personal learning project)",
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes)
        html_text = raw.decode("utf-8", errors="replace")
        parser = _TextExtractor()
        parser.feed(html_text)
        return parser.get_text()[:3000]
    except Exception:
        return ""


def _summarize_with_claude(article_text, headline):
    """Call claude -p (Claude Code pipe mode) to produce a 1-2 sentence summary.
    Uses your Pro/Max subscription — no API key or extra billing needed.
    Returns empty string if claude isn't available (e.g. in CI)."""
    if not article_text:
        return ""
    prompt = (
        "You are summarizing a news article for someone tracking US employment-based "
        "green card (EB-1, EB-2, EB-3) and H-1B visa developments.\n\n"
        "Article headline: %s\n\n"
        "Article text (first ~2000 chars):\n%s\n\n"
        "In 1-2 sentences, summarize what this article says and why it matters "
        "for someone in the EB/H-1B immigration process. Be specific to the "
        "article content — do not give generic advice. If the article isn't actually "
        "relevant to EB/H-1B immigration, say so briefly."
    ) % (headline, article_text[:2000])
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:400]
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return ""


def _enrich_items_with_descriptions(items):
    """For each item, fetch the article text and use Claude (via claude -p)
    to summarize why it matters. Falls back to a text snippet if claude
    isn't available (e.g. running in GitHub Actions CI)."""
    for it in items:
        if it.get("why_it_matters") or it.get("why"):
            continue
        headline = (it.get("headline") or "").strip()
        article_text = _fetch_article_text(it.get("url"))
        if article_text:
            summary = _summarize_with_claude(article_text, headline)
            if summary:
                it["why_it_matters"] = summary
                continue
        if article_text and len(article_text) > 100:
            snippet = article_text[:250].rsplit(" ", 1)[0]
            it["why_it_matters"] = snippet + "..."


def _relevance_dots(item):
    """Compute a 1-5 relevance score rendered as filled/empty circles.
    tier (1=3, 2=2, 3=1) + importance (high=+1, medium=+0, low=-1) + affects_facts (+1)."""
    tier = item.get("tier")
    base = {1: 3, 2: 2, 3: 1}.get(tier, 1) if isinstance(tier, int) else 1
    imp = item.get("importance", "medium")
    imp_adj = {"high": 1, "medium": 0, "low": -1}.get(imp, 0)
    af = 1 if item.get("affects_facts") else 0
    score = max(1, min(5, base + imp_adj + af))
    return "&#9679;" * score + "&#9675;" * (5 - score)


def _summary_is_useful(item):
    """Return True only when the summary adds real content beyond the headline."""
    headline = (item.get("headline") or "").strip()
    summary = (item.get("summary") or "").strip()
    if not summary:
        return False
    if summary == headline:
        return False
    if len(summary) <= len(headline) + 20:
        return False
    return True


def build_digest_html(run_date, new_items, deduped_count, source_index,
                      deduped_items=None):
    """Build a self-contained, Cloudscape-styled HTML digest. new_items is
    already rank-sorted. Returns the full HTML document as a string."""
    affects = [it for it in new_items if it.get("affects_facts")]
    e = _html_escape

    # Inline CSS using Cloudscape/Harmony design tokens from index.html
    css = """\
    :root {
      --neutral-950: #0f141a;
      --neutral-900: #161d26;
      --neutral-850: #232b37;
      --neutral-650: #424650;
      --neutral-600: #656871;
      --neutral-500: #8c8c94;
      --neutral-350: #c6c6cd;
      --neutral-250: #ebebf0;
      --neutral-150: #f6f6f9;
      --neutral-100: #f2f3f3;
      --white: #ffffff;
      --primary-600: #006ce0;
      --primary-700: #003c75;
      --primary-50: #f0fbff;
      --success-600: #00802f;
      --success-50: #effff1;
      --warning-900: #855900;
      --warning-50: #fffef0;
      --warning-border: #f7db8a;
      --error-600: #db0000;
      --error-50: #fff5f5;
      --border: #e9ebed;
      --shadow-sm: 0 0 1px 1px #e9ebed, 0 1px 8px 2px rgba(0,7,22,0.06);
      --shadow-md: 0 0 1px 1px #e9ebed, 0 6px 24px 2px rgba(0,7,22,0.10);
      --radius-sm: 8px;
      --radius-md: 16px;
      --radius-badge: 4px;
      --radius-button: 20px;
    }
    * { box-sizing: border-box; }
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont,
                   "Helvetica Neue", Roboto, Helvetica, Arial, sans-serif;
      background: var(--neutral-100);
      color: var(--neutral-950);
      margin: 0; padding: 0;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    .container { max-width: 820px; margin: 0 auto; padding: 24px 20px 60px; }
    header.hero {
      background:
        radial-gradient(120% 140% at 88% -10%, rgba(0,108,224,0.22) 0%, rgba(0,108,224,0) 55%),
        linear-gradient(160deg, #16202b 0%, var(--neutral-950) 62%);
      color: var(--neutral-250);
      padding: 40px 34px 36px;
      border-radius: var(--radius-md);
      margin-bottom: 24px;
      box-shadow: var(--shadow-sm);
      position: relative;
      overflow: hidden;
    }
    header.hero h1 {
      margin: 0 0 10px; font-size: 30px; font-weight: 700;
      letter-spacing: -0.4px; color: #ffffff; line-height: 1.18;
    }
    header.hero .subtitle {
      color: #d9dde3; font-size: 15px; margin: 0; font-weight: 400;
      line-height: 1.55;
    }
    .disclaimer {
      font-style: italic; color: var(--neutral-600); font-size: 13px;
      margin-bottom: 18px; padding: 0 4px;
    }
    .counts {
      display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px;
    }
    .count-badge {
      background: var(--white); border: 1px solid var(--border);
      border-radius: var(--radius-badge); padding: 8px 14px;
      font-size: 13px; box-shadow: var(--shadow-sm);
    }
    .count-badge strong { font-size: 18px; display: block; color: var(--primary-600); }
    .callout-warning {
      background: var(--warning-50);
      border: 1px solid var(--warning-border);
      border-left: 4px solid var(--warning-900);
      border-radius: var(--radius-md);
      padding: 18px 20px;
      margin-bottom: 20px;
    }
    .callout-warning h2 {
      margin: 0 0 10px; font-size: 16px; font-weight: 700;
      color: var(--warning-900);
    }
    .callout-warning p { margin: 0 0 10px; font-size: 13px; color: #5d4503; }
    .callout-warning ul { margin: 0; padding-left: 18px; }
    .callout-warning li { margin-bottom: 8px; font-size: 14px; }
    .callout-warning a { color: var(--warning-900); text-decoration: underline; }
    .card {
      background: var(--white); border: 1px solid var(--border);
      border-radius: var(--radius-md); padding: 20px 22px;
      margin-bottom: 16px; box-shadow: var(--shadow-sm);
    }
    .card h2 {
      margin: 0 0 14px; font-size: 18px; font-weight: 700;
      color: var(--neutral-950); border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }
    .item { margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid var(--neutral-100); }
    .item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
    .item-header { display: flex; align-items: baseline; gap: 6px; }
    .item-num { flex-shrink: 0; font-weight: 700; color: var(--primary-600); font-size: 14px; min-width: 22px; }
    .item-headline { flex: 1; }
    .item-headline a {
      color: var(--primary-600); font-weight: 600; font-size: 15px;
      text-decoration: none; line-height: 1.4;
    }
    .item-headline a:hover { text-decoration: underline; }
    .item-headline a::after {
      content: " \\2197"; font-size: 11px; opacity: 0.6;
    }
    .item-meta { font-size: 12px; color: var(--neutral-650); margin: 4px 0 0 28px; }
    .item-why {
      font-size: 13px; margin: 8px 0 0 28px; color: var(--neutral-850);
      border-left: 3px solid var(--primary-600); padding-left: 10px;
      font-style: italic; line-height: 1.45;
    }
    .item-summary { font-size: 14px; margin: 6px 0 0 28px; color: var(--neutral-950); }
    .item-badges { margin: 8px 0 0 28px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .conf-badge {
      display: inline-block; font-size: 11px; font-weight: 600;
      border-radius: var(--radius-badge); padding: 2px 8px;
    }
    .conf-high { background: #dcfce7; color: #166534; }
    .conf-medium { background: #fef3c7; color: #92400e; }
    .conf-low { background: #f3f4f6; color: #6b7280; }
    .affects-tag {
      display: inline-block; font-size: 11px; font-weight: 600;
      background: var(--warning-50); color: var(--warning-900);
      border: 1px solid var(--warning-border);
      border-radius: var(--radius-badge); padding: 2px 8px;
    }
    .community-badge {
      display: inline-block; font-size: 11px; font-weight: 600;
      background: var(--neutral-150); color: var(--neutral-650);
      border: 1px solid var(--border);
      border-radius: var(--radius-badge); padding: 2px 8px;
    }
    .community-disclaimer {
      font-size: 12px; color: var(--neutral-650); font-style: italic;
      background: var(--neutral-150); border-left: 3px solid var(--neutral-350);
      padding: 10px 12px; margin: 0 0 14px; border-radius: 4px; line-height: 1.5;
    }
    footer {
      text-align: center; font-size: 12px; color: var(--neutral-600);
      margin-top: 30px; padding-top: 16px;
      border-top: 1px solid var(--border);
    }
    .empty-msg { font-size: 14px; color: var(--neutral-650); padding: 12px 0; }
    .archive-toggle {
      background: none; border: 1px solid var(--border); border-radius: var(--radius-badge);
      padding: 8px 16px; font-size: 13px; color: var(--primary-600); cursor: pointer;
      font-weight: 600; margin-bottom: 12px;
    }
    .archive-toggle:hover { background: var(--primary-50); }
    .archive-list { display: none; }
    .archive-list.open { display: block; }
    .archive-item {
      display: flex; align-items: baseline; gap: 10px;
      padding: 8px 0; border-bottom: 1px solid var(--neutral-150);
      font-size: 13px;
    }
    .archive-item:last-child { border-bottom: none; }
    .archive-date { flex-shrink: 0; color: var(--neutral-600); font-size: 12px; min-width: 80px; }
    .archive-link { flex: 1; }
    .archive-link a { color: var(--neutral-850); text-decoration: none; }
    .archive-link a:hover { color: var(--primary-600); text-decoration: underline; }
    .archive-source { flex-shrink: 0; font-size: 11px; color: var(--neutral-500); }
    @media (max-width: 600px) {
      header.hero { padding: 28px 20px 24px; }
      header.hero h1 { font-size: 24px; }
      .card { padding: 16px; }
      .container { padding: 16px 12px 40px; }
    }
"""

    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append("<title>Immigration News Digest — %s</title>" % e(run_date))
    parts.append("<style>%s</style>" % css)
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<div class="container">')

    # Header
    parts.append('<header class="hero">')
    parts.append("<h1>Immigration News Digest</h1>")
    parts.append('<p class="subtitle">%s</p>' % e(run_date))
    parts.append("</header>")

    # Disclaimer
    parts.append('<p class="disclaimer">%s</p>' % e(DISCLAIMER))

    # Counts
    parts.append('<div class="counts">')
    parts.append('<div class="count-badge"><strong>%d</strong>new items</div>' % len(new_items))
    parts.append('<div class="count-badge"><strong>%d</strong>deduped</div>' % deduped_count)
    parts.append('<div class="count-badge"><strong>%d</strong>affects facts</div>' % len(affects))
    parts.append("</div>")

    # Empty-day early return
    if not new_items:
        parts.append('<div class="card">')
        parts.append("<h2>No new items today</h2>")
        parts.append('<p class="empty-msg">No new in-scope immigration news '
                     "(EB-1/EB-2/EB-3/H-1B) was found for this run, or everything "
                     "found was already reported on a prior day.</p>")
        parts.append("</div>")
        parts.append('<footer>Generated by the green card tool daily monitor. '
                     "Not legal advice.</footer>")
        parts.append("</div></body></html>")
        return "\n".join(parts) + "\n"

    # AFFECTS FACTS callout
    if affects:
        parts.append('<div class="callout-warning">')
        parts.append("<h2>AFFECTS FACTS — may require a rulebook refresh</h2>")
        parts.append("<p>These items suggest a fact in the rulebook may have "
                     "changed. They trigger the monthly facts flow for review.</p>")
        parts.append("<ul>")
        for it in affects:
            src = source_index.get(it.get("source_id"), {})
            src_name = src.get("name", it.get("source_id", "?"))
            headline = e(it.get("headline", "(no headline)"))
            url = it.get("url", "")
            parts.append('<li><a href="%s">%s</a> — %s (%s)</li>'
                         % (e(url), headline, e(src_name),
                            e(it.get("published_date", "?"))))
        parts.append("</ul>")
        parts.append("</div>")

    # Per-category sections (community items are rendered separately below).
    for cat in CATEGORY_ORDER:
        cat_items = [it for it in new_items
                     if it.get("category") == cat and not _is_community(it)]
        if not cat_items:
            continue
        parts.append('<div class="card">')
        parts.append("<h2>%s</h2>" % e(CATEGORY_TITLES[cat]))
        for idx, it in enumerate(cat_items, 1):
            src = source_index.get(it.get("source_id"), {})
            src_name = src.get("name", it.get("source_id", "?"))
            headline = e(it.get("headline", "(no headline)"))
            url = it.get("url", "")
            parts.append('<div class="item">')
            parts.append('<div class="item-header">')
            parts.append('<span class="item-num">%d.</span>' % idx)
            parts.append('<span class="item-headline">'
                         '<a href="%s">%s</a></span>' % (e(url), headline))
            parts.append('</div>')
            parts.append('<div class="item-meta">%s | %s</div>'
                         % (e(src_name), e(it.get("published_date", "?"))))
            why_text = why_it_matters(it)
            if why_text:
                parts.append('<div class="item-why">%s</div>' % e(why_text))
            # Summary only if it adds content beyond headline (improvement E)
            if _summary_is_useful(it):
                parts.append('<div class="item-summary">%s</div>'
                             % e(it.get("summary", "")))
            # Badges row: confidence badge + affects tag + relevance dots (B, F)
            conf = it.get("confidence", "low")
            tier = it.get("tier", 3)
            conf_class = {"high": "conf-high", "medium": "conf-medium"}.get(conf, "conf-low")
            parts.append('<div class="item-badges">')
            parts.append('<span class="conf-badge %s">Tier %s · %s confidence</span>'
                         % (conf_class, e(str(tier)), e(str(conf).capitalize())))
            if it.get("affects_facts"):
                parts.append('<span class="affects-tag">AFFECTS FACTS</span>')
            parts.append("</div>")
            parts.append("</div>")
        parts.append("</div>")

    # Community reports (unverified): crowd-sourced Reddit/forum date reports.
    # Clearly separated and disclaimered; low-confidence anecdote, not authority.
    community = [it for it in new_items if _is_community(it)]
    if community:
        community.sort(key=lambda x: x.get("published_date", ""), reverse=True)
        parts.append('<div class="card">')
        parts.append("<h2>Community reports (unverified)</h2>")
        parts.append('<p class="community-disclaimer">Crowd-sourced from Reddit '
                     "and public forums. These are anecdotal, individual reports "
                     "(for example, when someone got a visa appointment or saw "
                     "their priority date move) and are <strong>unverified</strong>. "
                     "Always confirm against official sources "
                     "(travel.state.gov, uscis.gov) before relying on anything "
                     "here.</p>")
        for idx, it in enumerate(community, 1):
            src = source_index.get(it.get("source_id"), {})
            src_name = src.get("name", it.get("source_id", "?"))
            headline = e(it.get("headline", "(no headline)"))
            url = it.get("url", "")
            parts.append('<div class="item">')
            parts.append('<div class="item-header">')
            parts.append('<span class="item-num">%d.</span>' % idx)
            parts.append('<span class="item-headline">'
                         '<a href="%s">%s</a></span>' % (e(url), headline))
            parts.append('</div>')
            parts.append('<div class="item-meta">%s | %s</div>'
                         % (e(src_name), e(it.get("published_date", "?"))))
            parts.append('<div class="item-badges">')
            parts.append('<span class="community-badge">Community · unverified</span>')
            parts.append('</div>')
            parts.append('</div>')
        parts.append('</div>')

    # Archive: all deduped (already-reported) items, sorted by date descending
    if deduped_items:
        deduped_sorted = sorted(deduped_items,
                                key=lambda x: x.get("published_date", ""),
                                reverse=True)
        parts.append('<div class="card">')
        parts.append('<h2>Previously Reported (%d items)</h2>' % len(deduped_sorted))
        parts.append('<button class="archive-toggle" '
                     'onclick="this.nextElementSibling.classList.toggle(\'open\'); '
                     'this.textContent = this.nextElementSibling.classList.contains(\'open\') '
                     '? \'Hide archive\' : \'Show archive\'">'
                     'Show archive</button>')
        parts.append('<div class="archive-list">')
        for it in deduped_sorted:
            src = source_index.get(it.get("source_id"), {})
            src_name = src.get("name", it.get("source_id", "?"))
            headline = e(it.get("headline", "(no headline)"))
            url = it.get("url", "")
            pub = it.get("published_date", "")
            parts.append('<div class="archive-item">')
            parts.append('<span class="archive-date">%s</span>' % e(pub))
            parts.append('<span class="archive-link">'
                         '<a href="%s">%s</a></span>' % (e(url), headline))
            parts.append('<span class="archive-source">%s</span>' % e(src_name))
            parts.append('</div>')
        parts.append('</div>')
        parts.append('</div>')

    # Footer
    parts.append('<footer>Generated by the green card tool daily monitor. '
                 "Not legal advice.</footer>")
    parts.append("</div></body></html>")
    return "\n".join(parts) + "\n"


def why_it_matters(item):
    """Return the article's own description/summary as the 'why' line.
    Only returns a non-empty string when we have real content from the source.
    Returns '' when there's nothing meaningful — caller skips the line."""
    why = item.get("why_it_matters") or item.get("why")
    if isinstance(why, str) and why.strip():
        return why.strip()
    if item.get("affects_facts"):
        return ("May change a fact in the rulebook — triggers the monthly "
                "refresh for review.")
    return ""


def _slack_source(it, source_index=None):
    """Human-readable source label (publisher name, e.g. 'Federal Register',
    'Murthy Law'). Prefers a readable source string the item carries; else maps
    source_id -> friendly name via news_sources.json (source_index); else the
    raw source_id."""
    for key in ("source", "source_name", "source_label"):
        v = it.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    sid = it.get("source_id")
    if isinstance(sid, str) and sid.strip():
        if source_index:
            src = source_index.get(sid)
            if isinstance(src, dict) and src.get("name"):
                return src["name"]
        return sid.strip()
    return "source"


SLACK_ITEM_SLOTS = 3  # Top-N items surfaced as WFB variables (3 items x 4 + 3 overhead = 15 vars).


def _plain(s):
    """Reduce a value to a single line of plain text safe as a Workflow Builder
    variable VALUE. Verified constraint (live tests against the real Slack
    workspace): content sent as a WFB Text variable value is NOT parsed as
    mrkdwn - `*bold*` shows literal asterisks and `<url|label>` gets stripped to
    a bare URL. So we do NOT add any mrkdwn markup here; the rich frame (bold
    labels, numbering, links) is TYPED into the 'Send a message' step. We only
    normalize whitespace: collapse newlines/tabs/runs of spaces to single spaces
    and trim, so a multi-line summary doesn't break the one-value-per-variable
    mapping. Values stay plain text otherwise."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _headline_with_flag(it):
    """Plain, single-line headline with a leading '[AFFECTS FACTS] ' prefix
    folded in when the item may change a rulebook fact. This replaces the old
    separate item{i}_flag variable so the Slack variable set stays at 15."""
    headline = _plain(it.get("headline", "(no headline)"))
    if it.get("affects_facts"):
        return "[AFFECTS FACTS] " + headline
    return headline


def select_top_picks(ranked_items):
    """Choose the day's TOP 3 items for the Slack payload.

    LLM-judgment path: if any new items carry an explicit `top_pick_rank`
    (integer 1..3, set by the Claude-assisted fetch session per its real
    judgment of what matters to an EB-1/2/3 or H-1B applicant today), honor it -
    rank 1 -> slot 1, rank 2 -> slot 2, rank 3 -> slot 3. Any slot left empty
    (a gap, or a tie where two items claim the same rank so only the first
    lands) is filled from the mechanical `rank_sort_key` ordering, in order,
    skipping items already picked.

    Mechanical fallback: if NO item carries a valid top_pick_rank, return the
    mechanical top 3 (backward-compatible with existing runs).

    `ranked_items` is expected to already be sorted by rank_sort_key
    (highest-first), which is how main() passes it. Returns up to 3 items."""
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

    # Fill any remaining slots from the mechanical order, skipping picked items.
    fill = (it for it in ranked_items if item_key(it) not in picked)
    for i in range(3):
        if slots[i] is None:
            nxt = next(fill, None)
            if nxt is None:
                break
            slots[i] = nxt
            picked.add(item_key(nxt))

    return [s for s in slots if s is not None]


def build_slack_variables(run_date, new_items, digest_rel_path, deduped_count,
                          source_index=None):
    """Build the FLAT dict of named string variables a Workflow Builder
    (/triggers/) webhook maps to workflow variables.

    CONTRACT (verified against the real Slack workspace, do NOT re-litigate):
    a WFB webhook can only receive DATA as top-level named variables; it CANNOT
    receive rich formatting, because a value sent as a Text variable is not
    parsed as mrkdwn. So this function emits PLAIN-TEXT data only. The rich frame
    (bold labels, numbering, hyperlinks) is TYPED into the workflow's 'Send a
    message' step in Workflow Builder - see SLACK_WORKFLOW_SETUP.md.

    Decision: surface the TOP 3 items (chosen by select_top_picks - the fetch's
    LLM top_pick_rank when present, else the mechanical rank). Each item
    contributes 4 data variables (headline, source, url, why) plus 3 overhead
    variables (date, summary, digest) = exactly 15 variables, well under the
    HARD 20-variable WFB cap. The old per-item `_flag` value is folded inline
    into the headline as a leading '[AFFECTS FACTS] ' prefix; the old `more`
    line is folded into `summary`. If fewer than 3 new items exist, the unused
    item slots are filled with EMPTY strings for every field so the workflow
    variables ALWAYS exist (the typed frame for an empty slot renders blank -
    noted as a limitation in the guide).

    Keys returned (15 total):
      date            - run_date (YYYY-MM-DD)
      summary         - e.g. "3 top picks; 1 affects-facts. 92 more in the full digest."
      digest          - digest_rel_path (pointer to full markdown)
      item{i}_headline - plain headline, '[AFFECTS FACTS] '-prefixed when set (i in 1..3)
      item{i}_source   - publisher display name
      item{i}_url      - raw URL (for the workflow's typed hyperlink)
      item{i}_why      - one-sentence why-it-matters

    Values carry NO mrkdwn markup and NO <url|label> link syntax, and are
    single-line (newlines collapsed) - the frame supplies all formatting. This
    is the payload written to the poster file."""
    picks = select_top_picks(new_items)
    affects_total = sum(1 for it in new_items if it.get("affects_facts"))
    remaining = len(new_items) - len(picks)

    if new_items:
        summary = ("%d top pick%s; %d affects-facts."
                   % (len(picks), "" if len(picks) == 1 else "s", affects_total))
        if remaining > 0:
            summary += " %d more in the full digest." % remaining
    else:
        summary = ("No new in-scope immigration news today (EB-1/EB-2/EB-3/H-1B). "
                   "%d item(s) were already reported earlier and skipped."
                   % deduped_count)

    variables = {
        "date": _plain(run_date),
        "summary": _plain(summary),
        "digest": _plain(digest_rel_path),
    }

    for i in range(1, SLACK_ITEM_SLOTS + 1):
        if i <= len(picks):
            it = picks[i - 1]
            variables["item%d_headline" % i] = _headline_with_flag(it)
            variables["item%d_source" % i] = _plain(_slack_source(it, source_index))
            variables["item%d_url" % i] = _plain(it.get("url") or "")
            variables["item%d_why" % i] = _plain(why_it_matters(it))
        else:
            # Empty slot: every field exists but is blank (frame renders blank).
            variables["item%d_headline" % i] = ""
            variables["item%d_source" % i] = ""
            variables["item%d_url" % i] = ""
            variables["item%d_why" % i] = ""

    return variables


def build_source_index(sources_path):
    """Map source_id -> source dict from news_sources.json (best-effort, for
    display names). Missing file is non-fatal - the digest just shows ids."""
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
                    index[src["id"]] = src
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Dedup a daily news-results JSON against a persistent ledger, "
                    "rank the NEW items, write a dated markdown digest, and emit a "
                    "Slack payload (mechanical step; consumes fetch results, never "
                    "scrapes). Personal-learning tool; not legal advice.")
    ap.add_argument("--news-results", required=True,
                    help="Path to the news-results JSON (see news_results_schema.json).")
    ap.add_argument("--date", default=None,
                    help="Canonical run date YYYY-MM-DD. Overrides run_date in the "
                         "news-results file. Wall clock is only a labeled fallback.")
    ap.add_argument("--ledger", default=str(HERE / "news_seen_ledger.json"),
                    help="Path to the persistent seen-ledger JSON (default: "
                         "automation/news_seen_ledger.json). Created if absent.")
    ap.add_argument("--out", default=str(REPO / "news_digests"),
                    help="Digests output directory (default: news_digests/).")
    ap.add_argument("--sources", default=str(HERE / "news_sources.json"),
                    help="Path to news_sources.json (default: automation/news_sources.json). "
                         "Used only for display names; missing is non-fatal.")
    args = ap.parse_args(argv)

    news = load_json(args.news_results)

    # Resolve the canonical run date: --date > news_results.run_date > wall-clock fallback.
    fallback_date_used = False
    if args.date:
        run_date = args.date
    elif news.get("run_date"):
        run_date = news["run_date"]
    else:
        run_date = datetime.date.today().isoformat()
        fallback_date_used = True

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", run_date):
        sys.stderr.write("ERROR: run_date must be YYYY-MM-DD, got %r\n" % run_date)
        return 2

    items = news.get("items", [])
    if not isinstance(items, list):
        sys.stderr.write("ERROR: news-results 'items' must be a list.\n")
        return 2

    ledger = load_ledger(args.ledger)
    seen = set(ledger.get("seen", []))

    source_index = build_source_index(args.sources)

    # Dedup: an item is NEW if its key is not in the ledger AND not already seen
    # earlier in THIS run (intra-run dedup guards against duplicate items in the
    # same fetch file). We do NOT add to the ledger until after a successful write.
    new_items = []
    deduped_items = []
    seen_this_run = set()
    for it in items:
        key = item_key(it)
        if key in seen or key in seen_this_run:
            deduped_items.append(it)
            continue
        seen_this_run.add(key)
        new_items.append(it)

    # Rank NEW items (highest first).
    new_items.sort(key=rank_sort_key, reverse=True)

    affects_count = sum(1 for it in new_items if it.get("affects_facts"))

    # Write the dated HTML digest.
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    digest_path = out_dir / ("%s.html" % run_date)

    deduped_count = len(deduped_items)
    digest_rel = digest_path.relative_to(REPO) if digest_path.is_relative_to(REPO) else digest_path
    _enrich_items_with_descriptions(new_items)
    html = build_digest_html(run_date, new_items, deduped_count, source_index,
                             deduped_items=deduped_items)
    digest_path.write_text(html, encoding="utf-8")

    # Write community.json to the SITE ROOT (next to index.html) so the green
    # card tool can load it same-origin and render a "Recent community chatter"
    # snapshot. Rolling window over the last N days, drawn from ALL fetched items
    # (not just ledger-new ones) and merged with the existing file - NO extra
    # fetch. Always writes a valid file (empty items array on a quiet day) so the
    # tool degrades gracefully. This file MUST be served at the site root.
    write_community_json(items, source_index, REPO / "community.json")

    # Emit the Slack payload: a FLAT JSON dict of named string variables that a
    # Workflow Builder (/triggers/) webhook maps to workflow variables. The rich
    # frame is TYPED into the workflow step; we send DATA only. See
    # build_slack_variables and SLACK_WORKFLOW_SETUP.md.
    slack_path = HERE / (".news_slack_payload_%s.txt" % run_date)
    # The digest variable is a clickable GitHub blob URL so Slack renders it as
    # a link. The workflow commits the HTML file back to main.
    digest_github_url = (
        "https://sweet-selkie-0f1f5f.netlify.app/news_digests/%s.html"
        % run_date
    )
    # Community (unverified crowd) items never surface as a Slack TOP pick - the
    # Slack payload draws only from the news items. Community reports live in the
    # digest's dedicated section, not in the daily headline slots.
    slack_items = [it for it in new_items if not _is_community(it)]
    slack_vars = build_slack_variables(run_date, slack_items, digest_github_url, deduped_count, source_index)
    slack_path.write_text(
        json.dumps(slack_vars, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Update the ledger with all newly-reported ids, then persist.
    for it in new_items:
        seen.add(item_key(it))
    ledger["seen"] = sorted(seen)
    Path(args.ledger).write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # stdout summary.
    print("=" * 70)
    print("news_digest.py - %s%s" % (run_date,
          " (FALLBACK date from wall clock - no run_date/--date supplied)"
          if fallback_date_used else ""))
    print("=" * 70)
    print("  new items:                 %d" % len(new_items))
    print("  deduped as already-seen:   %d" % deduped_count)
    print("  affects_facts:             %d  (may require a rulebook refresh)" % affects_count)
    print("  digest:                    %s" % digest_path)
    print("  slack payload:             %s" % slack_path)
    print("  ledger:                    %s (%d ids total)" % (args.ledger, len(seen)))
    print("")
    if affects_count:
        print("NOTE: %d affects_facts item(s) flagged. If confirmed, run the MONTHLY "
              "facts flow (automation/RUNBOOK.md -> diff_proposal.py) to update the "
              "rulebook." % affects_count)
    print("NEXT STEP (Claude, not Python): post the Slack payload to your self-DM. "
          "Python has no Slack creds - see NEWS_RUNBOOK.md Step 3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
