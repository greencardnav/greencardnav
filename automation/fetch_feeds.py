#!/usr/bin/env python3
"""
fetch_feeds.py - the UNATTENDED news fetcher for the green card tool DAILY news layer.

WHERE THIS SITS IN THE WORKFLOW
-------------------------------
This is a fully-automatable replacement for the "Step 1 FETCH" hand-off in
NEWS_RUNBOOK.md, for the SUBSET of sources that genuinely serve a plain
stdlib/urllib client (no browser, no auth) with an HTTP 200. It produces a
news-results JSON conforming to news_results_schema.json, which the mechanical
core (news_digest.py) then dedups, ranks, and turns into a dated digest + Slack
payload.

HONEST BOUNDARY (read this)
---------------------------
This fetcher ONLY talks to feeds that were verified to answer a plain,
unauthenticated stdlib client with HTTP 200 (see news_sources.json fetch_status):
  - Federal Register API v1 (JSON, no auth)
  - Google News RSS (aggregator search - captures publishers with no direct feed)
  - Murthy / BAL law-firm RSS (direct feeds, verified live)
  - Reddit r/h1b Atom (low-confidence signal)
  - Reddit public per-subreddit SEARCH feeds (search.rss, no auth) for
    crowd-sourced visa-DATE reports - TIER 3 / LOW confidence, rendered in a
    separate 'Community reports (unverified)' section, never sets affects_facts.
    See the COMMUNITY SIGNAL comment block below for the legitimacy rationale
    (public documented endpoints, courteous UA, paced cadence, skip-on-block).

It NEVER scrapes the Cloudflare-walled or bot-blocked official pages
(travel.state.gov, egov.uscis.gov processing-times, USCIS newsroom RSS, etc.) -
those 403 a scripted client and bypassing bot protection is out of bounds. Those
tier-1 reads still require the Claude-assisted WebFetch path in NEWS_RUNBOOK.md,
and the MONTHLY bulletin FACTS still require human review (fetch_bulletin.py +
diff_proposal.py). This fetcher does NOT write rulebook.json.

The User-Agent header set below is normal client COURTESY (identifying the
client and a contact), NOT evasion - we do not spoof a browser or defeat any
challenge; if a source blocks scripted access we simply skip it.

QUALITY FILTERS (three gates, in order)
---------------------------------------
1. RECENCY: an item whose published_date is older than --max-age-days (default 45)
   is DROPPED. Items with a missing/unparseable date are also DROPPED (never
   silently treated as "today"); both drop reasons are counted and logged. A
   daily monitor must not surface a 2018 article as current.
2. SCOPE (precise, word-boundary): scope is EB-1 / EB-2 / EB-3 / H-1B ONLY.
   Matching is regex word-boundary against a curated immigration vocabulary, NOT
   naive substring. Bare "green" / "eb" / "visa" never qualify; only unambiguous
   terms like "green card", "priority date", "H-1B", "EB-2". Items matching none
   are DROPPED before they reach the digest.
3. affects_facts GATE: fires ONLY for a TIER-1 item that is in-scope AND mentions
   a rulebook-relevant fact (fee | priority date | visa bulletin | prevailing
   wage | PERM | final rule | H-1B cap). A generic "visa" notice never sets it.

Scope: EB-1, EB-2, EB-3, and H-1B ONLY. Personal-learning project. NOT legal
advice, NOT official guidance.

Usage:
  python3 fetch_feeds.py [--out news_results.json] [--date YYYY-MM-DD]
                         [--max-age-days 45] [--window-days 1] [--verbose]

stdlib only: urllib.request, json, xml.etree.ElementTree, html, re, datetime,
email.utils, argparse, hashlib, pathlib, sys.
"""

import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Descriptive User-Agent = client courtesy (identify ourselves + a contact), NOT
# evasion. We never spoof a browser or defeat a bot challenge; blocked sources
# are simply skipped.
USER_AGENT = "green-card-monitor/1.0 (personal learning project)"
TIMEOUT_SECONDS = 20

# Default recency window. Generous enough to catch a monthly-cadence item (a new
# Visa Bulletin, a monthly practitioner roundup) but tight enough to kill stale
# 2018-2021 junk that law-firm feeds sometimes resurface. Overridable via
# --max-age-days.
DEFAULT_MAX_AGE_DAYS = 45

# ---------------------------------------------------------------------------
# Precise scope classification. Scope is EB-1 / EB-2 / EB-3 / H-1B ONLY. Every
# term below is an UNAMBIGUOUS immigration / employment-visa token, matched with
# WORD BOUNDARIES so unrelated substrings never trip the filter:
#   - "Green Canyon Block 205A" (a maritime rule) does NOT match \bgreen card\b
#   - "EB" inside a random word does NOT match \bEB-?[123]\b
#   - bare "visa" (e.g. "Visa Bond Program") is NOT in the vocabulary at all
# An item that matches none of these buckets is dropped before the digest.
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
# Cross-cutting terms: the employment-based system broadly. A match => in scope,
# category resolves to "cross-cutting" unless exactly one specific category above
# also matched. NOTE: only "green card" (never bare "green") and specific
# employment/EB/H-1B terms; generic "visa" is intentionally excluded so visitor /
# bond / consular notices do NOT qualify.
CROSSCUTTING_PATTERNS = [
    r"\bemployment-based\b", r"\bemployment based\b", r"\bpriority dates?\b",
    r"\bvisa bulletin\b", r"\bPERM\b", r"\bprevailing wage\b",
    r"\blabor certification\b", r"\bI-140\b", r"\bI-485\b",
    r"\bpremium processing\b",
    r"\bform I-907\b", r"\bI-907\b", r"\bgreen cards?\b",
    r"\bemployment-based green card\b", r"\bgreen[- ]card backlog\b",
]
# "Adjustment of status" (Form I-485) is NOT in the plain cross-cutting list on
# its own: AOS applies to family-based, asylum, and other out-of-scope cases too.
# It only counts as in-scope when an EB / H-1B / employment-context token
# CO-OCCURS in the same text (see classify_category). This keeps a bare
# "family-based adjustment of status" memo out of the employment-based digest.
_AOS_RE = re.compile(r"\badjustment of status\b", re.IGNORECASE)
_AOS_EMPLOYMENT_CONTEXT_RE = None  # compiled below, after _compile is defined


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_CATEGORY_RE = {cat: _compile(pats) for cat, pats in CATEGORY_PATTERNS.items()}
_CROSSCUT_RE = _compile(CROSSCUTTING_PATTERNS)

# Employment-context tokens that must co-occur with "adjustment of status" for an
# AOS item to be in scope. Bare "adjustment of status" also covers family-based
# cases, so it does NOT qualify alone. Includes the specific EB/H-1B category
# terms plus the employment-based cross-cutting vocabulary.
_AOS_EMPLOYMENT_CONTEXT_RE = _compile(
    [p for pats in CATEGORY_PATTERNS.values() for p in pats]
    + CROSSCUTTING_PATTERNS)

# Topic controlled vocabulary (must match news_results_schema.json enum). These
# only LABEL an already-in-scope item, so plain substring is acceptable here.
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
                          "perm processing"]),
]

# Importance heuristics (keyword-driven; label-only, substring is fine).
HIGH_IMPORTANCE_TERMS = ["final rule", "proposed rule", "lottery",
                         "random selection", "fee", "fees", "new visa bulletin",
                         "premium processing", "priority date rule",
                         "wage-selection", "wage selection"]
