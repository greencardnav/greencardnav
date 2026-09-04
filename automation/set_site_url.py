#!/usr/bin/env python3
"""Swap the site's canonical host across every file that hardcodes it.

WHY THIS EXISTS
    Canonical tags, OG/Twitter image URLs, the sitemap and robots.txt all need an
    ABSOLUTE url, and this repo has no build step, so the host is hardcoded in 18
    files. Doing that by hand at cutover is how you end up with three files still
    pointing at the old host and a search engine quietly de-ranking you. This makes
    the swap one reversible command with a verification pass.

USAGE
    python3 automation/set_site_url.py --check                  # what host is live now
    python3 automation/set_site_url.py --to greencardnav.com     # dry run (default)
    python3 automation/set_site_url.py --to greencardnav.com --commit
    python3 automation/set_site_url.py --to main.d20qtw2pnzotwx.amplifyapp.com --commit   # rollback

ORDER OF OPERATIONS AT CUTOVER - THIS MATTERS
    Do NOT push the swap before the new domain actually serves the site. A canonical
    tag pointing at a host that does not resolve is worse than one pointing at the old
    host: crawlers treat it as the authoritative URL and cannot fetch it.

    1. Register the domain and add it in Amplify (Hosting -> Custom domains). Wait for
       the ACM certificate to validate and the domain to serve the site over https.
    2. Confirm the new host returns 200 and the right content.
    3. Run this with --commit, then run the test suites.
    4. Commit and push. Amplify redeploys with the new canonicals.
    5. Re-run --check to confirm zero stragglers, and refetch the live sitemap.

    Keep the amplifyapp.com host working afterwards; Amplify serves both. It stops
    being the canonical, which is the point.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Only files that legitimately carry an absolute site URL. Deliberately excludes the
# aao-indexer (its own tool), venvs, and the PDF/data caches.
EXTS = {".html", ".js", ".json", ".xml", ".txt", ".yml", ".yaml", ".md", ".css"}
SKIP_DIRS = {".git", "node_modules", ".venv", "cache", "out", "aao-indexer",
             "niw results", "__pycache__", "freshness_proposals", "news_digests"}

# Every host this site has ever been served from, so --check can spot a straggler no
# matter which direction the last swap went.
KNOWN_HOSTS = [
    "main.d20qtw2pnzotwx.amplifyapp.com",
    "www.greencardnav.com",
    "greencardnav.com",
    "gcnav.org",
    "gcnav.net",
]

HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def walk_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in EXTS:
                yield os.path.join(root, f)


def scan():
    """Return {host: {relpath: count}} for every known host present."""
    found = {h: {} for h in KNOWN_HOSTS}
    for p in walk_files():
        try:
            s = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for h in KNOWN_HOSTS:
            n = len(re.findall(r"(?<![A-Za-z0-9.-])" + re.escape(h), s))
            if n:
                found[h][os.path.relpath(p, REPO)] = n
    return {h: v for h, v in found.items() if v}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", help="the new canonical host, e.g. greencardnav.com")
    ap.add_argument("--from", dest="frm",
                    help="the host to replace (default: auto-detect the only one present)")
    ap.add_argument("--commit", action="store_true", help="actually write (default is a dry run)")
    ap.add_argument("--check", action="store_true", help="report which hosts appear where, then exit")
    args = ap.parse_args()

    found = scan()

    if args.check or not args.to:
        if not found:
            print("No known site host appears in any file. Nothing to report.")
            return 0
        for h, files in found.items():
            print("%s  -> %d occurrence(s) in %d file(s)" % (h, sum(files.values()), len(files)))
            for p, n in sorted(files.items(), key=lambda kv: -kv[1]):
                print("    %-34s %3d" % (p, n))
        if len(found) > 1:
            print("\nWARNING: more than one host is present. The site is in a mixed state; "
                  "run with --to <host> --commit to make it consistent.", file=sys.stderr)
            return 1
        if not args.to:
            print("\nPass --to <host> to swap.")
        return 0

    new = args.to.strip().lower().rstrip("/")
    for pre in ("https://", "http://"):
        if new.startswith(pre):
            new = new[len(pre):]
    if not HOST_RE.match(new):
        print("that does not look like a bare hostname: %r" % args.to, file=sys.stderr)
        return 2

    if args.frm:
        old = args.frm.strip().lower()
    else:
        others = [h for h in found if h != new]
        if len(others) != 1:
            print("cannot auto-detect the host to replace (found: %s). Pass --from."
                  % (", ".join(found) or "none"), file=sys.stderr)
            return 2
        old = others[0]

    if old == new:
        print("old and new host are the same; nothing to do.")
        return 0

    print("%s  ->  %s%s\n" % (old, new, "" if args.commit else "   (DRY RUN)"))
    total = 0
    touched = 0
    for p in walk_files():
        try:
            s = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        pat = re.compile(r"(?<![A-Za-z0-9.-])" + re.escape(old))
        n = len(pat.findall(s))
        if not n:
            continue
        total += n
        touched += 1
        print("  %-34s %3d" % (os.path.relpath(p, REPO), n))
        if args.commit:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(pat.sub(new, s))

    print("\n%d occurrence(s) in %d file(s)" % (total, touched))
    if not args.commit:
        print("Dry run: nothing written. Re-run with --commit.")
        return 0

    # Verify the swap landed completely and left the files parseable.
    after = scan()
    if old in after:
        print("\nFAILED: %d occurrence(s) of %s remain in %s"
              % (sum(after[old].values()), old, ", ".join(after[old])), file=sys.stderr)
        return 1
    print("verified: zero occurrences of %s remain" % old)
    print("verified: %d occurrence(s) of %s now present"
          % (sum(after.get(new, {}).values()), new))

    import xml.etree.ElementTree as ET
    for f in ("sitemap.xml",):
        fp = os.path.join(REPO, f)
        if os.path.exists(fp):
            try:
                ET.parse(fp)
                print("verified: %s still parses as XML" % f)
            except ET.ParseError as e:
                print("FAILED: %s no longer parses: %s" % (f, e), file=sys.stderr)
                return 1

    print("\nNext: run the test suites, then commit. Do not push until %s serves the "
          "site over https (see the module docstring)." % new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
