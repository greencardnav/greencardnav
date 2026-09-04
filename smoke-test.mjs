#!/usr/bin/env node
// smoke-test.mjs — lightweight deployment smoke test for the Green Card Navigator static site.
//
// Purpose: catch embarrassing deployment regressions (an accidentally empty page, a page that
// lost its nav/footer, a Resources page with no links) without a browser or any npm deps.
//
// Usage:
//   node smoke-test.mjs                 # tests http://localhost:8137
//   BASE_URL=https://your.site node smoke-test.mjs   # test a deployed site
//
// Requires Node 18+ (uses global fetch). No external dependencies.

const BASE_URL = (process.env.BASE_URL || "http://localhost:8137").replace(/\/+$/, "");

const PAGES = [
  "index.html",
  "status.html",
  "paths.html",
  "eb1a.html",
  "eb1b.html",
  "eb1c.html",
  "eb2.html",
  "eb3.html",
  "tools.html",
  "faq.html",
  "glossary.html",
  "niw-appeals.html",
"niw-decisions.html",
"niw-guide.html",
  "resources.html",
  "about.html",
  "privacy.html",
  "compare.html",
];

// --- small helpers ---------------------------------------------------------

// Strip <script> and <style> blocks and then all remaining tags, returning the
// visible text. Used to decide whether a region is "blank / whitespace-only".
function visibleText(html) {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&[a-z]+;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// Find the substring that is the closing index of the <div class="topbar"> block
// by matching div nesting depth. Returns the index just after the matching </div>,
// or -1 if not found. This lets us isolate the main content that sits between the
// topbar (banner) and the footer.
function topbarEndIndex(html) {
  const open = html.search(/<div\b[^>]*class=["'][^"']*\btopbar\b[^"']*["'][^>]*>/i);
  if (open === -1) return -1;
  const tagRe = /<(\/?)div\b[^>]*>/gi;
  tagRe.lastIndex = open;
  let depth = 0;
  let m;
  while ((m = tagRe.exec(html)) !== null) {
    if (m[1] === "/") {
      depth--;
      if (depth === 0) return tagRe.lastIndex;
    } else {
      depth++;
    }
  }
  return -1;
}

// Extract the main content region: everything between the end of the topbar and
// the start of the footer. Falls back sensibly if either marker is missing.
function mainContentRegion(html) {
  let start = topbarEndIndex(html);
  if (start === -1) {
    const bodyM = html.search(/<body\b[^>]*>/i);
    start = bodyM === -1 ? 0 : bodyM;
  }
  let end = html.search(/<footer\b/i);
  if (end === -1) end = html.length;
  if (end < start) end = html.length;
  return html.slice(start, end);
}

// Run the checks for a single page's HTML. Returns { checks: [{name, ok, detail}] }.
function checkPage(page, status, html) {
  const checks = [];
  const add = (name, ok, detail = "") => checks.push({ name, ok, detail });

  add("http200", status === 200, `status=${status}`);

  const titleM = html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i);
  const titleText = titleM ? titleM[1].replace(/\s+/g, " ").trim() : "";
  add("nonEmptyTitle", titleText.length > 0, titleText ? `"${titleText}"` : "no <title>");

  const hasHeading = /<h1\b[^>]*>[\s\S]*?<\/h1>/i.test(html) || /<h2\b[^>]*>[\s\S]*?<\/h2>/i.test(html);
  add("hasHeading", hasHeading, "h1 or h2");

  const hasNavStatus = /href=["'][^"']*status\.html["']/i.test(html);
  const hasNavTools = /href=["'][^"']*tools\.html["']/i.test(html);
  add("primaryNav", hasNavStatus && hasNavTools, `status.html=${hasNavStatus} tools.html=${hasNavTools}`);

  const hasFooter = /class=["'][^"']*\bsite-footer\b[^"']*["']/i.test(html) || /href=["'][^"']*privacy\.html["']/i.test(html);
  add("footer", hasFooter, "site-footer or privacy.html link");

  const region = mainContentRegion(html);
  const regionText = visibleText(region);
  add("nonEmptyMain", regionText.length >= 20, `mainTextLen=${regionText.length}`);

  if (page === "resources.html") {
    const externalLinks = html.match(/href=["']https?:\/\/[^"']+["']/gi) || [];
    // Ignore obvious non-resource externals is unnecessary; any external link counts,
    // but note whether a known authoritative gov source is present.
    const hasGov = externalLinks.some((l) => /uscis\.gov|travel\.state\.gov|state\.gov|dol\.gov/i.test(l));
    add(
      "externalResourceLink",
      externalLinks.length > 0,
      `externalLinks=${externalLinks.length}${hasGov ? " (incl. gov source)" : ""}`
    );
  }

  return checks;
}

// --- runner ----------------------------------------------------------------

async function run() {
  console.log(`Smoke test against ${BASE_URL}\n`);
  const rows = [];
  let anyFail = false;

  for (const page of PAGES) {
    const url = `${BASE_URL}/${page}`;
    let checks;
    try {
      const res = await fetch(url, { redirect: "follow" });
      const html = await res.text();
      checks = checkPage(page, res.status, html);
    } catch (err) {
      checks = [{ name: "fetch", ok: false, detail: String(err && err.message ? err.message : err) }];
    }
    const failed = checks.filter((c) => !c.ok);
    const pass = failed.length === 0;
    if (!pass) anyFail = true;
    rows.push({ page, pass, failed, checks });
  }

  // Print per-page table
  const pad = (s, n) => (s + " ".repeat(n)).slice(0, n);
  console.log(pad("PAGE", 18) + pad("RESULT", 8) + "DETAIL");
  console.log("-".repeat(78));
  for (const r of rows) {
    const result = r.pass ? "PASS" : "FAIL";
    const detail = r.pass ? "" : "failed: " + r.failed.map((c) => `${c.name} (${c.detail})`).join("; ");
    console.log(pad(r.page, 18) + pad(result, 8) + detail);
  }
  console.log("-".repeat(78));

  const passCount = rows.filter((r) => r.pass).length;
  console.log(`\n${passCount}/${rows.length} pages passed all checks.`);

  // --- committed data series: gaps and staleness --------------------------------
  // Added because two series had drifted with nothing to catch it. vb_history.json was
  // missing an entire fiscal year (Oct 2022 - Sep 2023) AND lagged the rulebook by a month,
  // and perm_history.json was a quarter behind DOL. Both are hand-maintained, both feed
  // charts, and both failed silently: the charts drew straight through the hole rather than
  // breaking, so the only tell was noticing a year absent from an axis by eye.
  //
  // These run on the committed files, so they need no network and no browser.
  // Two different kinds of finding, deliberately separated:
  //   dataProblems = a DEFECT in what is committed - an interior gap, out-of-order months,
  //     or two files in this repo disagreeing about the latest month. Those are bugs and fail.
  //   dataWarnings = the WORLD moved on and a newer release exists upstream. Fixing that
  //     needs a human to download a file dol.gov will not serve to a script, so failing on it
  //     would leave the suite permanently red - and a permanently red suite is exactly why the
  //     original drift went unnoticed. It reports loudly and passes.
  const dataProblems = [];
  const dataWarnings = [];
  try {
    const fs = await import("node:fs/promises");

    // search-index.json must cover every page this suite tests. It is generated from a
    // HARDCODED page list in build-search-index.mjs, so adding a page to the site does not
    // add it to site search - it just silently stays unfindable. That is exactly what
    // happened to niw-decisions.html and niw-guide.html: both shipped, both linked, neither
    // searchable, and nothing anywhere went red. A DEFECT, not a warning, because unlike the
    // DOL download this is entirely fixable by running one command.
    try {
      const idx = JSON.parse(await fs.readFile("search-index.json", "utf8"));
      const indexed = new Set(
        idx.map((e) => String(e.u || "").split("#")[0]).filter(Boolean)
      );
      // faq.html and glossary.html are indexed as q/g entries keyed to their own anchors, so
      // they appear under their own filenames too; no special case needed.
      // status.html contributes nothing on purpose. It is the questionnaire: its headings are
      // <h2 id="q-..."> interactive prompts, not content sections, and deep-linking a searcher
      // into the middle of a form is worse than not matching. Verified: 0 .hub-section and
      // 0 .hub-title in that file. Named here so the guard stays green for a real reason
      // rather than being loosened.
      const NO_SECTIONS_BY_DESIGN = new Set(["status.html"]);
      const missing = PAGES.filter((p) => !indexed.has(p) && !NO_SECTIONS_BY_DESIGN.has(p));
      if (missing.length) {
        dataProblems.push(
          `search-index.json is missing ${missing.length} page(s): ${missing.join(", ")}` +
          ` - add them to PAGES in build-search-index.mjs, then run: node build-search-index.mjs`
        );
      }
    } catch (e) {
      dataProblems.push(`search-index.json could not be read or parsed: ${e.message}`);
    }

    // vb_history: every series must be gap-free and reach the rulebook's bulletin month.
    const vb = JSON.parse(await fs.readFile("vb_history.json", "utf8"));
    const rb = JSON.parse(await fs.readFile("rulebook.json", "utf8"));
    const bulletinMonth = rb?.bulletin?.as_of;
    const keys = Object.keys(vb);
    let vbLast = null;
    for (const k of keys) {
      const months = vb[k].map((r) => r.month);
      if (!months.length) { dataProblems.push(`vb_history ${k} is empty`); continue; }
      const sorted = [...months].sort();
      if (String(months) !== String(sorted)) dataProblems.push(`vb_history ${k} out of order`);
      // walk the span and require every month
      const [fy, fm] = sorted[0].split("-").map(Number);
      const [ly, lm] = sorted[sorted.length - 1].split("-").map(Number);
      const want = [];
      for (let y = fy, m = fm; y < ly || (y === ly && m <= lm); m === 12 ? (y++, m = 1) : m++) {
        want.push(`${y}-${String(m).padStart(2, "0")}`);
      }
      const have = new Set(months);
      const miss = want.filter((m) => !have.has(m));
      if (miss.length) {
        dataProblems.push(`vb_history ${k} missing ${miss.length} month(s): ${miss.slice(0, 4).join(", ")}${miss.length > 4 ? " ..." : ""}`);
      }
      const last = sorted[sorted.length - 1];
      if (!vbLast || last > vbLast) vbLast = last;
    }
    if (bulletinMonth && vbLast && vbLast < bulletinMonth) {
      dataProblems.push(`vb_history ends ${vbLast} but rulebook shows ${bulletinMonth} — the History charts lag the rest of the site`);
    }

    // perm_history: quarters contiguous, and no more than one quarter behind.
    const perm = JSON.parse(await fs.readFile("perm_history.json", "utf8"));
    const qk = (l) => [Number(l.slice(2, 6)), Number(l.slice(7))];
    const labels = perm.map((r) => r.quarter);
    for (let i = 1; i < labels.length; i++) {
      const [py, pq] = qk(labels[i - 1]);
      const [cy, cq] = qk(labels[i]);
      const expected = pq < 4 ? [py, pq + 1] : [py + 1, 1];
      if (cy !== expected[0] || cq !== expected[1]) {
        dataProblems.push(`perm_history jumps ${labels[i - 1]} -> ${labels[i]}`);
      }
    }
    const now = new Date();
    const fyNow = now.getUTCMonth() >= 9 ? now.getUTCFullYear() + 1 : now.getUTCFullYear();
    const qNow = Math.floor(((now.getUTCMonth() - 9 + 12) % 12) / 3) + 1;
    const prev = qNow > 1 ? [fyNow, qNow - 1] : [fyNow - 1, 4];
    const [ly2, lq2] = qk(labels[labels.length - 1]);
    if (ly2 * 10 + lq2 < prev[0] * 10 + prev[1]) {
      dataWarnings.push(`perm_history ends ${labels[labels.length - 1]} but FY${prev[0]}Q${prev[1]} should be published upstream — run automation/fetch_perm_history.py --check`);
    }
  } catch (e) {
    dataProblems.push(`could not audit the data series: ${e.message}`);
  }

  console.log("");
  if (dataProblems.length) {
    console.log("Committed data series: FAIL");
    for (const p of dataProblems) console.log(`  - ${p}`);
    anyFail = true;
  } else {
    console.log("Committed data series: PASS — no gaps, and the series agree with each other.");
  }
  for (const w of dataWarnings) console.log(`  WARN  ${w}`);

  if (anyFail) {
    console.log("\nFAIL — one or more checks did not pass.");
    process.exit(1);
  } else {
    console.log("\nOK — all pages passed.");
    process.exit(0);
  }
}

run();