MEDIUM_IMPORTANCE_TERMS = ["guidance", "policy manual", "rfe",
                           "request for evidence", "processing time",
                           "clarifies", "updates"]

# ---------------------------------------------------------------------------
# affects_facts gate. A fact in rulebook.json plausibly changed. This fires ONLY
# for a TIER-1 (Federal Register / official) item that is BOTH in-scope AND
# mentions one of these rulebook-relevant tokens. A generic notice that merely
# mentions "visa" must NOT set affects_facts.
# ---------------------------------------------------------------------------
AFFECTS_FACTS_PATTERNS = [
    r"\bfees?\b", r"\bpriority dates?\b", r"\bvisa bulletin\b",
    r"\bprevailing wage\b", r"\bPERM\b", r"\bfinal rule\b", r"\bH-?1B cap\b",
]
_AFFECTS_FACTS_RE = _compile(AFFECTS_FACTS_PATTERNS)

# ---------------------------------------------------------------------------
# NEAR-DUPLICATE STORY CLUSTERING (stdlib only, no ML). The live run showed the
# top items were several outlets covering the SAME 1-2 stories (e.g. the
# "$100,000 H-1B fee" litigation; the "DHS 9-11 fee expansion to H-1B/L-1").
# We collapse same-story items to a single representative before writing the
# output, so downstream top-N selection sees DISTINCT stories.
#
# Two items are treated as the SAME story if their significant-token sets have
# Jaccard overlap >= JACCARD_SAME_STORY, OR they share a rare distinctive bigram
# (e.g. "100000"+"fee", "9-11"+"fee"). We are deliberately CONSERVATIVE: a
# false merge (two real stories collapsed into one) is worse than a near-dup
# slipping through, so the threshold is high and merging is transitive only
# through direct pairwise matches.
# ---------------------------------------------------------------------------
JACCARD_SAME_STORY = 0.6

# Very common words that carry no story identity. Distinctive immigration tokens
# (100000, 9-11, fee, h-1b, l-1, renewal, premium, processing, cap, lottery,
# etc.) are intentionally NOT in this list - they are exactly the signal we keep.
_STORY_STOPWORDS = frozenset([
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "but", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "it", "its", "this", "that", "these", "those", "will", "would", "can",
    "could", "may", "might", "has", "have", "had", "new", "over", "into",
    "amid", "after", "before", "how", "what", "why", "who", "when", "us", "u",
    "says", "say", "said", "report", "reports", "update", "updates", "news",
])

# Distinctive tokens whose SHARED presence across two items is a same-story
# signal even when overall Jaccard is under threshold. Split into two sets:
#   _RARE_STORY_TOKENS  = terms that PIN a specific story (a dollar amount, a
#                         named fee, a specific litigation/proclamation). Sharing
#                         one of these is strong evidence of the same story.
#   _DOMAIN_DISTINCTIVE = terms that are distinctive vs. stopwords but are COMMON
#                         across employment-immigration stories (fee, h-1b, cap).
#                         Sharing these alone is NOT enough - many unrelated
#                         stories mention "h-1b" and "fee".
# A distinctive-bigram match requires >= 2 shared distinctive tokens of which at
# least ONE is a rare story-pinning token (e.g. "100000"+"fee", "9-11"+"fee").
# This deliberately does NOT merge two different stories that merely share the
# generic pair "h-1b"+"fee".
_RARE_STORY_TOKENS = frozenset([
    "100000", "9-11", "l-1", "l1", "lottery", "litigation", "lawsuit",
    "proclamation", "injunction", "retrogression", "retrogress",
])
_DOMAIN_DISTINCTIVE = frozenset([
    "fee", "fees", "h-1b", "h1b", "renewal", "premium", "processing", "cap",
    "dhs", "uscis", "perm", "eb-1", "eb-2", "eb-3", "wage",
])
_DISTINCTIVE_TOKENS = _RARE_STORY_TOKENS | _DOMAIN_DISTINCTIVE

FR_AGENCIES = [
    # All four slugs verified live against /api/v1/agencies.json on 2026-08-07.
    "u-s-citizenship-and-immigration-services",
    # NOTE: the Federal Register agency slug for State is "state-department"
    # (VERIFIED valid). The plain "department-of-state" form is NOT a valid slug
    # (confirmed absent from agencies.json / returns 400), so we use the
    # canonical slug the API accepts.
    "state-department",
    "employment-and-training-administration",
    "homeland-security-department",
]

# Google News targeted queries (aggregator; tier 3, low confidence). This is how
# publishers with no working direct feed (AILA, Fragomen, Boundless, NFAP/Forbes,
# Morgan Lewis, NAFSA, USCIS/DOS/DOL newsrooms) are still captured - see
# fetch_status "via-google-news" in news_sources.json.
GOOGLE_NEWS_QUERIES = [
    "H-1B visa",
    "EB-2 India priority date",
    "visa bulletin EB-3",
    "USCIS employment green card",
    "EB-1 priority date",
]

# ---------------------------------------------------------------------------
# COMMUNITY SIGNAL (Reddit public read endpoints) - TIER 3, LOW CONFIDENCE.
#
# WHY THIS IS LEGITIMATE (not scraping / not a bypass):
#   - Reddit PUBLISHES per-subreddit search as a PUBLIC, documented feed:
#       https://www.reddit.com/r/<sub>/search.rss?q=...&restrict_sr=1&sort=new&t=week
#     It requires NO login, NO OAuth, and returns standard Atom XML. Reading it
#     is exactly what the endpoint is FOR. (The existing r/h1b/.rss fetch above
#     uses the same public-feed mechanism.)
#   - We send a descriptive, honest User-Agent (identify the client + purpose),
#     the same courtesy as every other feed here. We do NOT spoof a browser and
#     we do NOT defeat any bot / Cloudflare challenge.
#   - We RESPECT rate limits: a modest fixed sleep between requests and a small,
#     curated query set (not a full sub x keyword cross-product). On ANY 403/429/
#     timeout we SKIP that query and move on - we never retry-hammer or evade.
#   - We READ public posts only. No posting, no auth-walled content, no private
#     data, no user PII beyond the public post title + link the feed already
#     serves.
#   - For higher volume, Reddit's official OAuth API (a registered "script" app)
#     is the documented path; the public search feed is sufficient at this low
#     daily volume, so we use it and keep OAuth as a future option.
#
# WHAT THIS DATA IS (and is NOT): anecdotal, crowd-sourced date reports ("got my
# Mumbai dropbox slot", "EB-2 India moved", "221g cleared"). It is a SIGNAL, not
# an authority. Community items are TIER 3 / LOW confidence, are rendered in a
# SEPARATE 'Community reports (unverified)' section of the digest with a
# "verify against official sources" disclaimer, and can NEVER set affects_facts
# or trigger the monthly rulebook refresh. Marked by a 'community-reddit-*'
# source_id prefix that the digest renderer keys on.
# ---------------------------------------------------------------------------
COMMUNITY_REQUEST_SLEEP_SECONDS = 2.0  # courteous pacing between Reddit reads

