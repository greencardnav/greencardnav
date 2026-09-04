#!/usr/bin/env node
/* =============================================================================
   build-search-index.mjs — generate search-index.json from the built HTML.
   =============================================================================
   Run this after editing any page content:

       node build-search-index.mjs

   It writes search-index.json, which app.js fetches lazily the first time
   someone focuses the search box. Nothing is sent anywhere; the whole index
   ships with the site and the matching happens in the browser.

   Three kinds of entry, each deliberately small so the file stays cacheable:
     q  question   — an FAQ disclosure, keyed to its #q-... anchor
     g  glossary   — a <dt>/<dd> pair, keyed to its group anchor
     p  page       — a section heading on any other page, keyed to its id

   Field names are one letter on purpose. At ~34 questions + 55 glossary terms
   + ~90 section headings, verbose keys would roughly double the payload for no
   benefit to anyone reading it.
   ========================================================================== */

import { readFileSync, writeFileSync, existsSync } from "node:fs";

const OUT = "search-index.json";

// Pages whose section headings are worth indexing. The FAQ and glossary are
// handled separately below because their structure is richer.
const PAGES = [
  ["index.html", "Home"],
  ["status.html", "Check My Status"],
  ["eb1a.html", "EB-1A"],
  ["eb1b.html", "EB-1B"],
  ["eb1c.html", "EB-1C"],
  ["eb2.html", "EB-2"],
  ["eb3.html", "EB-3"],
  ["paths.html", "EB-2 NIW"],
  ["compare.html", "Compare"],
  ["tools.html", "Tools"],
  ["community.html", "Community"],
  ["niw-appeals.html", "NIW Appeals"],
  ["niw-decisions.html", "NIW Decisions"],
  ["niw-guide.html", "NIW Guide"],
  ["resources.html", "Resources"],
  ["about.html", "About"],
  ["privacy.html", "Privacy"],
];

/* ---------- helpers ---------- */

