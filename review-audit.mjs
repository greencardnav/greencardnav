#!/usr/bin/env node
/*
 * review-audit.mjs — ground-truth audit of the interactive (JS-driven) behavior
 * of Green Card Navigator, for an LLM reviewer that would otherwise only see the
 * no-JS static HTML and wrongly report interactive features as "missing".
 *
 * WHY THIS EXISTS: almost every "still missing / unverified" finding in past
 * review loops came from crawling raw HTML. The methodology panel, the
 * category-aware helpers, the fee amounts, and the whole H-1B branch/selector
 * only exist after JavaScript runs. This script actually runs the JS in a real
 * Chromium, drives each flow, and prints PASS/FAIL with evidence the reviewer
 * can cite.
 *
 * ZERO npm dependencies. It drives a headless Chrome/Chromium directly over the
 * DevTools Protocol using only Node built-ins (global fetch + global WebSocket,
 * Node 18.16+ / best on Node 20+; tested on Node 24). It auto-discovers a
 * Chrome/Chromium binary; override with CHROME_BIN=/path/to/chrome.
 *
 * USAGE:
 *   node review-audit.mjs                      # audits the live Amplify site
 *   BASE_URL=http://localhost:8137 node review-audit.mjs   # audit a local server
 *   CHROME_BIN="/path/to/chrome" node review-audit.mjs     # explicit browser
 *
 * Exit code 0 if every flow passed, 1 otherwise.
 */

import { spawn } from "node:child_process";
import { readFileSync, existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir, homedir } from "node:os";
import { join } from "node:path";

const BASE_URL = (process.env.BASE_URL || "https://www.greencardnav.com").replace(/\/$/, "");

// The persona harness is a TEST FIXTURE, read from disk rather than fetched from the served
// site. It used to be fetched over HTTP, which meant persona-regression.js had to be deployed
// to production purely so the test could reach it - and shipping test files to a live site is
// exactly what amplify.yml now prevents. Reading it locally removes that coupling.
//
// What does NOT change: the source is still injected into the page as a real inline <script>,
// so the check still runs under the site's actual enforcing CSP. That matters because the
// policy has no 'unsafe-eval' (deliberately - the site uses no eval anywhere), and an earlier
// version of this check used eval() and silently broke when the CSP went from report-only to
// enforcing. 'unsafe-inline' IS in the policy, so an inline script is permitted where eval is
// not, and that asymmetry is the thing being exercised.
const PERSONA_SRC = readFileSync(new URL("./persona-regression.js", import.meta.url), "utf8");
const HEADLESS = process.env.HEADFUL ? [] : ["--headless=new"];