# ---------------------------------------------------------------------------
# CURATED SUBREDDIT REGISTRY (replaces the old flat (sub, query) list).
#
# Each entry: {tier, enabled, cats, strict}
#   tier    = "core" (fetch every run) | "rotating" (fetch a subset per run,
#             round-robin by day-of-year - see select_subreddits_for_run).
#   enabled = whether this sub participates at all. ONLY the four confirmed-active
#             subs are enabled today; the "verify-before-enabling" subs from the
#             plan are present but DISABLED (enabled:False) pending a one-time
#             manual Phase-0 confirmation (hit old.reddit.com/r/<sub>/new.rss from
#             a residential connection and confirm an active feed) before flipping
#             them on. The rotation code below already handles them so no code
#             change is needed when they are enabled.
#   cats    = the sub's DEFAULT taxonomy categories, used to SEED an item's
#             category array before per-post keyword refinement (classify_categories).
#   strict  = broad/noisy subs (nri, ABCDesis) require a stricter relevance gate
#             (must hit a real immigration token, not just an India/geography word).
#
# With only the 4 core subs enabled and a per-run budget of 6, all 4 fetch every
# run; the rotating slots simply go unused until more subs are enabled.
# ---------------------------------------------------------------------------
COMMUNITY_SUBREDDITS = {
    # --- CORE: confirmed active, fetched every run ---
    "immigration": {"tier": "core", "enabled": True,  "cats": ["general"],       "strict": False},
    "USCIS":       {"tier": "core", "enabled": True,  "cats": ["general"],       "strict": False},
    "h1b":         {"tier": "core", "enabled": True,  "cats": ["work_visas"],    "strict": False},
    "f1visa":      {"tier": "core", "enabled": True,  "cats": ["students_opt"],  "strict": False},
    # --- ROTATING: DISABLED pending one-time manual Phase-0 confirmation.
    #     Do NOT enable without confirming each returns an active feed first
    #     (Reddit blocks datacenter/CI IPs, so CI cannot self-confirm these). ---
    "immigrationlaw": {"tier": "rotating", "enabled": False, "cats": ["employment_gc"], "strict": False},
    "AskImmigration": {"tier": "rotating", "enabled": False, "cats": ["general"],       "strict": False},
    "greencard":      {"tier": "rotating", "enabled": False, "cats": ["employment_gc"], "strict": False},
    "AskDS":          {"tier": "rotating", "enabled": False, "cats": ["consular"],      "strict": False},
    "nri":            {"tier": "rotating", "enabled": False, "cats": ["country"],       "strict": True},
    "ABCDesis":       {"tier": "rotating", "enabled": False, "cats": ["country"],       "strict": True},
}

# Per-run fetch budget and rotation. Hard cap of 6 subreddit reads per run; core
# subs fetch every run, remaining budget is filled with rotating subs on a
# day-of-year round-robin so all rotating subs are covered within the window.
COMMUNITY_PER_RUN_BUDGET = 6
COMMUNITY_ROTATING_PER_RUN = 2

# ---------------------------------------------------------------------------
# NESTED CATEGORY TAXONOMY. Ordered top-level categories + label + member subs.
# Ships in community.json (schema:2) so the UI and fetcher read ONE source of
# truth and never drift. A single Reddit post can belong to several categories,
# so items carry an ARRAY of category ids (see classify_categories).
# ---------------------------------------------------------------------------
COMMUNITY_TAXONOMY = [
    {"id": "general",       "label": "General & News",                    "subs": ["immigration", "USCIS", "AskImmigration"]},
    {"id": "employment_gc", "label": "Employment-Based Green Card",       "subs": ["immigration", "USCIS", "greencard", "immigrationlaw"]},
    {"id": "family_gc",     "label": "Family-Based Green Card",           "subs": ["immigration", "USCIS", "greencard"]},
    {"id": "work_visas",    "label": "Work Visas & Status",               "subs": ["h1b", "immigration", "f1visa"]},
    {"id": "consular",      "label": "Consular & Stamping",               "subs": ["AskDS", "h1b", "immigration", "f1visa"]},
    {"id": "students_opt",  "label": "Students & OPT",                    "subs": ["f1visa", "immigration"]},
    {"id": "country",       "label": "Country-Specific (India / China)",  "subs": ["nri", "ABCDesis", "immigration", "h1b"]},
]
_VALID_CATEGORY_IDS = frozenset(t["id"] for t in COMMUNITY_TAXONOMY)

# Per-post category keyword rules (word-boundary, case-insensitive). An item can
# match several categories; results are UNIONed with the sub's default cats.
COMMUNITY_CATEGORY_PATTERNS = {
    "employment_gc": [
        r"\bEB-?1\b", r"\bEB-?2\b", r"\bEB-?3\b", r"\bNIW\b",
        r"\bnational interest waiver\b", r"\bPERM\b", r"\bprevailing wage\b",
        r"\blabor cert\w*\b", r"\bI-?140\b", r"\bpriority dates?\b",
        r"\bemployment-based\b",
    ],
    "family_gc": [
        r"\bI-?130\b", r"\bmarriage green card\b", r"\bspouse visa\b",
        r"\bCR-?1\b", r"\bIR-?1\b", r"\bF2A\b", r"\bF2B\b", r"\bF3\b", r"\bF4\b",
        r"\bfamily-based\b", r"\bfianc",
    ],
    "work_visas": [
        r"\bH-?1B\b", r"\bH-?4\b", r"\bL-?1\b", r"\bO-?1\b", r"\bTN\b",
        r"\bchange of status\b", r"\bCOS\b", r"\bEAD\b",
        r"\bpremium processing\b", r"\bcap-?gap\b", r"\btransfer\b",
    ],
    "consular": [
        r"\bdropbox\b", r"\bdrop box\b", r"\bstamping\b", r"\b221\s*\(?g\)?\b",
        r"\badministrative processing\b", r"\bconsulate\b", r"\bembassy\b",
        r"\binterview waiver\b", r"\bDS-?160\b", r"\bvisa slot\b",
        r"\bappointment\b", r"\bMumbai\b", r"\bHyderabad\b", r"\bNew Delhi\b",
        r"\bChennai\b", r"\bKolkata\b", r"\bGuangzhou\b",
    ],
    "students_opt": [
        r"\bOPT\b", r"\bSTEM OPT\b", r"\bCPT\b", r"\bSEVIS\b", r"\bI-?20\b",
        r"\bF-?1\b", r"\bday 1 cpt\b",
    ],
    # 'country' additionally REQUIRES a co-occurring immigration token (below) so
    # a pure India/China geography mention without visa context does not match.
    "country": [
        r"\bIndia\b", r"\bIndian\b", r"\bChina\b", r"\bChinese\b", r"\bMumbai\b",
        r"\bHyderabad\b", r"\bDelhi\b", r"\bChennai\b", r"\bKolkata\b",
        r"\bBangalore\b", r"\bGuangzhou\b", r"\bBeijing\b",
    ],
}
_COMMUNITY_CATEGORY_RE = {
    cat: _compile(pats) for cat, pats in COMMUNITY_CATEGORY_PATTERNS.items()
}

# A real immigration/visa token. Used two ways: (a) the extra AND-condition for
# the 'country' category, and (b) the strict relevance gate for broad subs.
COMMUNITY_IMMIGRATION_TOKENS = [
    r"\bH-?1B\b", r"\bH-?4\b", r"\bL-?1\b", r"\bO-?1\b", r"\bgreen cards?\b",
    r"\bEB-?1\b", r"\bEB-?2\b", r"\bEB-?3\b", r"\bNIW\b", r"\bdropbox\b",
    r"\bconsulate\b", r"\bembassy\b", r"\b221\s*\(?g\)?\b", r"\bpriority dates?\b",
    r"\bvisa slot\b", r"\bvisa bulletin\b", r"\bUSCIS\b", r"\bI-?140\b",
    r"\bI-?485\b", r"\bI-?130\b", r"\bOPT\b", r"\bstamping\b",
    r"\binterview waiver\b", r"\bEAD\b", r"\bcap-?gap\b", r"\bPERM\b",
]
_COMMUNITY_IMMIGRATION_RE = _compile(COMMUNITY_IMMIGRATION_TOKENS)