const ENT = {
  "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
  "&nbsp;": " ", "&rarr;": "→", "&middot;": "·", "&ndash;": "–",
  "&mdash;": "—", "&rsquo;": "’", "&lsquo;": "‘", "&#10003;": "",
};
function decode(s) {
  return s.replace(/&[a-z#0-9]+;/gi, (m) => (m in ENT ? ENT[m] : m));
}
// Strip tags, collapse whitespace. Drops <script>/<style> bodies first so their
// contents never leak into a snippet.
function text(html) {
  return decode(
    html
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " ")
  ).replace(/\s+/g, " ").trim();
}
function snip(s, n = 190) {
  s = s.trim();
  if (s.length <= n) return s;
  // Cut on a word boundary so the preview doesn't end mid-token.
  return s.slice(0, s.lastIndexOf(" ", n) > 0 ? s.lastIndexOf(" ", n) : n) + "…";
}
function read(f) {
  if (!existsSync(f)) { console.warn(`  ! skipped (missing): ${f}`); return null; }
  return readFileSync(f, "utf8");
}

const index = [];

/* ---------- 1. FAQ questions ---------- */
{
  const html = read("faq.html");
  if (html) {
    // Walk sections so each question can carry its section title as context.
    const secRe = /<section class="hub-section" id="(mod-[a-z0-9-]+)"[\s\S]*?<h2 class="hub-title"[^>]*>([\s\S]*?)<\/h2>/g;
    const secs = [];
    let m;
    while ((m = secRe.exec(html))) secs.push({ id: m[1], title: text(m[2]), at: m.index });
    secs.forEach((s, i) => { s.end = i + 1 < secs.length ? secs[i + 1].at : html.length; });

    let n = 0;
    for (const s of secs) {
      const body = html.slice(s.at, s.end);
      const qRe = /<details class="collapsible" id="(q-[a-z0-9-]+)">\s*<summary>([\s\S]*?)<\/summary>([\s\S]*?)<\/details>/g;
      let q;
      while ((q = qRe.exec(body))) {
        // The short answer is the most useful preview, so prefer it.
        const short = /<p class="faq-short">([\s\S]*?)<\/p>/.exec(q[3]);
        index.push({
          t: "q",
          l: text(q[2]),
          s: s.title,
          u: `faq.html#${q[1]}`,
          b: snip(text(short ? short[1] : q[3])),
        });
        n++;
      }
    }
    console.log(`  faq.html          ${n} questions`);
  }
}

/* ---------- 2. Glossary terms ---------- */
{
  const html = read("glossary.html");
  if (html) {
    const groups = { "gc-eb": "Green card categories", "gc-family": "Family categories",
                     "gc-work": "Work visas", "gc-process": "Process and bulletin" };
    const gRe = /id="(gc-[a-z-]+)"([\s\S]*?)(?=id="gc-[a-z-]+"|<\/div>\s*<\/div>\s*<\/section>|$)/g;
    let m, n = 0;
    while ((m = gRe.exec(html))) {
      const gid = m[1];
      const pairRe = /<dt[^>]*>([\s\S]*?)<\/dt>\s*<dd[^>]*>([\s\S]*?)<\/dd>/g;
      let p;
      while ((p = pairRe.exec(m[2]))) {
        const label = text(p[1]);
        if (!label) continue;
        index.push({
          t: "g",
          l: label,
          s: groups[gid] || "Glossary",
          u: `glossary.html#${gid}`,
          b: snip(text(p[2]).replace(/\s*(8 CFR|8 U\.S\.C\.|20 CFR|22 CFR|USCIS Policy Manual|travel\.state\.gov)[^.]*$/, "")),
        });
        n++;
      }
    }
    console.log(`  glossary.html     ${n} terms`);
  }
}

/* ---------- 3. Section headings on every other page ---------- */
for (const [file, label] of PAGES) {
  const html = read(file);
  if (!html) continue;
  // Slice the page into sections FIRST, then read each slice on its own.
  // Matching a section tag and then scanning forward for an <h2> lets a section
  // that has no heading swallow the next section's heading, pairing the wrong id
  // with the wrong title. Bounding each section to its own span prevents that.
  //
  // Attribute order is not consistent across pages (some write id before class),
  // so match the open tag loosely and pull the id out of it.
  const opens = [];
  const openRe = /<section ([^>]*\bhub-section\b[^>]*)>/g;
  let o;
  while ((o = openRe.exec(html))) opens.push({ attrs: o[1], at: o.index, from: openRe.lastIndex });

  let n = 0;
  for (let k = 0; k < opens.length; k++) {
    const cur = opens[k];
    const stop = k + 1 < opens.length ? opens[k + 1].at : html.length;
    const slice = html.slice(cur.from, stop);

    const idm = /\bid="([a-z0-9-]+)"/.exec(cur.attrs);
    if (!idm) continue;                       // no id means nothing to link to

    // h1 as well as h2. On a page whose FIRST section carries the page title, that
    // heading is an <h1> (one <h1> per page), so an h2-only match silently skipped the
    // section a searcher is most likely to want. niw-decisions.html lost its
    // "Browse the appeal decisions" entry exactly this way.
    const h2 = /<h([12]) class="hub-title"[^>]*>([\s\S]*?)<\/h\1>/.exec(slice);
    if (!h2) continue;                        // no heading of its own, skip it
    const title = text(h2[2]);   // [1] is the heading level
    if (!title) continue;

    const sub = /<p class="hub-sub">([\s\S]*?)<\/p>/.exec(slice);
    index.push({
      t: "p", l: title, s: label, u: `${file}#${idm[1]}`,
      b: snip(text(sub ? sub[1] : ""), 150),
    });
    n++;
  }
  console.log(`  ${file.padEnd(17)} ${n} sections`);
}

/* ---------- write ---------- */
// Drop exact duplicates by URL + label, which can happen where a page repeats a
// heading, and keep the order stable so the file diffs cleanly between builds.
const seen = new Set();
const deduped = index.filter((e) => {
  const k = e.u + "|" + e.l;
  if (seen.has(k)) return false;
  seen.add(k);
  return true;
});

writeFileSync(OUT, JSON.stringify(deduped));
const kb = (Buffer.byteLength(JSON.stringify(deduped)) / 1024).toFixed(1);
console.log(`\n  wrote ${OUT}: ${deduped.length} entries, ${kb} KB`);
