#!/usr/bin/env bash
#
# deploy.sh - deploy step for the green card questionnaire tool.
#
# WHERE THIS SITS IN THE WORKFLOW
# -------------------------------
# This is the final step of the monthly freshness workflow, run AFTER
# apply_proposal.py --commit has updated index.html's inlined rulebook.
# It validates that index.html is a self-contained single file and that its
# inlined JSON parses, then guides the (manual) Netlify anon-drop or, if the
# Netlify CLI is present, offers the netlify deploy command form.
#
# HONESTY NOTE: Netlify "anonymous drop" is a manual drag-and-drop in the
# browser. This script CANNOT do that drag for you. It validates and instructs.
# A internal-hosting path is documented separately in the local-only
# DEPLOYMENT.md, which is gitignored and must stay that way.
#
# Usage:
#   bash automation/deploy.sh            # validate + print instructions
#   bash automation/deploy.sh --help
#
# No arguments required. Pure bash + coreutils + python3 (for JSON validation).

set -euo pipefail

usage() {
  cat <<'EOF'
deploy.sh - validate and deploy index.html for the green card tool.

What it does:
  1. Confirms index.html is self-contained (no external CSS/JS/font/image src/href
     beyond citation links to gov / law-firm pages).
  2. Validates the inlined rulebook JSON parses.
  3. Prints the exact manual Netlify anon-drop steps, OR - if the `netlify` CLI
     is installed - offers the `netlify deploy` command form.
  4. Prints a pointer to the local-only DEPLOYMENT.md for the other option.

Usage:
  bash automation/deploy.sh
  bash automation/deploy.sh --help
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INDEX="$REPO_DIR/index.html"

echo "======================================================================"
echo "green card tool - deploy.sh"
echo "index.html: $INDEX"
echo "======================================================================"

if [[ ! -f "$INDEX" ]]; then
  echo "ERROR: index.html not found at $INDEX" >&2
  exit 1
fi

# ---- 1. Self-contained check --------------------------------------------------
# Flag external RESOURCE references (things the browser would fetch to render):
# src= or href= pointing at http(s) CSS/JS/font/image assets. Citation links
# (<a href="https://...">) to gov/law-firm pages are EXPECTED and allowed - we
# only care about asset references (stylesheet rel, script src, img src, font).
echo ""
echo "[1/3] Checking index.html is self-contained (no external asset references)..."

# Stylesheet links: <link rel="stylesheet" href="http...">
STYLE_HITS="$(grep -Eio '<link[^>]+rel=["'"'"']?stylesheet[^>]+href=["'"'"']?https?://[^"'"'"' >]+' "$INDEX" || true)"
# External script src
SCRIPT_HITS="$(grep -Eio '<script[^>]+src=["'"'"']?https?://[^"'"'"' >]+' "$INDEX" || true)"
# External img src
IMG_HITS="$(grep -Eio '<img[^>]+src=["'"'"']?https?://[^"'"'"' >]+' "$INDEX" || true)"
# Font / @import in CSS or preconnect to font hosts
FONT_HITS="$(grep -Eio '(@import[^;]+https?://|href=["'"'"']?https?://[^"'"'"' >]*fonts\.[^"'"'"' >]+)' "$INDEX" || true)"

EXTERNAL_ASSET_FOUND=0
for label in "stylesheet:$STYLE_HITS" "script-src:$SCRIPT_HITS" "img-src:$IMG_HITS" "font:$FONT_HITS"; do
  name="${label%%:*}"
  body="${label#*:}"
  if [[ -n "$body" ]]; then
    echo "  WARNING: external $name reference(s) found:"
    echo "$body" | sed 's/^/    /'
    EXTERNAL_ASSET_FOUND=1
  fi
done

if [[ "$EXTERNAL_ASSET_FOUND" -eq 0 ]]; then
  echo "  OK: no external asset references. index.html is self-contained."
  echo "  (Citation <a href> links to gov / law-firm pages are expected and were not flagged.)"
else
  echo "  ACTION: inline or remove the external asset references above before deploying."
  echo "  A self-contained single file is what makes the Netlify anon-drop work."
fi

# ---- 2. Inlined JSON validation ----------------------------------------------
echo ""
echo "[2/3] Validating the inlined rulebook JSON parses..."
if python3 - "$INDEX" <<'PY'
import sys, re, json
text = open(sys.argv[1], encoding="utf-8").read()
OPEN = '<script type="application/json" id="rulebook">'
CLOSE = "</script>"
i = text.find(OPEN)
if i == -1:
    print("  ERROR: could not find the rulebook <script> block."); sys.exit(1)
i += len(OPEN)
j = text.find(CLOSE, i)
if j == -1:
    print("  ERROR: could not find </script> after the rulebook block."); sys.exit(1)
payload = text[i:j].strip()
try:
    obj = json.loads(payload)
except json.JSONDecodeError as e:
    print("  ERROR: inlined rulebook JSON did not parse: %s" % e); sys.exit(1)
print("  OK: inlined rulebook JSON parses. meta.version=%s last_verified=%s"
      % (obj.get("meta", {}).get("version"), obj.get("meta", {}).get("last_verified")))
PY
then
  :
else
  echo "  ACTION: re-run apply_proposal.py --commit (it re-syncs + validates the inlined JSON)." >&2
  exit 1
fi

# ---- 3. Deploy instructions --------------------------------------------------
echo ""
echo "[3/3] Deploy options"
echo ""
if command -v netlify >/dev/null 2>&1; then
  echo "  Netlify CLI detected ($(command -v netlify))."
  echo "  You can deploy non-interactively from the repo directory:"
  echo ""
  echo "    cd \"$REPO_DIR\""
  echo "    # First time, link to the existing site:  netlify link"
  echo "    netlify deploy --dir \"$REPO_DIR\" --prod"
  echo ""
  echo "  (--dir points at the folder containing index.html. Drop other files"
  echo "   from the dir if you only want to publish index.html - or use a"
  echo "   dedicated publish subfolder.)"
else
  echo "  Netlify CLI NOT installed. Deploy is a MANUAL anonymous drag-and-drop:"
  echo ""
  echo "    1. Open https://app.netlify.com/drop  (or your existing site's"
  echo "       'Deploys' tab -> drag-and-drop zone)."
  echo "    2. Drag index.html (this file) onto the drop zone:"
  echo "         $INDEX"
  echo "    3. Netlify publishes it in a few seconds and gives you the URL."
  echo ""
  echo "  This drag step is manual - no script can perform the browser drop."
  echo "  (To automate later: install the Netlify CLI and re-run this script;"
  echo "   it will print the netlify deploy command form instead.)"
fi

echo ""
echo "----------------------------------------------------------------------"
echo "An alternative hosting path is documented in DEPLOYMENT.md, which is"
echo "gitignored and stays local. Details are deliberately not printed here,"
echo "because this script is committed to a public repository."
echo "----------------------------------------------------------------------"
echo ""
echo "deploy.sh done."