# Fine-grained (UI-only) topic labels for a community item. Optional; used as a
# small tag in the UI. NOT tied to the news schema topic enum.
COMMUNITY_FINE_TOPIC_PATTERNS = [
    ("consular-stamping", [r"\bdropbox\b", r"\bdrop box\b", r"\bstamping\b",
                           r"\b221\s*\(?g\)?\b", r"\bconsulate\b", r"\bembassy\b",
                           r"\binterview waiver\b", r"\bvisa slot\b",
                           r"\bappointment\b", r"\badministrative processing\b",
                           r"\bDS-?160\b"]),
    ("priority-dates",   [r"\bpriority dates?\b", r"\bvisa bulletin\b",
                          r"\bretrogress\w*\b", r"\bdate movement\b",
                          r"\bbacklog\b", r"\bfinal action date\b",
                          r"\bdates for filing\b"]),
    ("opt-stem",         [r"\bSTEM OPT\b", r"\bOPT\b", r"\bCPT\b", r"\bSEVIS\b",
                          r"\bI-?20\b"]),
    ("rfe-trends",       [r"\bRFE\b", r"\brequests? for evidence\b"]),
    ("h1b-lottery",      [r"\blottery\b", r"\bregistration\b", r"\bselection\b",
                          r"\bcap-?gap\b"]),
]
_COMMUNITY_FINE_TOPIC_RE = [
    (label, _compile(pats)) for label, pats in COMMUNITY_FINE_TOPIC_PATTERNS
]

# Community RELEVANCE vocabulary. Community date-report posts often do NOT use
# the strict EB/H-1B word-boundary tokens that classify_category requires (a
# "got my Mumbai dropbox slot" post mentions none of them), so we accept an item
# into the community section if it matches EITHER the main scope OR one of these
# visa-date / consular tokens. This keeps the crowd signal on-topic (real visa
# process chatter) without pulling in unrelated subreddit noise. Word-boundary
# matched, case-insensitive.
COMMUNITY_RELEVANCE_PATTERNS = [
    r"\bdropbox\b", r"\bvisa slot\b", r"\bslots?\b", r"\bappointment\b",
    r"\bstamping\b", r"\bconsulate\b", r"\bembassy\b",
    r"\bMumbai\b", r"\bHyderabad\b", r"\bNew Delhi\b", r"\bDelhi\b",
    r"\bChennai\b", r"\bKolkata\b",
    r"\b221\s*\(?g\)?\b", r"\b214\s*\(?b\)?\b", r"\badministrative processing\b",
    r"\bEB-?2 India\b", r"\bEB-?3 India\b", r"\bpriority dates?\b",
    r"\bvisa bulletin\b", r"\bH-?1B\b", r"\bcap[- ]?gap\b", r"\bstamped\b",
    r"\binterview waiver\b", r"\bdomestic (?:visa )?renewal\b",
]
_COMMUNITY_RELEVANCE_RE = _compile(COMMUNITY_RELEVANCE_PATTERNS)

# Consular / appointment tokens that map a community post to the closest valid
# topic enum value ('processing-times'), since the schema topic enum has no
# dedicated 'consular' value.
_COMMUNITY_PROCESSING_RE = _compile([
    r"\bdropbox\b", r"\bslots?\b", r"\bappointment\b", r"\bstamping\b",
    r"\bconsulate\b", r"\bembassy\b", r"\bstamped\b", r"\binterview waiver\b",
    r"\b221\s*\(?g\)?\b", r"\badministrative processing\b",
])


def log(msg, verbose):
    if verbose:
        sys.stderr.write("[fetch_feeds] %s\n" % msg)


def http_get(url, verbose):
    """GET a URL with a descriptive UA and a short timeout. Returns bytes.
    Raises on any failure so the per-source caller can catch and continue."""
    log("GET %s" % url, verbose)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return resp.read()


def normalize_title(title):
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


def stable_id(source_id, title, published_date):
    """Stable dedup id: sha1(source_id|normalized_title|published_date)[:16].
    Same story => same id across days, so the news_digest ledger dedups it."""
    basis = "%s|%s|%s" % (source_id, normalize_title(title), published_date or "")
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def parse_date_any(raw):
    """Best-effort parse of a date/datetime string into YYYY-MM-DD. Returns
    None if nothing parseable is found (the caller then DROPS the item rather
    than pretending it is current)."""
    if not raw:
        return None
    raw = raw.strip()
    # Already ISO date/datetime (Federal Register publication_date, ISO pubDate).
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    # RFC 822 (RSS pubDate), e.g. "Wed, 27 Jul 2026 14:30:00 +0000" or
    # "Wed, 06 Aug 2026 14:30:00 GMT". email.utils.parsedate_to_datetime is
    # stdlib and handles the numeric-offset and named-zone forms.
    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return dt.date().isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    # Fallback: find a "DD Mon YYYY" or "Mon DD, YYYY" fragment.
    try:
        m2 = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", raw)
        if m2:
            return datetime.datetime.strptime(
                "%s %s %s" % (m2.group(1), m2.group(2)[:3], m2.group(3)),
                "%d %b %Y").date().isoformat()
        m3 = re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),?\s+(\d{4})", raw)
        if m3:
            return datetime.datetime.strptime(
                "%s %s %s" % (m3.group(1)[:3], m3.group(2), m3.group(3)),
                "%b %d %Y").date().isoformat()
    except ValueError:
        pass
    return None


def days_old(pub_iso, run_date):
    """How many days before run_date the item was published. Negative = future
    (kept). None if either date is unparseable."""
    try:
        p = datetime.date.fromisoformat(pub_iso)
        r = datetime.date.fromisoformat(run_date)
    except (TypeError, ValueError):
        return None
    return (r - p).days


def classify_category(text):
    """Return an in-scope category string, or None if out of scope.
    Word-boundary match against the curated EB / H-1B / cross-cutting vocabulary.
    A single specific EB/H-1B match wins; multiple specific matches or only
    cross-cutting terms resolve to 'cross-cutting'."""
    t = text or ""
    matched = [cat for cat, res in _CATEGORY_RE.items()
               if any(r.search(t) for r in res)]
    crosscut = any(r.search(t) for r in _CROSSCUT_RE)
    # "adjustment of status" is in scope ONLY when an EB / H-1B / employment
    # token co-occurs. Alone it also matches family-based AOS, which is out of
    # scope, so a bare AOS memo with no employment context must NOT qualify.
    aos_in_scope = bool(_AOS_RE.search(t)
                        and any(r.search(t) for r in _AOS_EMPLOYMENT_CONTEXT_RE))
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return "cross-cutting"
    if crosscut or aos_in_scope:
        return "cross-cutting"
    return None


def classify_topic(text):
    t = (text or "").lower()
    for topic, pats in TOPIC_PATTERNS:
        if any(p in t for p in pats):
            return topic
    return "policy"


