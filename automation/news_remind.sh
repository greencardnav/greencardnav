#!/usr/bin/env bash
#
# news_remind.sh - the HONEST "cron part" of the green card tool DAILY news layer.
#
# A scheduled job (cron / launchd) can only REMIND. It CANNOT do the daily news
# scan unattended, because Step 1 (fetching immigration news) requires Claude's
# WebFetch: USCIS/DOS/DOL/Federal Register are Cloudflare-walled or rate-limited
# to scripts and headless browsers, and even the reliably-fetchable law-firm
# practitioner sites need WebFetch, which a bare cron has no access to. So this
# script does exactly one thing: fire a reminder that the daily news scan is due,
# and point at the runbook. It NEVER fetches, dedups, ranks, or changes anything.
#
# On macOS, if osascript is available it also fires a Notification Center alert.
#
# Usage:
#   bash automation/news_remind.sh
#   bash automation/news_remind.sh --help
#
# Wire it up via cron or launchd - see NEWS_RUNBOOK.md for a sample crontab line
# and a sample launchd plist. Mirrors remind.sh (the monthly facts reminder).

set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
news_remind.sh - fire a daily "immigration-news scan is due" reminder.

Pure reminder. Does NOT fetch, dedup, rank, or modify anything (a cron cannot do
the Cloudflare-walled / WebFetch-only fetch step). Prints a message and, on macOS
with osascript, posts a Notification Center alert.

Scope reminder: EB-1, EB-2, EB-3, and H-1B only. Personal-learning tool, not
legal advice, not official guidance.

Usage:
  bash automation/news_remind.sh
EOF
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNBOOK="$REPO_DIR/automation/NEWS_RUNBOOK.md"
TODAY="$(date +%Y-%m-%d)"

MSG="Green card tool: daily immigration-news scan is due (EB-1/EB-2/EB-3/H-1B). This is a manual/Claude-assisted step (Cloudflare + WebFetch-only fetch). Open the runbook: $RUNBOOK"

echo "[$TODAY] $MSG"
echo ""
echo "Step 1 (fetch) needs a Claude session - see NEWS_RUNBOOK.md for the exact prompt."
echo "This reminder script did NOT fetch or change anything (by design)."

# macOS Notification Center, if available. Non-fatal if it isn't.
if command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"Daily immigration-news scan due. Open NEWS_RUNBOOK.md and run the Step-1 fetch prompt.\" with title \"Green Card Tool news\" sound name \"Glass\"" >/dev/null 2>&1 || true
fi

exit 0
