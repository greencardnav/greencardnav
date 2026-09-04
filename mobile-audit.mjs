#!/usr/bin/env node
/*
 * mobile-audit.mjs — drive the site at a real phone viewport and assert the
 * things that only break on small screens.
 *
 * WHY THIS EXISTS SEPARATELY from review-audit.mjs: that script audits behavior
 * at a desktop viewport. Everything it covers can pass while the phone layout is
 * horizontally scrolling, the search overlay is unusable, or a tap target is too
 * small to hit. Those are different failures and need their own viewport.
 *
 * Uses CDP's Emulation.setDeviceMetricsOverride with touch enabled, so the
 * mobile media queries and the touch-only chrome (bottom tab bar, More drawer)
 * actually engage.
 *
 * ZERO npm dependencies, same approach as review-audit.mjs.
 *
 * USAGE:
 *   BASE_URL=http://localhost:8137 node mobile-audit.mjs
 *   node mobile-audit.mjs                  # audits the live site
 *   DEVICE=tablet node mobile-audit.mjs    # 768x1024 instead of 390x844
 */

import { spawn } from "node:child_process";
import { readFileSync, existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir, homedir } from "node:os";
import { join } from "node:path";

const BASE_URL = (process.env.BASE_URL || "https://www.greencardnav.com").replace(/\/$/, "");
const HEADLESS = process.env.HEADFUL ? [] : ["--headless=new"];

// iPhone 14/15 logical viewport by default. 390px is the width most worth
// protecting: narrow enough to catch overflow, common enough to matter.
const DEVICES = {
  phone:  { width: 390, height: 844, dpr: 3, mobile: true,  label: "phone 390x844" },
  small:  { width: 360, height: 780, dpr: 3, mobile: true,  label: "small phone 360x780" },
  tablet: { width: 768, height: 1024, dpr: 2, mobile: true, label: "tablet 768x1024" },
};
const DEV = DEVICES[process.env.DEVICE || "phone"] || DEVICES.phone;