def classify_importance(text, is_fr_rule=False):
    t = (text or "").lower()
    if is_fr_rule and any(term in t for term in ("fee", "fees", "priority date",
                                                 "premium processing",
                                                 "wage-selection", "wage selection")):
        return "high"
    if any(term in t for term in HIGH_IMPORTANCE_TERMS):
        return "high"
    if any(term in t for term in MEDIUM_IMPORTANCE_TERMS):
        return "medium"
    return "low"


def affects_facts_gate(text, tier, in_scope):
    """affects_facts fires ONLY for a tier-1, in-scope item that mentions a
    rulebook-relevant fact (fee | priority date | visa bulletin | prevailing
    wage | PERM | final rule | H-1B cap). Tier-2/3 items never set it; a generic
    'visa' notice never sets it."""
    if tier != 1 or not in_scope:
        return False
    t = text or ""
    return any(r.search(t) for r in _AFFECTS_FACTS_RE)


def make_item(source_id, tier, confidence, headline, url, published_date,
              category, topic, summary, importance, affects_facts):
    return {
        "id": stable_id(source_id, headline, published_date),
        "headline": headline,
        "url": url,
        "source_id": source_id,
        "published_date": published_date,
        "category": category,
        "topic": topic,
        "summary": summary,
        "importance": importance,
        "affects_facts": affects_facts,
        "confidence": confidence,
        "tier": tier,
    }


# ---------------------------------------------------------------------------
# Near-duplicate story clustering helpers (Fix 2). Stdlib only.
# ---------------------------------------------------------------------------
_OUTLET_SUFFIX_RE = re.compile(r"\s+[-|]\s+[^-|]+$")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def story_signature(headline):
    """Normalized significant-token set for a headline, for near-dup detection.
    Lowercase; strip a trailing ' - <outlet>' / ' | <outlet>' suffix (Google News
    appends the publisher); drop currency/thousands punctuation so '$100,000'
    becomes the token '100000'; keep internal hyphens so distinctive tokens like
    'h-1b', 'l-1', '9-11' survive; drop stopwords. Returns a set of tokens."""
    t = (headline or "").lower()
    t = _OUTLET_SUFFIX_RE.sub("", t)          # strip trailing outlet suffix
    t = t.replace("$", "").replace(",", "")   # "$100,000" -> "100000"
    tokens = _TOKEN_RE.findall(t)
    return set(tok for tok in tokens if tok not in _STORY_STOPWORDS)


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def same_story(sig_a, sig_b):
    """True if two token-set signatures describe the same story. Match if Jaccard
    overlap >= JACCARD_SAME_STORY, OR they share >= 2 distinctive tokens (a rare
    distinctive bigram, e.g. '100000'+'fee' or '9-11'+'fee'). Conservative by
    design: when unsure, return False and keep the items separate."""
    if _jaccard(sig_a, sig_b) >= JACCARD_SAME_STORY:
        return True
    shared_distinctive = (sig_a & sig_b) & _DISTINCTIVE_TOKENS
    # Require a distinctive BIGRAM (>= 2 shared distinctive tokens) AND at least
    # one of them to be a RARE story-pinning token. Two stories sharing only the
    # generic pair "h-1b"+"fee" must NOT merge - a false merge is worse than a
    # near-dup slipping through.
    return (len(shared_distinctive) >= 2
            and bool(shared_distinctive & _RARE_STORY_TOKENS))


def _rep_rank(item):
    """Sort key to pick a cluster's representative: highest authority first
    (tier 1 > 2 > 3), then a named practitioner/official over a generic
    aggregator (bare 'google-news' or Reddit), then most recent. Higher sorts
    first (used with max())."""
    tier = item.get("tier")
    tier_rank = (4 - tier) if isinstance(tier, int) else 0
    sid = (item.get("source_id") or "").lower()
    named = 0 if sid in ("google-news", "reddit-immigration") else 1
    pub = item.get("published_date") or ""  # ISO date sorts chronologically
    return (tier_rank, named, pub)


def cluster_near_duplicates(items):
    """Collapse near-duplicate stories to one representative each. Returns
    (kept_items, collapsed_count). Each cluster keeps the highest-authority /
    most-recent representative (per _rep_rank); when a cluster has >1 member the
    representative's summary gets a '(also reported by N other outlets)' note.
    The schema forbids new item fields (additionalProperties:false), so the note
    is folded into the existing summary text rather than a new field.

    Clustering is greedy and matches each item against a cluster's SEED signature
    only (no chained transitive merges), keeping false merges unlikely."""
    clusters = []  # each: {"seed_sig": set, "members": [item, ...]}
    for it in items:
        sig = story_signature(it.get("headline"))
        placed = False
        for cl in clusters:
            if same_story(sig, cl["seed_sig"]):
                cl["members"].append(it)
                placed = True
                break
        if not placed:
            clusters.append({"seed_sig": sig, "members": [it]})

    kept = []
    collapsed = 0
    for cl in clusters:
        members = cl["members"]
        rep = max(members, key=_rep_rank)
        others = len(members) - 1
        if others > 0:
            note = " (also reported by %d other outlet%s)" % (
                others, "" if others == 1 else "s")
            rep["summary"] = (rep.get("summary", "") + note)[:600]
            collapsed += others
        kept.append(rep)
    return kept, collapsed


class DropStats(object):
    """Counts items dropped by each quality gate, for the run report."""

    def __init__(self):
        self.stale = 0
        self.no_date = 0

    def recency_ok(self, pub_iso, run_date, max_age_days):
        """True if the item is recent enough to keep. Increments the relevant
        drop counter and returns False otherwise. A missing/unparseable date is
        a drop (no_date) - we never treat it as 'today'."""
        if not pub_iso:
            self.no_date += 1
            return False
        age = days_old(pub_iso, run_date)
        if age is None:
            self.no_date += 1
            return False
        if age > max_age_days:
            self.stale += 1
            return False
        return True


# ---------------------------------------------------------------------------
# Federal Register API v1 (JSON, no auth). Fully unattended. TIER 1.
# ---------------------------------------------------------------------------
def fetch_federal_register(run_date, max_age_days, drops, verbose):
    kept = []
    fetched = 0
    for agency in FR_AGENCIES:
        # Build the EXACT bracket-param form (do not percent-encode the literal
        # bracket keys; only encode values). Do NOT use format=rss (302 -> unblock).
        parts = [
            "conditions[agencies][]=%s" % urllib.parse.quote(agency, safe=""),
            "conditions[type][]=RULE",
            "conditions[type][]=PRORULE",
            "conditions[type][]=NOTICE",
            "fields[]=title",
            "fields[]=publication_date",
            "fields[]=abstract",
            "fields[]=html_url",
            "fields[]=document_number",
            "fields[]=type",
            "per_page=20",
            "order=newest",
        ]
        url = ("https://www.federalregister.gov/api/v1/documents.json?"
               + "&".join(parts))
        try:
            raw = http_get(url, verbose)
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - one dead agency must not kill the run
            log("Federal Register agency %s FAILED: %s" % (agency, exc), verbose)
            continue
        results = data.get("results", []) if isinstance(data, dict) else []
        fetched += len(results)
        for r in results:
            title = (r.get("title") or "").strip()
            abstract = (r.get("abstract") or "").strip()
            text = "%s %s" % (title, abstract)
            category = classify_category(text)
            if category is None:
                continue  # out of scope (EB/H-1B only)
            # RECENCY: Federal Register always carries a reliable publication_date.
            pub = parse_date_any(r.get("publication_date"))
            if not drops.recency_ok(pub, run_date, max_age_days):
                continue
            fr_type = (r.get("type") or "").upper()
            url_html = r.get("html_url") or ""
            topic = classify_topic(text)
            is_rule = fr_type in ("RULE", "PRORULE")
            importance = classify_importance(text, is_fr_rule=is_rule)
            # affects_facts: tier-1 + in-scope + rulebook-relevant token.
            affects = affects_facts_gate(text, tier=1, in_scope=True)
            summary = abstract if abstract else (
                "Federal Register %s: %s" % (fr_type.title() or "document", title))
            summary = summary[:600]
            kept.append(make_item(
                source_id="federal-register-uscis", tier=1, confidence="high",
                headline=title or "(untitled Federal Register document)",
                url=url_html, published_date=pub, category=category,
                topic=topic, summary=summary, importance=importance,
                affects_facts=affects))
    return fetched, kept