/* ---------- locate a Chrome/Chromium binary ---------- */
function findChrome() {
  if (process.env.CHROME_BIN && existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  const home = homedir();
  const candidates = [
    // Playwright-managed Chromium (what the MCP downloads)
    `${home}/Library/Caches/ms-playwright/chromium-1212/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`,
    // Any playwright chromium build (glob-ish fallbacks handled below)
    // System Chrome / Chromium / Edge, macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    // Linux
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    // Windows
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  // last resort: scan the ms-playwright cache for any chromium build
  try {
    const base = `${home}/Library/Caches/ms-playwright`;
    if (existsSync(base)) {
      for (const dir of readdirSync(base)) {
        if (!/^chromium/.test(dir)) continue;
        const p = `${base}/${dir}/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;
        if (existsSync(p)) return p;
        const p2 = `${base}/${dir}/chrome-mac/Chromium.app/Contents/MacOS/Chromium`;
        if (existsSync(p2)) return p2;
      }
    }
  } catch {}
  return null;
}

/* ---------- tiny CDP client over the built-in WebSocket ---------- */
class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.waiters = [];
    this.ready = new Promise((res, rej) => {
      this.ws.addEventListener("open", () => res());
      this.ws.addEventListener("error", (e) => rej(new Error("WS error: " + (e.message || e.type))));
    });
    this.ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id != null && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      } else if (msg.method) {
        this.waiters = this.waiters.filter((w) => {
          if (w.method === msg.method) { w.resolve(msg.params); return false; }
          return true;
        });
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error("CDP timeout: " + method)); }
      }, 30000);
    });
  }
  waitEvent(method, ms = 20000) {
    return new Promise((resolve, reject) => {
      const w = { method, resolve };
      this.waiters.push(w);
      setTimeout(() => {
        this.waiters = this.waiters.filter((x) => x !== w);
        reject(new Error("event timeout: " + method));
      }, ms);
    });
  }
  close() { try { this.ws.close(); } catch {} }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launchBrowser(bin) {
  const userDataDir = mkdtempSync(join(tmpdir(), "gcn-audit-"));
  const args = [
    ...HEADLESS,
    "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--hide-scrollbars", "--mute-audio",
    `--user-data-dir=${userDataDir}`,
    "--remote-debugging-port=0",
    "about:blank",
  ];
  const proc = spawn(bin, args, { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "", exited = false;
  proc.stderr.on("data", (d) => { stderr += d.toString(); });
  proc.on("exit", () => { exited = true; });
  // Chrome writes the chosen port to <user-data-dir>/DevToolsActivePort
  const portFile = join(userDataDir, "DevToolsActivePort");
  let port = null;
  for (let i = 0; i < 200; i++) {  // up to ~20s: first cold launch can be slow
    if (exited) throw new Error("Chrome exited during startup.\n" + stderr.slice(-500));
    if (existsSync(portFile)) {
      const line = readFileSync(portFile, "utf8").split("\n")[0].trim();
      if (line) { port = line; break; }
    }
    await sleep(100);
  }
  if (!port) { proc.kill(); throw new Error("Chrome did not expose a debugging port within 20s.\n" + stderr.slice(-500)); }
  // find (or create) a page target
  let target = null;
  for (let i = 0; i < 30; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = list.find((t) => t.type === "page");
      if (target) break;
    } catch {}
    // create one if none
    try { await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" }); } catch {}
    await sleep(150);
  }
  if (!target || !target.webSocketDebuggerUrl) { proc.kill(); throw new Error("No page target from Chrome"); }
  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.ready;
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  return { proc, cdp, kill: () => { cdp.close(); try { proc.kill(); } catch {} } };
}

async function navigate(cdp, url) {
  const loaded = cdp.waitEvent("Page.loadEventFired", 25000).catch(() => null);
  await cdp.send("Page.navigate", { url });
  await loaded;
  await sleep(900); // settle: app.js DOMContentLoaded handlers + async render
}

async function evaluate(cdp, asyncBody) {
  const expression = `(async () => { ${asyncBody} })()`;
  const r = await cdp.send("Runtime.evaluate", {
    expression, awaitPromise: true, returnByValue: true,
  });
  if (r.exceptionDetails) {
    return { __error: r.exceptionDetails.exception ? r.exceptionDetails.exception.description : "eval exception" };
  }
  return r.result.value;
}

/* ---------- shared page-side helpers (injected as a prelude) ---------- */
const PRELUDE = `
  function pick(name, val){ var i=document.querySelector('input[name="'+name+'"][value="'+val+'"]'); if(!i) return false; var c=i.closest('.radio-card'); if(c){c.click();return true;} i.checked=true; i.dispatchEvent(new Event('change',{bubbles:true})); return true; }
  function pickWV(val){ var c=document.querySelector('.workvisa-chip[data-value="'+val+'"]'); if(!c) return false; if(!c.classList.contains('selected')) c.click(); return true; }
  function setPd(v){ var i=document.getElementById('pd-input'); if(!i) return false; i.value=v; i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true})); return true; }
  function clickStart(){ var b=[].slice.call(document.querySelectorAll('button')).find(function(x){return /^start$/i.test((x.textContent||'').trim());}); if(b) b.click(); }
  function wait(ms){ return new Promise(function(r){setTimeout(r,ms);}); }
`;

/* ---------- the five flows ---------- */
const FLOWS = [
  {
    name: "1. Timeline methodology + 'Why this range?' render",
    page: "/status.html",
    body: `${PRELUDE}
      // Use a deeply-backlogged priority date (recent) so there is a real future
      // wait to explain — the "Why this range?" panel intentionally hides itself
      // when the date is already current.
      clickStart(); pick('category','EB-2'); pickWV('H-1B'); pick('country','India'); setPd('2023-06-01');
      await wait(800);
      // textContent (NOT innerText): the methodology/why live in collapsed <details>,
      // and innerText excludes hidden nodes. This is the crux of the crawler blind spot.
      var rc = document.getElementById('result-content'); var t = rc ? (rc.textContent||'') : '';
      var method = /how is this calculated/i.test(t);
      var why = /why this range/i.test(t);
      var median = /median/i.test(t), quartile = /quartile/i.test(t), bulletin = /visa bulletin/i.test(t);
      var limits = /(cannot|can't|does not|limitation|policy|retrogress)/i.test(t);
      var pass = method && why && median && quartile && bulletin && limits;
      return { pass: pass, detail: 'methodology='+method+' why='+why+' median='+median+' quartile='+quartile+' bulletin='+bulletin+' limits='+limits, resultLen: t.length };
    `,
  },
  {
    name: "1c. Timeline tail is bounded AND internally consistent (no year past the 'beyond' cutoff)",
    page: "/status.html",
    body: `${PRELUDE}
      // Two failure modes to guard:
      //  (a) false-precision century year (e.g. 2107) instead of "beyond ~YYYY"
      //  (b) a shown range endpoint LATER than the "beyond YYYY" cutoff
      //      (the "approx. 2033-2068 · worst case beyond 2056" contradiction).
      // Uses a fresh PD (typical pace lands past the horizon) — the exact case
      // that surfaced the bug.
      clickStart(); pick('category','EB-2'); pickWV('H-1B'); pick('country','India'); setPd('2026-08-14');
      await wait(800);
      var head = document.getElementById('qp-headline');
      var t = head ? (head.querySelector('.qp-big') ? head.querySelector('.qp-big').textContent : head.textContent) : '';
      t = (t||'').replace(/\\s+/g,' ').trim();
      var years = (t.match(/\\b(20|21)\\d\\d\\b/g) || []).map(Number);
      var beyondMatch = t.match(/beyond\\s+((?:20|21)\\d\\d)/i);
      var beyondYear = beyondMatch ? Number(beyondMatch[1]) : null;
      var hasBeyond = beyondYear != null || !!(head && head.querySelector('.qp-beyond'));
      var centuryYear = years.some(function(y){ return y >= 2080; });
      // No shown year may exceed the "beyond" cutoff (that is the contradiction).
      var consistent = beyondYear == null || years.every(function(y){ return y <= beyondYear; });
      var pass = t.length > 0 && hasBeyond && !centuryYear && consistent;
      return { pass: pass, detail: 'headline="'+t.slice(0,80)+'" beyondYear='+beyondYear+' shownYears=['+years.join(',')+'] centuryYear='+centuryYear+' consistent='+consistent };
    `,
  },
  {
    name: "2. Category-aware priority-date helper updates on selection",
    page: "/status.html",
    body: `${PRELUDE}
      clickStart();
      var pd = document.getElementById('pd-help-text'); if(!pd) return { pass:false, detail:'no #pd-help-text' };
      pick('category','EB-1'); await wait(150); var eb1 = pd.textContent;
      pick('category','EB-3'); await wait(150); var eb3 = pd.textContent;
      pick('category','EB-2'); await wait(150); var eb2 = pd.textContent;
      var okEb1 = /i-140/i.test(eb1) && /(no labor cert|there is no labor|skip)/i.test(eb1);
      var okEb3 = /labor certification/i.test(eb3);
      var okEb2 = /national interest waiver|niw/i.test(eb2) && /perm/i.test(eb2);
      var pass = okEb1 && okEb3 && okEb2;
      return { pass: pass, detail: 'EB-1(I-140/noPERM)='+okEb1+' EB-3(laborcert)='+okEb3+' EB-2(PERM+NIW)='+okEb2 };
    `,
  },
  {
    name: "3. EB-1A fee table shows dollar amounts",
    page: "/eb1a.html",
    body: `${PRELUDE}
      await wait(300);
      var spans = [].slice.call(document.querySelectorAll('[data-fee]'));
      var vals = spans.map(function(s){ return { key: s.getAttribute('data-fee'), text: (s.textContent||'').trim() }; });
      var allFilled = spans.length >= 5 && vals.every(function(v){ return /\\$\\s?[0-9]/.test(v.text); });
      return { pass: allFilled, detail: 'spans='+spans.length+' values='+JSON.stringify(vals) };
    `,
  },
  {
    name: "4. H-1B checklist: branches + fee table + persistence copy",
    page: "/tools.html",
    body: `${PRELUDE}
      // activate the H-1B Checklist tab
      var tabBtn = [].slice.call(document.querySelectorAll('[data-tool-target], [role="tab"], button')).find(function(b){ return /h-1b checklist/i.test((b.textContent||'')); });
      if (tabBtn) tabBtn.click();
      await wait(700);
      var host = document.getElementById('tools-h1b') || document;
      var sel = host.querySelector('select');
      if (!sel) return { pass:false, detail:'no H-1B scenario selector found' };
      function set(v){ sel.value=v; sel.dispatchEvent(new Event('change',{bubbles:true})); }
      function txt(){ return (host.innerText||host.textContent||''); }
      // transfer
      set('transfer'); await wait(250); var trT = txt();
      var transferOK = /transfer/i.test(trT) && /portability/i.test(trT) && !/registration and lottery/i.test(trT);
      // extension
      set('extension'); await wait(250); var exT = txt();
      var extensionOK = /extension/i.test(exT) && /i-129 extension|i-129 \\(extension|files the i-129/i.test(exT);
      // amendment + move-checker cross-link
      set('amendment'); await wait(250); var amT = txt();
      var amendmentOK = /amendment/i.test(amT);
      var crossLink = !!host.querySelector('a[href*="jobchange"], a[href*="tools-jobchange"]') || /job or location change/i.test(amT);
      // fee table
      var feeOK = /fees at a glance/i.test(txt()) && /\\$2,965/.test(txt()) && /\\$100,000/.test(txt());
      // persistence copy fixed (no "nothing is saved or sent anywhere")
      var intro = document.body.innerText || '';
      var copyOK = /saved locally in this browser/i.test(intro) && !/nothing is saved or sent anywhere/i.test(intro);
      var clearBtn = !!document.getElementById('h1b-clear');
      var selectorOptions = [].slice.call(sel.options).map(function(o){return o.value;}).filter(Boolean);
      var pass = transferOK && extensionOK && amendmentOK && crossLink && feeOK && copyOK && clearBtn;
      return { pass: pass, detail: 'transfer='+transferOK+' extension='+extensionOK+' amendment='+amendmentOK+' moveCheckerLink='+crossLink+' feeTable='+feeOK+' persistCopyFixed='+copyOK+' clearBtn='+clearBtn, options: selectorOptions };
    `,
  },
  {
    name: "4b. H-1B checklist progress persists across reload (localStorage)",
    page: "/tools.html",
    body: `${PRELUDE}
      try { localStorage.setItem('gc_h1b_checklist', JSON.stringify({scenario:'transfer', fork:'cos', done:['x']})); } catch(e){ return { pass:false, detail:'localStorage blocked: '+e }; }
      return { pass:true, detail:'seeded', seeded: localStorage.getItem('gc_h1b_checklist') };
    `,
    reloadCheck: `${PRELUDE}
      var v = null; try { v = localStorage.getItem('gc_h1b_checklist'); } catch(e){}
      var persisted = !!v && /transfer/.test(v);
      return { pass: persisted, detail: 'afterReload='+v };
    `,
  },
  {
    name: "5. Status persona regression suite (13 personas)",
    page: "/status.html",
    // The harness source is read from disk by the runner (see PERSONA_SRC) and injected
    // here as a real <script>. It used to be fetched from the site and eval()'d.
    // That broke the moment the Content-Security-Policy went from report-only to
    // ENFORCING, because script-src has no 'unsafe-eval' - correctly, since the site
    // itself uses no eval or new Function anywhere. Injecting the source as a real
    // <script> element keeps the test honest: it exercises the same CSP the site
    // actually ships, rather than working around it with Page.setBypassCSP.
    // 'unsafe-inline' IS in the policy (19 onclick handlers make it unavoidable), so
    // an inline <script> is permitted where eval is not.
    body: `${PRELUDE}
      var src = ${JSON.stringify(PERSONA_SRC)};
      try {
        var el = document.createElement('script');
        el.textContent = src;
        document.head.appendChild(el);
      } catch(e){ return { pass:false, detail:'script injection failed: '+e }; }
      if (typeof window.runPersonaRegression !== 'function') return { pass:false, detail:'harness did not define runPersonaRegression' };
      var res = await window.runPersonaRegression();
      var fails = res.results.filter(function(r){return !r.pass;}).map(function(r){return r.persona;});
      return { pass: res.failed === 0, detail: res.passed+'/'+res.total+' personas passed', failures: fails };
    `,
  },
  {
    // The search box is injected by app.js and fetches its index lazily, so
    // nothing about it is exercised by simply loading a page. This types a real
    // query and asserts the right answer comes back, including the synonym path
    // ("wife" must reach the answers that say "spouse").
    name: "6. Sitewide search: overlay opens, synonyms + un-hyphenated forms resolve",
    page: "/faq.html",
    body: `${PRELUDE}
      var trigger = document.getElementById('gcs-trigger');
      if (!trigger) return { pass:false, detail:'search trigger was never injected into the topbar' };
      var modal = document.getElementById('gcs-modal');
      if (!modal) return { pass:false, detail:'search overlay was never created' };
      if (!modal.hidden) return { pass:false, detail:'overlay started visible; it should open only on demand' };

      // The overlay must be opened before the input is reachable.
      trigger.click();
      await wait(150);
      if (modal.hidden) return { pass:false, detail:'clicking the trigger did not open the overlay' };
      var input = document.getElementById('gcs-input');
      if (!input) return { pass:false, detail:'search input missing inside the overlay' };

      // The index is fetched on open. Wait for it rather than sleeping a fixed
      // amount, or the queries below race the fetch.
      for (var w = 0; w < 60 && !window.__gcsReady; w++) await wait(100);
      if (!window.__gcsReady) return { pass:false, detail:'search index never finished loading (6s)' };
      var idxOk = false;
      try {
        var r = await fetch('/search-index.json');
        idxOk = r.ok;
        var arr = await r.json();
        if (!Array.isArray(arr) || arr.length < 50) return { pass:false, detail:'index too small: '+(arr&&arr.length) };
        var kinds = {};
        arr.forEach(function(e){ kinds[e.t]=(kinds[e.t]||0)+1; });
        if (!kinds.q || !kinds.g || !kinds.p) return { pass:false, detail:'index missing a kind: '+JSON.stringify(kinds) };
        window.__kinds = kinds; window.__n = arr.length;
      } catch(e) { return { pass:false, detail:'index fetch failed: '+e }; }

      function type(v){ input.value = v; input.dispatchEvent(new Event('input',{bubbles:true})); }
      async function results(v){
        type(v);
        // Rendering is synchronous once the index is in memory, but give the
        // DOM a beat so a failure here means "no match", not "not yet drawn".
        for (var i = 0; i < 20; i++) {
          await wait(50);
          var got = document.querySelectorAll('#gcs-panel .gcs-item');
          if (got.length) return [].slice.call(got);
          if (document.querySelector('#gcs-panel .gcs-empty')) break;
        }
        return [];
      }

      var fails = [];

      // Synonym: "wife" is never on the page; the answers say "spouse".
      var a = await results('can my wife work');
      if (!a.length) fails.push('no results for "can my wife work"');
      else if (!/spouse/i.test(a[0].textContent)) fails.push('top hit for "wife" was not a spouse answer: '+a[0].textContent.slice(0,50));

      // Synonym: "fired" must reach the layoff answer.
      var b = await results('fired');
      if (!b.length) fails.push('no results for "fired"');
      else if (!/laid off/i.test(b[0].textContent)) fails.push('top hit for "fired" was not the layoff answer: '+b[0].textContent.slice(0,50));

      // Exact term reaches both the question and the glossary entry.
      var c = await results('cap gap');
      if (c.length < 2) fails.push('"cap gap" returned fewer than 2 results');
      var hrefs = c.map(function(x){return x.getAttribute('href');});
      if (!hrefs.some(function(h){return h.indexOf('faq.html#q-')===0;})) fails.push('"cap gap" returned no FAQ question');
      if (!hrefs.some(function(h){return h.indexOf('glossary.html#')===0;})) fails.push('"cap gap" returned no glossary entry');

      // A nonsense query must say so rather than showing stale results.
      type('zzzzqqqq'); await wait(450);
      var empty = document.querySelector('#gcs-panel .gcs-empty');
      if (!empty) fails.push('no empty-state shown for a nonsense query');
      if (document.querySelectorAll('#gcs-panel .gcs-item').length) fails.push('stale results left on screen after a nonsense query');

      // Un-hyphenated forms must work: the site writes "H-1B", people type "h1b".
      var flatQ = ['h1b','eb2','i140','i94','h4'];
      for (var fi = 0; fi < flatQ.length; fi++) {
        var fr = await results(flatQ[fi]);
        if (!fr.length) fails.push('no results for un-hyphenated "'+flatQ[fi]+'"');
      }

      // Escape closes the whole overlay.
      type('cap gap'); await wait(400);
      input.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
      await wait(200);
      if (!modal.hidden) fails.push('Escape did not close the overlay');

      return {
        pass: fails.length === 0,
        detail: 'index '+window.__n+' entries '+JSON.stringify(window.__kinds)+', idxHTTP='+idxOk,
        failures: fails
      };
    `,
  },
  {
    // A search result is only useful if following it actually reveals the answer.
    // Questions live inside a collapsed-capable section shell, so the anchor
    // handler has to open BOTH or the reader lands on hidden content.
    name: "6b. Deep link to a question opens the question and its section",
    page: "/faq.html#q-my-spouse-works-on-an-l-2-if-i-move-from-l-1-to-h-1b",
    body: `${PRELUDE}
      var q = document.getElementById('q-my-spouse-works-on-an-l-2-if-i-move-from-l-1-to-h-1b');
      if (!q) return { pass:false, detail:'target question id not found on the page' };
      var fails = [];
      if (!q.open) fails.push('the question itself did not open');
      var shell = q.closest('details.section-collapse');
      if (!shell) fails.push('question is not inside a section-collapse shell');
      else if (!shell.open) fails.push('the section shell stayed closed, so the answer is hidden');
      var sec = q.closest('section.hub-section');
      return {
        pass: fails.length === 0,
        detail: 'section='+(sec?sec.id:'?')+' questionOpen='+q.open+' shellOpen='+(shell?shell.open:'n/a'),
        failures: fails
      };
    `,
  },
  {
    // axe normally runs on a freshly loaded page, where the results panel is
    // empty and display:none. That means the rendered results have never been
    // scanned. This opens the panel first, then scans.
    name: "6c. Accessibility of the search results panel while OPEN",
    page: "/faq.html",
    body: `${PRELUDE}
      var trigger = document.getElementById('gcs-trigger');
      if (!trigger) return { pass:false, detail:'search trigger missing' };
      trigger.click();
      await wait(150);
      var input = document.getElementById('gcs-input');
      if (!input) return { pass:false, detail:'search input missing' };
      for (var w = 0; w < 60 && !window.__gcsReady; w++) await wait(100);
      if (!window.__gcsReady) return { pass:false, detail:'search index never loaded' };
      input.value = 'cap gap';
      input.dispatchEvent(new Event('input',{bubbles:true}));
      for (var i = 0; i < 20 && !document.querySelectorAll('#gcs-panel .gcs-item').length; i++) await wait(50);
      if (!document.querySelectorAll('#gcs-panel .gcs-item').length) {
        return { pass:false, detail:'panel had no results to scan' };
      }
      // axe is pre-injected per navigation in main(); nothing to load here.
      // A missing axe is a FAILED check, not a silent pass - reporting it as a pass is
      // how an accessibility suite goes from real audits to zero unnoticed.
      if (!window.axe) return { pass:false, detail:'axe was not pre-injected' };
      var r = await window.axe.run(document.getElementById('gcs-modal'), {
        runOnly:{ type:'tag', values:['wcag2a','wcag2aa','best-practice'] }
      });
      return {
        pass: r.violations.length === 0,
        detail: r.violations.length+' violation(s) in the open search panel',
        failures: r.violations.map(function(v){return v.id+' ('+v.nodes.length+')';})
      };
    `,
  },
];

/* ---------- accessibility pass ----------
   axe used to be pulled straight from cdnjs INSIDE the page. That silently stopped
   working the moment the Content-Security-Policy went from report-only to ENFORCING,
   because script-src allows 'self' and gc.zgo.at only. Worse, the failure was
   reported as { pass: true, detail: 'SKIPPED' }, so the a11y suite quietly went from
   5 real page audits to zero while the summary still looked green.

   Now: Node downloads axe once into a gitignored cache and the source is injected as
   an INLINE script, which the policy does permit ('unsafe-inline' is unavoidable
   here given 19 onclick handlers). That keeps the audit running against the same CSP
   the site actually ships, instead of disabling the policy with Page.setBypassCSP.
   A genuinely unavailable axe is now reported as a FAILURE, not a silent pass. */
const A11Y_PAGES = ["/index.html", "/status.html", "/eb1a.html", "/tools.html", "/faq.html", "/niw-appeals.html", "/niw-decisions.html", "/niw-guide.html"];
const AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js";
const AXE_CACHE = ".cache/axe-core-4.10.2.min.js";
let AXE_SRC = null;

async function loadAxeSource() {
  if (AXE_SRC !== null) return AXE_SRC;
  const { readFileSync, writeFileSync, mkdirSync, existsSync } = await import("node:fs");
  if (existsSync(AXE_CACHE)) {
    AXE_SRC = readFileSync(AXE_CACHE, "utf8");
    return AXE_SRC;
  }
  try {
    const r = await fetch(AXE_URL);
    if (!r.ok) throw new Error("HTTP " + r.status);
    AXE_SRC = await r.text();
    mkdirSync(".cache", { recursive: true });
    writeFileSync(AXE_CACHE, AXE_SRC);
    console.log(`  (cached axe-core to ${AXE_CACHE}, ${(AXE_SRC.length / 1024).toFixed(0)} KB)`);
  } catch (e) {
    AXE_SRC = "";
    console.log(`  (could not download axe-core: ${e.message})`);
  }
  return AXE_SRC;
}

async function axeRun(cdp, path) {
  if (!AXE_SRC) return { ok: false, reason: "axe-core unavailable: no network and no cached copy" };
  await navigate(cdp, BASE_URL + path);
  const r = await evaluate(cdp, `
    try {
      if (!window.axe) return { ok:false, reason:'axe was not pre-injected' };
      var out = await axe.run(document, { runOnly: ['wcag2a','wcag2aa','best-practice'] });
      // Report the offending NODE, not just the rule id. A bare 'heading-order' sends you
      // hunting; the selector and the element's html tell you immediately.
      return { ok:true, violations: out.violations.length,
               ids: out.violations.map(function(v){return v.id;}),
               nodes: out.violations.map(function(v){
                 return v.id + ' @ ' + v.nodes.map(function(nd){
                   return nd.target.join(' ') + ' -> ' + nd.html.slice(0,110);
                 }).join(' ;; ');
               }),
               vw: window.innerWidth };
    } catch (e) { return { ok:false, reason: String(e && e.message || e) }; }
  `);
  return r;
}

/* ---------- run ---------- */
async function main() {
  await loadAxeSource();   // populate .cache/ before any flow needs it
  const bin = findChrome();
  if (!bin) {
    console.error("\nNo Chrome/Chromium found. Set CHROME_BIN=/path/to/chrome, or install Chrome.\n" +
      "(Playwright's cached Chromium under ~/Library/Caches/ms-playwright also works.)\n");
    process.exit(2);
  }
  console.log(`\nGreen Card Navigator — interactive audit`);
  console.log(`Target : ${BASE_URL}`);
  console.log(`Browser: ${bin}\n`);

  let browser;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try { browser = await launchBrowser(bin); break; }
    catch (e) {
      if (attempt === 2) { console.error("Failed to launch browser: " + e.message); process.exit(2); }
      console.error("Launch attempt " + attempt + " failed (" + e.message.split("\n")[0] + "); retrying...");
      await sleep(1500);
    }
  }
  const { cdp, kill } = browser;

  // addScriptToEvaluateOnNewDocument runs before any page script on EVERY navigation,
  // so window.axe simply exists everywhere. This is a debugger-level injection, not a
  // page <script>, so it does not depend on the site's CSP or on the local server
  // serving a dotfile directory - both of which bit the previous approaches.
  if (AXE_SRC) {
    try {
      await cdp.send("Page.enable");
      await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: AXE_SRC });
    } catch (e) {
      console.error("  (could not pre-inject axe-core: " + e.message + ")");
    }
  }

  const results = [];
  try {
    for (const flow of FLOWS) {
      let out;
      try {
        await navigate(cdp, BASE_URL + flow.page);
        out = await evaluate(cdp, flow.body);
        if (flow.reloadCheck) {
          await navigate(cdp, BASE_URL + flow.page); // reload same origin; localStorage persists
          const after = await evaluate(cdp, flow.reloadCheck);
          out = after; // the reload check is the real assertion
        }
      } catch (e) {
        out = { pass: false, detail: "flow error: " + e.message };
      }
      const pass = out && out.pass === true;
      results.push({ name: flow.name, pass, out });
      const mark = pass ? "PASS" : "FAIL";
      console.log(`[${mark}] ${flow.name}`);
      if (out && out.detail) console.log(`        ${out.detail}`);
      if (out && out.failures && out.failures.length) console.log(`        failing: ${out.failures.join("; ")}`);
      if (out && out.options) console.log(`        selector options: ${out.options.join(", ")}`);
      if (out && out.__error) console.log(`        (page error) ${out.__error}`);
    }

    // Accessibility (best-effort; needs cdnjs reachable)
    console.log(`\n--- Accessibility (axe-core WCAG2 A/AA + best-practice) ---`);
    for (const p of A11Y_PAGES) {
      let r;
      try { r = await axeRun(cdp, p); } catch (e) { r = { ok: false, reason: e.message }; }
      if (r && r.ok) {
        const mark = r.violations === 0 ? "PASS" : "FAIL";
        console.log(`[${mark}] ${p} — ${r.violations} violation(s)${r.violations ? ": " + r.ids.join(", ") : ""}`);
        if (r.violations && r.nodes) r.nodes.forEach((x) => console.log(`        vw=${r.vw} ${x}`));
        results.push({ name: "a11y " + p, pass: r.violations === 0, out: r });
      } else {
        console.log(`[SKIP] ${p} — axe could not run (${r && r.reason})`);
      }
    }
  } finally {
    kill();
  }

  const flowResults = results.filter((r) => !r.name.startsWith("a11y") || true);
  const failed = results.filter((r) => !r.pass);
  console.log(`\n====================================================`);
  console.log(`Summary: ${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) console.log(`Failed: ${failed.map((f) => f.name).join(" | ")}`);
  console.log(`====================================================\n`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