function findChrome() {
  if (process.env.CHROME_BIN && existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  const home = homedir();
  const candidates = [
    `${home}/Library/Caches/ms-playwright/chromium-1212/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  try {
    const base = `${home}/Library/Caches/ms-playwright`;
    if (existsSync(base)) {
      for (const dir of readdirSync(base)) {
        if (!/^chromium/.test(dir)) continue;
        const p = `${base}/${dir}/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;
        if (existsSync(p)) return p;
      }
    }
  } catch {}
  return null;
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0; this.pending = new Map(); this.waiters = [];
    this.ready = new Promise((res, rej) => {
      this.ws.addEventListener("open", () => res());
      this.ws.addEventListener("error", (e) => rej(new Error("WS error: " + (e.message || e.type))));
    });
    this.ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id != null && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
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
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error("CDP timeout: " + method)); } }, 30000);
    });
  }
  waitEvent(method, ms = 20000) {
    return new Promise((resolve, reject) => {
      const w = { method, resolve }; this.waiters.push(w);
      setTimeout(() => { this.waiters = this.waiters.filter((x) => x !== w); reject(new Error("event timeout: " + method)); }, ms);
    });
  }
  close() { try { this.ws.close(); } catch {} }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch(bin) {
  const userDataDir = mkdtempSync(join(tmpdir(), "gcn-mobile-"));
  const proc = spawn(bin, [...HEADLESS, "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--mute-audio",
    `--user-data-dir=${userDataDir}`, "--remote-debugging-port=0", "about:blank"],
    { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "", exited = false;
  proc.stderr.on("data", (d) => { stderr += d.toString(); });
  proc.on("exit", () => { exited = true; });
  const portFile = join(userDataDir, "DevToolsActivePort");
  let port = null;
  for (let i = 0; i < 200; i++) {
    if (exited) throw new Error("Chrome exited during startup.\n" + stderr.slice(-400));
    if (existsSync(portFile)) {
      const line = readFileSync(portFile, "utf8").split("\n")[0].trim();
      if (line) { port = line; break; }
    }
    await sleep(100);
  }
  if (!port) { proc.kill(); throw new Error("no debugging port"); }
  let target = null;
  for (let i = 0; i < 30; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = list.find((t) => t.type === "page"); if (target) break;
    } catch {}
    await sleep(150);
  }
  if (!target) { proc.kill(); throw new Error("no page target"); }
  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.ready;
  await cdp.send("Page.enable"); await cdp.send("Runtime.enable");
  // This is the whole point: emulate the device BEFORE navigating, so the
  // mobile media queries and touch-only chrome apply from first paint.
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: DEV.width, height: DEV.height, deviceScaleFactor: DEV.dpr,
    mobile: DEV.mobile, screenWidth: DEV.width, screenHeight: DEV.height,
  });
  await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await cdp.send("Emulation.setUserAgentOverride", {
    userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 " +
               "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  });
  return { proc, cdp, kill: () => { cdp.close(); try { proc.kill(); } catch {} } };
}

async function go(cdp, url) {
  const loaded = cdp.waitEvent("Page.loadEventFired", 25000).catch(() => null);
  await cdp.send("Page.navigate", { url });
  await loaded;
  await sleep(900);
}

async function evaluate(cdp, body) {
  const r = await cdp.send("Runtime.evaluate", {
    expression: `(async () => { ${body} })()`, awaitPromise: true, returnByValue: true,
  });
  if (r.exceptionDetails) {
    return { __error: r.exceptionDetails.exception ? r.exceptionDetails.exception.description : "eval exception" };
  }
  return r.result.value;
}

const HELP = `
  function wait(ms){ return new Promise(function(r){setTimeout(r,ms);}); }
  // Elements wider than the viewport are the usual cause of a page that scrolls
  // sideways on a phone. Report the worst offenders by name so the fix is obvious.
  function overflowers(){
    var vw = document.documentElement.clientWidth, out = [];
    var all = document.querySelectorAll('body *');
    for (var i=0;i<all.length;i++){
      var el=all[i], r=el.getBoundingClientRect();
      if (r.width===0 && r.height===0) continue;
      var cs=getComputedStyle(el);
      if (cs.position==='fixed') continue;              // overlays legitimately span
      // Skip links are deliberately parked far off-screen left; that is the
      // standard pattern and contributes nothing to rightward scroll.
      if (r.right < 0) continue;
      // Content INSIDE an opt-in horizontal scroller (a wide table, a tab strip)
      // is supposed to exceed the viewport; the scroller clips it and the page
      // itself does not move. Walk up, not just check this element.
      var anc = el, inScroller = false;
      while (anc && anc !== document.body) {
        var acs = getComputedStyle(anc);
        if (acs.overflowX === 'auto' || acs.overflowX === 'scroll' || acs.overflowX === 'hidden') { inScroller = true; break; }
        anc = anc.parentElement;
      }
      if (inScroller) continue;
      if (r.right > vw + 1.5 || r.left < -1.5) {
        out.push((el.tagName.toLowerCase()) + (el.id?('#'+el.id):'') +
                 (el.className && typeof el.className==='string' ? ('.'+el.className.trim().split(/\\s+/).slice(0,2).join('.')) : '') +
                 ' [' + Math.round(r.left) + '..' + Math.round(r.right) + ']');
      }
    }
    return out.slice(0,6);
  }
  function tapTooSmall(sel, min){
    var bad=[];
    document.querySelectorAll(sel).forEach(function(el){
      var r=el.getBoundingClientRect();
      if (r.width===0&&r.height===0) return;
      if (r.height < min || r.width < min) bad.push((el.id||el.className||el.tagName)+' '+Math.round(r.width)+'x'+Math.round(r.height));
    });
    return bad.slice(0,6);
  }
`;

const CHECKS = [
  {
    name: "M1. No horizontal overflow on the main pages",
    multi: ["/index.html", "/faq.html", "/glossary.html", "/status.html", "/eb2.html", "/tools.html", "/compare.html", "/niw-decisions.html", "/niw-guide.html"],
    body: `${HELP}
      var vw = document.documentElement.clientWidth;
      var sw = document.documentElement.scrollWidth;
      var off = overflowers();
      return {
        pass: sw <= vw + 2 && off.length === 0,
        detail: 'viewport='+vw+' scrollWidth='+sw,
        failures: off
      };
    `,
  },
  {
    name: "M2. Search: trigger is visible, tappable, and opens a full-width overlay",
    page: "/faq.html",
    body: `${HELP}
      var fails=[];
      var t=document.getElementById('gcs-trigger');
      if(!t) return {pass:false, detail:'no search trigger on mobile'};
      var tr=t.getBoundingClientRect();
      if (tr.width===0||tr.height===0) fails.push('trigger has no size');
      if (tr.right > document.documentElement.clientWidth) fails.push('trigger sits off-screen at '+Math.round(tr.right));
      if (tr.height < 28) fails.push('trigger only '+Math.round(tr.height)+'px tall');

      t.click(); await wait(250);
      var m=document.getElementById('gcs-modal');
      if(!m || m.hidden) return {pass:false, detail:'overlay did not open on tap', failures:fails};
      var sheet=m.querySelector('.gcs-sheet').getBoundingClientRect();
      var vw=document.documentElement.clientWidth;
      // On a phone the sheet should use essentially the whole width; a 620px
      // desktop card centered in 390px would overflow.
      if (sheet.width > vw+1) fails.push('sheet wider than viewport: '+Math.round(sheet.width)+' > '+vw);
      // Only phones should get the edge-to-edge sheet. At tablet width a centred
      // card is the intended look, so do not demand near-full width there.
      if (vw < 761 && sheet.width < vw*0.9) fails.push('sheet only '+Math.round(sheet.width)+'px of '+vw);
      var inp=document.getElementById('gcs-input');
      if (!inp) fails.push('no input in overlay');
      else if (inp.getBoundingClientRect().width < 120) fails.push('input too narrow to type in');
      return { pass: fails.length===0, detail:'trigger '+Math.round(tr.width)+'x'+Math.round(tr.height)+', sheet '+Math.round(sheet.width)+'px of '+vw, failures:fails };
    `,
  },
  {
    name: "M3. Search results render, fit the screen, and are tappable",
    page: "/faq.html",
    body: `${HELP}
      var fails=[];
      document.getElementById('gcs-trigger').click();
      await wait(200);
      for (var w=0;w<60 && !window.__gcsReady;w++) await wait(100);
      if (!window.__gcsReady) return {pass:false, detail:'index never loaded on mobile'};
      var inp=document.getElementById('gcs-input');
      inp.value='h1b'; inp.dispatchEvent(new Event('input',{bubbles:true}));
      for (var i=0;i<20 && !document.querySelectorAll('#gcs-panel .gcs-item').length;i++) await wait(50);
      var items=document.querySelectorAll('#gcs-panel .gcs-item');
      if(!items.length) return {pass:false, detail:'no results for "h1b" on mobile'};
      var vw=document.documentElement.clientWidth, small=0;
      items.forEach(function(el){
        var r=el.getBoundingClientRect();
        if (r.right > vw+1) fails.push('result overflows: '+Math.round(r.right)+' > '+vw);
        if (r.height < 34) small++;
      });
      if (small) fails.push(small+' result row(s) under 34px tall');
      var panel=document.getElementById('gcs-panel').getBoundingClientRect();
      if (panel.height > document.documentElement.clientHeight) fails.push('panel taller than the screen with no scroll');
      return { pass: fails.length===0, detail:items.length+' results, tallest row '+Math.round(items[0].getBoundingClientRect().height)+'px', failures:fails };
    `,
  },
  {
    name: "M4. FAQ: index, section collapse, and question disclosure all work by tap",
    page: "/faq.html",
    body: `${HELP}
      var fails=[];
      var toc=document.querySelector('.paths-toc');
      if(!toc) fails.push('no on-page index');
      else {
        var tr=toc.getBoundingClientRect();
        if (tr.width > document.documentElement.clientWidth+1) fails.push('index wider than viewport');
        if (getComputedStyle(toc).position === 'sticky') fails.push('index still sticky on mobile (eats the screen)');
      }
      var sec=document.querySelector('details.faq-sec');
      if(!sec) fails.push('no section collapse shell');
      else {
        var s=sec.querySelector('summary');
        var was=sec.open; s.click(); await wait(150);
        if (sec.open===was) fails.push('section shell did not toggle on tap');
        s.click(); await wait(150);
      }
      var q=document.querySelector('details.collapsible[id^="q-"]');
      if(!q) fails.push('no question disclosures');
      else {
        var qs=q.querySelector('summary');
        var qr=qs.getBoundingClientRect();
        if (qr.height < 34) fails.push('question summary only '+Math.round(qr.height)+'px tall');
        qs.click(); await wait(200);
        if(!q.open) fails.push('question did not open on tap');
        var body=q.querySelector('.body');
        if (body && body.getBoundingClientRect().right > document.documentElement.clientWidth+1) fails.push('answer body overflows the viewport');
      }
      return { pass: fails.length===0, detail:'sections='+document.querySelectorAll('details.faq-sec').length+' questions='+document.querySelectorAll('details.collapsible[id^="q-"]').length, failures:fails };
    `,
  },
  {
    name: "M5. Mobile bottom tab bar exists and the More drawer includes FAQ",
    page: "/faq.html",
    body: `${HELP}
      var fails=[];
      var bar=document.querySelector('.m-tabbar');
      if(!bar) return {pass:false, detail:'no bottom tab bar was injected at this viewport'};
      // The bar is phone-only by design (display:none from 768px up), so above
      // that breakpoint its absence is correct rather than a failure.
      if (getComputedStyle(bar).display === 'none') {
        return { pass:true, detail:'tab bar correctly hidden at '+document.documentElement.clientWidth+'px' };
      }
      var tabs=bar.querySelectorAll('.m-tab');
      if (tabs.length < 4) fails.push('only '+tabs.length+' tabs');
      var br=bar.getBoundingClientRect();
      if (br.width > document.documentElement.clientWidth+1) fails.push('tab bar wider than viewport');
      tabs.forEach(function(t){
        var r=t.getBoundingClientRect();
        if (r.height < 40) fails.push('tab under 40px tall: '+Math.round(r.height));
      });
      // The More button is the last .m-tab and is a <button>, not a link.
      var moreBtn=[].slice.call(tabs).filter(function(x){return x.tagName==='BUTTON';})[0];
      if(!moreBtn) fails.push('no More button');
      else {
        moreBtn.click(); await wait(300);
        var drawer=document.getElementById('m-drawer');
        if(!drawer || !drawer.classList.contains('open')) fails.push('More drawer did not open');
        else {
          var hrefs=[].slice.call(drawer.querySelectorAll('a')).map(function(a){return a.getAttribute('href');});
          if (hrefs.indexOf('faq.html')===-1) fails.push('FAQ missing from the More drawer: '+hrefs.join(','));
        }
      }
      return { pass: fails.length===0, detail:tabs.length+' tabs', failures:fails };
    `,
  },
  {
    name: "M6. Body text is legible and the disclaimer does not dominate",
    page: "/faq.html",
    body: `${HELP}
      var fails=[];
      var p=document.querySelector('.faq-short') || document.querySelector('.hub-sub');
      if (p) {
        var fs=parseFloat(getComputedStyle(p).fontSize);
        if (fs < 13) fails.push('body text only '+fs+'px');
      }
      var band=document.querySelector('.disclaimer-banner');
      if (band) {
        var h=band.getBoundingClientRect().height;
        if (h > document.documentElement.clientHeight*0.3) fails.push('disclaimer takes '+Math.round(h)+'px, over 30% of the screen');
      }
      return { pass: fails.length===0, detail:'body '+(p?getComputedStyle(p).fontSize:'?')+', disclaimer '+(band?Math.round(band.getBoundingClientRect().height)+'px':'none'), failures:fails };
    `,
  },
];

// Cached axe source, downloaded once by Node and pre-injected per navigation so the
// page never needs a network fetch. Mirrors review-audit.mjs.
const AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js";
const AXE_CACHE = ".cache/axe-core-4.10.2.min.js";
let AXE_SRC = null;
async function loadAxeSource() {
  if (AXE_SRC !== null) return AXE_SRC;
  const { readFileSync, writeFileSync, mkdirSync, existsSync } = await import("node:fs");
  if (existsSync(AXE_CACHE)) { AXE_SRC = readFileSync(AXE_CACHE, "utf8"); return AXE_SRC; }
  try {
    const r = await fetch(AXE_URL);
    if (!r.ok) throw new Error("HTTP " + r.status);
    AXE_SRC = await r.text();
    mkdirSync(".cache", { recursive: true });
    writeFileSync(AXE_CACHE, AXE_SRC);
  } catch (e) { AXE_SRC = ""; console.log(`  (could not download axe-core: ${e.message})`); }
  return AXE_SRC;
}

async function axeAt(cdp, path) {
  await go(cdp, BASE_URL + path);
  const r = await evaluate(cdp, `
    if (!window.axe) return { missing: true };
    var r = await window.axe.run(document, { runOnly:{ type:'tag', values:['wcag2a','wcag2aa'] } });
    return { violations: r.violations.length, ids: r.violations.map(function(v){return v.id+'('+v.nodes.length+')';}) };
  `);
  return r;
}

async function main() {
  const bin = findChrome();
  if (!bin) { console.error("No Chrome/Chromium found. Set CHROME_BIN."); process.exit(2); }
  console.log(`Green Card Navigator — MOBILE audit`);
  console.log(`Target : ${BASE_URL}`);
  console.log(`Device : ${DEV.label}, touch on, iOS Safari UA\n`);

  const { cdp, kill } = await launch(bin);

  // Pre-inject axe once per navigation at the debugger level, so no page ever needs a
  // network fetch for it and the check cannot silently vanish.
  await loadAxeSource();
  if (AXE_SRC) {
    try {
      await cdp.send("Page.enable");
      await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: AXE_SRC });
    } catch (e) { console.error("  (could not pre-inject axe-core: " + e.message + ")"); }
  }
  const results = [];
  try {
    for (const c of CHECKS) {
      const pages = c.multi || [c.page];
      let allPass = true, details = [], failures = [];
      for (const p of pages) {
        await go(cdp, BASE_URL + p);
        const out = await evaluate(cdp, c.body);
        if (!out || out.__error) {
          allPass = false; failures.push(`${p}: ${out && out.__error}`); continue;
        }
        if (!out.pass) allPass = false;
        if (out.failures && out.failures.length) failures.push(...out.failures.map((f) => `${p}: ${f}`));
        if (pages.length > 1) { if (!out.pass) details.push(`${p} ${out.detail}`); }
        else details.push(out.detail);
      }
      results.push({ name: c.name, pass: allPass });
      console.log(`[${allPass ? "PASS" : "FAIL"}] ${c.name}`);
      if (details.length) console.log(`        ${details.join(" | ")}`);
      failures.slice(0, 8).forEach((f) => console.log(`        - ${f}`));
    }

    console.log(`\n--- Accessibility at ${DEV.label} (WCAG2 A/AA) ---`);
    for (const p of ["/index.html", "/faq.html", "/status.html", "/niw-decisions.html", "/niw-guide.html"]) {
      const r = await axeAt(cdp, p);
      if (!r || r.missing) { fail(`${p} — axe was not pre-injected`, "accessibility check could not run"); continue; }
      const ok = r.violations === 0;
      results.push({ name: "a11y " + p, pass: ok });
      console.log(`[${ok ? "PASS" : "FAIL"}] ${p} — ${r.violations} violation(s)${r.violations ? ": " + r.ids.join(", ") : ""}`);
    }
  } finally { kill(); }

  const failed = results.filter((r) => !r.pass);
  console.log(`\n====================================================`);
  console.log(`Mobile summary: ${results.length - failed.length}/${results.length} checks passed`);
  if (failed.length) console.log(`Failed: ${failed.map((f) => f.name).join(" | ")}`);
  console.log(`====================================================\n`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
