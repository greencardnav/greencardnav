#!/usr/bin/env bash
#
# remind.sh - the HONEST "cron part" of the green card tool freshness workflow.
#
# A scheduled job (cron / launchd) can only REMIND. It CANNOT do the monthly
# refresh unattended, because Step 1 (fetching the Visa Bulletin) requires
# Claude's WebFetch against tier-2 aggregators - travel.state.gov and uscis.gov
# are Cloudflare-walled and 403 both scripts and headless browsers. So this
# script does exactly one thing: fire a reminder that the refresh is due, and
# point at the runbook. It NEVER fetches, diffs, or changes any data.
#
# On macOS, if osascript is available it also fires a Notification Center alert.
#
# Usage:
#   bash automation/remind.sh
#   bash automation/remind.sh --help
#
# Wire it up via cron or launchd - see RUNBOOK.md for a sample crontab line and
# a sample launchd plist.

set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
remind.sh - fire a monthly "visa bulletin refresh is due" reminder.

Pure reminder. Does NOT fetch, diff, or modify anything (a cron cannot do the
Cloudflare-walled fetch step). Prints a message and, on macOS with osascript,
posts a Notification Center alert.

Usage:
  bash automation/remind.sh
EOF
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNBOOK="$REPO_DIR/automation/RUNBOOK.md"
TODAY="$(date +%Y-%m-%d)"

MSG="Green card tool: monthly Visa Bulletin freshness refresh is due. This is a manual/Claude-assisted step (Cloudflare blocks unattended fetch). Open the runbook: $RUNBOOK"

echo "[$TODAY] $MSG"
echo ""
echo "Step 1 (fetch) needs a Claude session - see RUNBOOK.md for the exact prompt."
echo "This reminder script did NOT fetch or change anything (by design)."

# macOS Notification Center, if available. Non-fatal if it isn't.
if command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"Visa Bulletin refresh due. Open RUNBOOK.md and run the Step-1 fetch prompt.\" with title \"Green Card Tool freshness\" sound name \"Glass\"" >/dev/null 2>&1 || true
fi

exit 0