# ---------------------------------------------------------------------------
# Generic RSS 2.0 / Atom parsing with xml.etree. Handles both shapes.
# ---------------------------------------------------------------------------
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def parse_feed_entries(raw_bytes):
    """Return a list of dicts {title, link, pubDate, source} from RSS or Atom.
    Robust to a leading BOM / whitespace. Raises ET.ParseError on bad XML."""
    text = raw_bytes.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    root = ET.fromstring(text)
    entries = []
    # RSS 2.0: <rss><channel><item>...
    items = root.findall(".//item")
    if items:
        for it in items:
            src_el = it.find("source")
            entries.append({
                "title": html.unescape(_text(it.find("title"))),
                "link": _text(it.find("link")),
                "pubDate": _text(it.find("pubDate")),
                "source": html.unescape(_text(src_el)) if src_el is not None else "",
            })
        return entries
    # Atom: <feed><entry>...
    for en in root.findall("%sentry" % ATOM_NS):
        link_el = en.find("%slink" % ATOM_NS)
        link = link_el.get("href") if link_el is not None else ""
        updated = _text(en.find("%supdated" % ATOM_NS)) or _text(
            en.find("%spublished" % ATOM_NS))
        entries.append({
            "title": html.unescape(_text(en.find("%stitle" % ATOM_NS))),
            "link": link,
            "pubDate": updated,
            "source": "",
        })
    return entries


def fetch_rss_source(url, source_id, tier, confidence, run_date, max_age_days,
                     drops, verbose, aggregator=False):
    """Fetch one RSS/Atom feed and map in-scope, recent entries to news items.

    aggregator=True marks a Google News aggregator query. For those entries the
    Google News <item> carries a <source url="...">Publisher Name</source>
    sub-element (already parsed into e["source"]); we use that publisher as the
    item's DISPLAY source label instead of the literal 'google-news'. The
    downstream tier (1 > 2 > 3) is carried by the separate `tier` field, so
    tiering is unaffected by relabeling the display source.

    URL tradeoff: Google News link is a news.google.com/rss/articles/CBMi...
    redirect that cannot be decoded to the publisher URL without an extra
    network call, which we do NOT do. The redirect resolves fine when clicked,
    so we keep it as-is and only fix the display LABEL, not the URL.
    """
    raw = http_get(url, verbose)  # may raise; caller catches
    entries = parse_feed_entries(raw)
    kept = []
    for e in entries:
        title = e["title"]
        if not title:
            continue
        text = title  # RSS titles are the reliable signal; summaries vary
        category = classify_category(text)
        if category is None:
            continue
        # RECENCY: RSS pubDate (RFC-822 or ISO). Missing/unparseable => drop,
        # never fall back to run_date and mask a stale item as current.
        pub = parse_date_any(e["pubDate"])
        if not drops.recency_ok(pub, run_date, max_age_days):
            continue
        topic = classify_topic(text)
        importance = classify_importance(text)
        # affects_facts triggers the human MONTHLY facts flow, so gate it to
        # tier-1 + in-scope + a rulebook-relevant token. Tier-2/3 feeds
        # (practitioner alerts, Google News, Reddit) never set it.
        affects = affects_facts_gate(text, tier=tier, in_scope=True)
        # DISPLAY source label: for a Google News aggregator entry, use the real
        # publisher from <source> (e.g. "JD Supra", "India Today", "Fragomen")
        # so the digest never shows the literal 'google-news'. The schema forbids
        # extra item fields (additionalProperties:false), so the readable label
        # rides in source_id itself (the only source field the renderer shows);
        # tiering uses the separate `tier` integer, which is unchanged.
        display_source = source_id
        if aggregator and e["source"]:
            display_source = e["source"]
        summary = title[:600]
        kept.append(make_item(
            source_id=display_source, tier=tier, confidence=confidence,
            headline=title, url=e["link"], published_date=pub,
            category=category, topic=topic, summary=summary,
            importance=importance, affects_facts=affects))
    return len(entries), kept


def fetch_google_news(run_date, max_age_days, drops, verbose):
    total_fetched = 0
    all_kept = []
    seen_ids = set()
    for q in GOOGLE_NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
               % urllib.parse.quote(q))
        try:
            n, kept = fetch_rss_source(
                url, source_id="google-news", tier=3, confidence="low",
                run_date=run_date, max_age_days=max_age_days, drops=drops,
                verbose=verbose, aggregator=True)
        except Exception as exc:  # noqa: BLE001
            log("Google News query %r FAILED: %s" % (q, exc), verbose)
            continue
        total_fetched += n
        # Dedup within Google News across queries (same story surfaces on many).
        for item in kept:
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            all_kept.append(item)
    return total_fetched, all_kept


def _has_immigration_token(text):
    """True if the text hits a real immigration/visa token (not just geography)."""
    t = text or ""
    return any(r.search(t) for r in _COMMUNITY_IMMIGRATION_RE)


def classify_community_relevance(text, strict=False):
    """A community post is relevant if it matches the main EB/H-1B scope OR the
    looser visa-date/consular community vocabulary (the PERMISSIVE gate for
    on-topic subs). For broad/noisy subs (strict=True), the base gate must ALSO
    be backed by a real immigration token, so a pure India/geography/finance post
    is rejected. Returns True/False."""
    t = text or ""
    base = (classify_category(t) is not None
            or any(r.search(t) for r in _COMMUNITY_RELEVANCE_RE))
    if strict:
        return base and _has_immigration_token(t)
    return base


def classify_categories(title, subreddit):
    """Return the taxonomy category id array for a community post (always >= 1).

    Combines (a) the subreddit's DEFAULT categories from the registry with (b)
    per-post keyword classification. 'country' additionally requires a real
    immigration token to co-occur, so pure geography mentions don't match. Falls
    back to ['general'] when nothing else matches, so every kept item lands
    somewhere. Order is stable (taxonomy order), duplicates removed."""
    text = title or ""
    cats = []
    cfg = COMMUNITY_SUBREDDITS.get(subreddit, {})
    for c in cfg.get("cats", []):
        if c in _VALID_CATEGORY_IDS:
            cats.append(c)
    has_imm = _has_immigration_token(text)
    for cat, res in _COMMUNITY_CATEGORY_RE.items():
        if not any(r.search(text) for r in res):
            continue
        if cat == "country" and not has_imm:
            continue  # geography without visa context is not country-specific
        cats.append(cat)
    # De-dup preserving taxonomy order.
    ordered = [t["id"] for t in COMMUNITY_TAXONOMY if t["id"] in set(cats)]
    return ordered or ["general"]


def community_topic(text):
    """Map a community post to a valid news-schema topic enum. Consular /
    appointment / dropbox chatter -> 'processing-times' (closest enum value);
    otherwise defer to the standard classifier."""
    t = text or ""
    if any(r.search(t) for r in _COMMUNITY_PROCESSING_RE):
        return "processing-times"
    return classify_topic(text)


def community_fine_topic(text):
    """Optional, UI-only finest-grained topic label (e.g. 'consular-stamping',
    'priority-dates', 'opt-stem'). Returns None when nothing distinctive matches.
    NOT tied to the news-schema topic enum; drives a small tag in the UI only and
    never affects gating or affects_facts."""
    t = text or ""
    for label, res in _COMMUNITY_FINE_TOPIC_RE:
        if any(r.search(t) for r in res):
            return label
    return None


def _day_of_year(run_date):
    """Day-of-year (1-366) for an ISO run_date, or 0 if unparseable."""
    try:
        return datetime.date.fromisoformat(run_date).timetuple().tm_yday
    except (TypeError, ValueError):
        return 0


def select_subreddits_for_run(run_date, registry=None,
                              budget=COMMUNITY_PER_RUN_BUDGET,
                              rotating_per_run=COMMUNITY_ROTATING_PER_RUN):
    """Return the list of subreddit names to fetch this run under the per-run
    budget. All ENABLED core subs fetch every run; the remaining budget is filled
    with ENABLED rotating subs on a day-of-year round-robin (wrap-around), so all
    rotating subs are covered within a few days. Disabled subs never fetch.

    With only the 4 core subs enabled today, this returns exactly those 4."""
    reg = registry if registry is not None else COMMUNITY_SUBREDDITS
    core = [name for name, cfg in reg.items()
            if cfg.get("enabled", False) and cfg.get("tier") == "core"]
    rotating = [name for name, cfg in reg.items()
                if cfg.get("enabled", False) and cfg.get("tier") == "rotating"]
    selected = core[:budget]
    remaining = max(0, budget - len(selected))
    take = min(rotating_per_run, remaining, len(rotating))
    if rotating and take > 0:
        start = (_day_of_year(run_date) * rotating_per_run) % len(rotating)
        for i in range(take):
            selected.append(rotating[(start + i) % len(rotating)])
    return selected


def fetch_reddit_community(run_date, max_age_days, drops, verbose):
    """Fetch crowd-sourced visa-date reports from Reddit PUBLIC search feeds.

    Legitimacy: see the COMMUNITY SIGNAL comment block near the top of this file.
    In short - these are Reddit's own public, login-free search.rss endpoints,
    read with a courteous User-Agent, at a modest paced cadence, skipping (never
    evading) any 403/429/timeout. Read-only, public posts only.

    Items are emitted TIER 3 / LOW confidence, affects_facts is ALWAYS False, and
    the source_id carries a 'community-reddit-<sub>' prefix so news_digest.py can
    route them into a distinct 'Community reports (unverified)' section with a
    verify-against-official-sources disclaimer. Returns (fetched, kept)."""
    total_fetched = 0
    kept = []
    seen_ids = set()
    # Reddit's search.rss is soft-blocked (HTTP 200 but an EMPTY feed) and
    # www.reddit.com 429-rate-limits almost immediately from datacenter / CI IPs
    # (e.g. GitHub Actions) — which is why this section was ~never populated. The
    # plain per-subreddit feed on old.reddit.com is the most permissive public,
    # login-free endpoint, so we fetch each SELECTED subreddit's newest posts there
    # and filter for visa-date relevance client-side (classify_community_relevance)
    # instead of relying on the search query. Honest UA, paced, one polite backoff
    # on 429, then skip — never hammer, never evade.
    #
    # Which subs are fetched is driven by the COMMUNITY_SUBREDDITS registry under
    # a per-run budget + rotation (see select_subreddits_for_run): core subs every
    # run, rotating subs round-robin by day. With only the 4 core subs enabled,
    # all 4 fetch every run.
    subs = select_subreddits_for_run(run_date)
    for subreddit in subs:
        cfg = COMMUNITY_SUBREDDITS.get(subreddit, {})
        strict = bool(cfg.get("strict", False))
        url = ("https://old.reddit.com/r/%s/new.rss?limit=50"
               % urllib.parse.quote(subreddit, safe=""))
        raw = None
        for attempt in (1, 2):
            try:
                raw = http_get(url, verbose)
                break
            except Exception as exc:  # noqa: BLE001 - skip a blocked/failed sub, never hammer
                if attempt == 1 and "429" in str(exc):
                    log("Reddit r/%s 429 — backing off once" % subreddit, verbose)
                    time.sleep(COMMUNITY_REQUEST_SLEEP_SECONDS * 4)
                    continue
                log("Reddit community r/%s SKIPPED (%s)" % (subreddit, exc), verbose)
                raw = None
                break
        if raw is None:
            time.sleep(COMMUNITY_REQUEST_SLEEP_SECONDS)
            continue
        try:
            entries = parse_feed_entries(raw)
        except Exception as exc:  # noqa: BLE001
            log("Reddit community r/%s parse failed (%s)" % (subreddit, exc), verbose)
            time.sleep(COMMUNITY_REQUEST_SLEEP_SECONDS)
            continue
        total_fetched += len(entries)
        source_id = "community-reddit-%s" % subreddit.lower()
        for e in entries:
            title = e["title"]
            if not title:
                continue
            # Permissive gate for on-topic subs; stricter (real-immigration-token)
            # gate for broad subs flagged strict:True in the registry.
            if not classify_community_relevance(title, strict=strict):
                continue
            pub = parse_date_any(e["pubDate"])
            if not drops.recency_ok(pub, run_date, max_age_days):
                continue
            iid = stable_id(source_id, title, pub)
            if iid in seen_ids:
                continue  # same post surfaced by more than one query
            seen_ids.add(iid)
            # category must be a valid enum; if the post doesn't match the strict
            # EB/H-1B scope it's still employment-visa community chatter, so it
            # defaults to 'cross-cutting'.
            category = classify_category(title) or "cross-cutting"
            item = make_item(
                source_id=source_id, tier=3, confidence="low",
                headline=title, url=e["link"], published_date=pub,
                category=category, topic=community_topic(title),
                summary=title[:600], importance="low",
                affects_facts=False)  # community NEVER sets affects_facts
            # Attach the taxonomy/nesting fields the community.json snapshot
            # carries (subreddit + category array + fine topic). These ride
            # ALONGSIDE the news-schema fields; write_community_json is the
            # authoritative computer of them, but attaching here keeps
            # news_results.json self-describing.
            item["subreddit"] = subreddit
            item["categories"] = classify_categories(title, subreddit)
            item["community_topic"] = community_fine_topic(title)
            kept.append(item)
        time.sleep(COMMUNITY_REQUEST_SLEEP_SECONDS)
    return total_fetched, kept


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Unattended news fetcher for the green card DAILY news layer. "
                    "Fetches ONLY authorized feeds (Federal Register API, live "
                    "RSS, Google News), never scrapes bot-walled gov sites, and "
                    "emits a news_results.json for news_digest.py. Applies three "
                    "quality gates: recency, precise word-boundary scope, and a "
                    "tier-1 affects_facts gate. Personal-learning tool; not legal "
                    "advice.")
    ap.add_argument("--out", default=str(HERE / "news_results.json"),
                    help="Output path for the news-results JSON "
                         "(default: automation/news_results.json).")
    ap.add_argument("--date", default=None,
                    help="Canonical run date YYYY-MM-DD (default: today, UTC).")
    ap.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                    help="Drop any item whose published_date is older than this "
                         "many days before the run date (default %d). Items with "
                         "a missing/unparseable date are always dropped."
                         % DEFAULT_MAX_AGE_DAYS)
    ap.add_argument("--window-days", type=int, default=1,
                    help="Informational window_days written into the output (default 1).")
    ap.add_argument("--verbose", action="store_true",
                    help="Log each fetch to stderr.")
    args = ap.parse_args(argv)

    run_date = args.date or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", run_date):
        sys.stderr.write("ERROR: --date must be YYYY-MM-DD, got %r\n" % run_date)
        return 2
    if args.max_age_days < 1:
        sys.stderr.write("ERROR: --max-age-days must be >= 1, got %r\n"
                         % args.max_age_days)
        return 2

    verbose = args.verbose
    max_age_days = args.max_age_days
    drops = DropStats()
    per_source_fetched = {}
    per_source_kept = {}
    failures = []
    all_items = []

    # --- Federal Register API (tier 1) ---
    try:
        n, kept = fetch_federal_register(run_date, max_age_days, drops, verbose)
        per_source_fetched["federal-register-uscis"] = n
        per_source_kept["federal-register-uscis"] = len(kept)
        all_items.extend(kept)
    except Exception as exc:  # noqa: BLE001
        failures.append("federal-register-uscis: %s" % exc)

    # --- Google News RSS (tier 3, low confidence) ---
    try:
        n, kept = fetch_google_news(run_date, max_age_days, drops, verbose)
        per_source_fetched["google-news"] = n
        per_source_kept["google-news"] = len(kept)
        all_items.extend(kept)
    except Exception as exc:  # noqa: BLE001
        failures.append("google-news: %s" % exc)

    # --- Law-firm / community RSS feeds (only feeds VERIFIED live to a plain
    # stdlib client - see fetch_status "live" in news_sources.json). Dead feeds
    # (AILA /feed, Fragomen /insights/feed, Boundless /feed, DOL releases.xml,
    # Morgan Lewis, NAFSA) are NOT fetched here; their publishers are captured
    # via Google News instead.
    rss_feeds = [
        ("https://www.murthy.com/feed/", "murthy-news", 2, "medium"),
        ("https://www.bal.com/feed/", "bal-alerts", 2, "medium"),
        ("https://www.reddit.com/r/h1b/.rss", "reddit-immigration", 3, "low"),
    ]
    for url, source_id, tier, confidence in rss_feeds:
        try:
            n, kept = fetch_rss_source(url, source_id, tier, confidence,
                                       run_date, max_age_days, drops, verbose)
            per_source_fetched[source_id] = n
            per_source_kept[source_id] = len(kept)
            all_items.extend(kept)
        except Exception as exc:  # noqa: BLE001
            failures.append("%s: %s" % (source_id, exc))

    # --- Reddit COMMUNITY signal (public search feeds; tier 3, low confidence).
    # Kept SEPARATE from the news items below: community items are excluded from
    # near-duplicate clustering so a crowd anecdote is never collapsed into a
    # news representative (or vice versa), preserving the distinct 'Community
    # reports (unverified)' section. See COMMUNITY SIGNAL comment block above.
    community_items = []
    try:
        n, kept = fetch_reddit_community(run_date, max_age_days, drops, verbose)
        per_source_fetched["community-reddit"] = n
        per_source_kept["community-reddit"] = len(kept)
        community_items = kept
    except Exception as exc:  # noqa: BLE001
        failures.append("community-reddit: %s" % exc)

    # Cross-source dedup by stable id (same story from two feeds -> one item).
    # Community ids are included so a community post duplicated across queries is
    # collapsed, but the community/news PARTITION is preserved for clustering.
    deduped = {}
    for it in all_items:
        deduped.setdefault(it["id"], it)
    news_items = list(deduped.values())

    community_deduped = {}
    for it in community_items:
        community_deduped.setdefault(it["id"], it)
    community_items = list(community_deduped.values())

    # NEAR-DUPLICATE STORY CLUSTERING (Fix 2): collapse multiple outlets covering
    # the same story to ONE representative, BEFORE writing the output, so
    # downstream top-N selection (post_slack.py) sees distinct stories. Runs
    # after exact-id dedup, on the NEWS items only. Conservative: see
    # cluster_near_duplicates.
    pre_cluster_count = len(news_items)
    news_items, collapsed_count = cluster_near_duplicates(news_items)
    log("near-duplicate clustering: %d items -> %d (%d collapsed)"
        % (pre_cluster_count, len(news_items), collapsed_count), verbose)

    # Community items ride alongside the clustered news items in the flat output
    # array; the digest renderer separates them by the 'community-reddit-' id.
    items = news_items + community_items

    affects_count = sum(1 for it in items if it["affects_facts"])

    community_count = len(community_items)
    fetch_notes = (
        "Unattended fetch via fetch_feeds.py (authorized feeds only: Federal "
        "Register API + live RSS [Murthy, BAL, Reddit] + Google News + Reddit "
        "public community search feeds). Bot-walled tier-1 pages "
        "(travel.state.gov, egov.uscis.gov, USCIS newsroom RSS) are NOT scraped. "
        "Quality gates: recency (max_age_days=%d), precise word-boundary scope "
        "(EB-1/EB-2/EB-3/H-1B only; community items use a looser visa-date "
        "vocabulary), tier-1 affects_facts gate. Dropped %d stale + %d undated "
        "item(s). Collapsed %d near-duplicate news item(s) covering the same "
        "story. %d item(s) after all filters, cross-source dedup, and near-dup "
        "clustering; %d flagged affects_facts; %d unverified community item(s) "
        "(tier 3, low confidence, never affects_facts)."
        % (max_age_days, drops.stale, drops.no_date, collapsed_count,
           len(items), affects_count, community_count))
    if failures:
        fetch_notes += " Source failures this run: %s." % "; ".join(failures)

    output = {
        "run_date": run_date,
        "window_days": args.window_days,
        "fetched_by": "fetch_feeds.py-unattended",
        "fetch_notes": fetch_notes,
        "items": items,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- stdout summary ----
    print("=" * 70)
    print("fetch_feeds.py - %s (max_age_days=%d)" % (run_date, max_age_days))
    print("=" * 70)
    print("Per-source (fetched -> kept after scope + recency filters):")
    all_source_ids = sorted(set(list(per_source_fetched.keys())
                                + list(per_source_kept.keys())))
    for sid in all_source_ids:
        print("  %-26s %5d -> %d" % (
            sid, per_source_fetched.get(sid, 0), per_source_kept.get(sid, 0)))
    print("")
    print("Dropped by recency gate: %d stale, %d missing/unparseable date"
          % (drops.stale, drops.no_date))
    if failures:
        print("")
        print("FAILED sources (run continued; a dead source never kills the run):")
        for f in failures:
            print("  - %s" % f)
    print("")
    print("Near-duplicate stories collapsed: %d" % collapsed_count)
    print("Total items after cross-source dedup + near-dup clustering: %d"
          % len(items))
    print("Items flagged affects_facts (tier-1 + in-scope + rulebook token): %d"
          % affects_count)
    print("Output: %s" % out_path)
    if not items:
        print("NOTE: 0 items. A quiet/failed-fetch day is a real state - wrote a "
              "valid empty items[] (nothing fabricated).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
