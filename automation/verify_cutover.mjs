#!/usr/bin/env node
// Domain-cutover gate. Run this against the NEW host before pushing the canonical
// swap, and again after the push. It is the checklist that decides whether the
// cutover is safe, in one command.
//
//   node automation/verify_cutover.mjs                       # defaults to greencardnav.com
//   node automation/verify_cutover.mjs example.com
//
// Phase 1 (run BEFORE pushing): does the new host serve the site at all? A canonical
// pointing at a host that does not resolve is worse than one pointing at the old host,
// because crawlers treat it as authoritative and then cannot fetch it.
//
// Phase 2 (run AFTER pushing): are the canonicals, sitemap, robots, fonts and security
// headers all consistent with the new host, and does the report-only CSP come back
// clean so it can be flipped to enforcing?
//
// Needs only node and headless Chrome. No npm dependencies, matching the other audits.

import { spawn } from 'node:child_process';
import http from 'node:http';

const HOST = (process.argv[2] || 'www.greencardnav.com').replace(/^https?:\/\//, '').replace(/\/$/, '');
const BASE = `https://${HOST}`;
const OLD_HOST = 'main.d20qtw2pnzotwx.amplifyapp.com';

const PAGES = ['index.html', 'status.html', 'paths.html', 'compare.html', 'tools.html',
  'eb1a.html', 'eb1b.html', 'eb1c.html', 'eb2.html', 'eb3.html',
  'faq.html', 'glossary.html', 'resources.html', 'about.html', 'privacy.html', 'community.html'];

let pass = 0, fail = 0, warn = 0;
const ck = (n, ok, d) => {
  if (ok) { pass++; console.log(`[PASS] ${n}${d ? ' - ' + d : ''}`); }
  else { fail++; console.log(`[FAIL] ${n}${d ? ' - ' + d : ''}`); }
};
const note = (n, d) => { warn++; console.log(`[WARN] ${n}${d ? ' - ' + d : ''}`); };

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
           '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

async function fetchIt(url, opts = {}) {
  try {
    return await fetch(url, { redirect: 'manual', headers: { 'User-Agent': UA }, ...opts });
  } catch (e) { return { ok: false, status: 0, err: e.message, headers: new Map() }; }
}

console.log(`\n=== cutover gate for ${HOST} ===\n`);

// ---- Phase 1: is the host live at all? -------------------------------------
const root = await fetchIt(BASE + '/');
if (!root.status) {
  console.log(`[FAIL] ${HOST} did not respond - ${root.err}`);
  console.log('\nThe domain is not serving yet. Add it in Amplify (Hosting -> Custom');
  console.log('domains), wait for the ACM certificate to validate, then re-run.');
  console.log('DO NOT push the canonical swap until this passes.\n');
  process.exit(1);
}
ck(`${HOST} responds over https`, root.status === 200, 'HTTP ' + root.status);

const html = root.status === 200 ? await root.text() : '';
ck(`${HOST} serves the site (not a parking page)`, /Green Card Navigator/i.test(html),
   html.length + ' bytes');

// www is primary (Amplify only supports the apex -> www direction), so every
// canonical is www-form and the APEX is what must 301 across. Verifying the
// direction matters: a canonical that disagrees with the served URL is the exact
// SEO failure this gate exists to catch.
const apex = HOST.replace(/^www\./, '');
const apexRes = await fetchIt(`https://${apex}/`);
if (!apexRes.status) note('apex does not resolve', 'people typing it bare will fail');
else if ([301, 302, 307, 308].includes(apexRes.status)) {
  const loc = apexRes.headers.get('location') || '';
  ck('apex redirects to the www host', loc.replace(/\/$/, '') === BASE, apexRes.status + ' -> ' + loc);
  // 301 vs 302 is not cosmetic for a domain move. A 302 says "temporary", so search
  // engines may keep the apex indexed instead of consolidating everything onto www.
  // Amplify's domain checkbox creates a 302 by default; it is editable to 301 under
  // Hosting -> Rewrites and redirects.
  if (apexRes.status === 301) ck('apex redirect is a permanent 301', true, '301');
  else note(`apex redirect is a ${apexRes.status}, not a 301`,
            'change it to 301 in Amplify -> Hosting -> Rewrites and redirects so link ' +
            'equity consolidates onto www');
  // A path-losing redirect would send every deep link to the homepage.
  const deep = await fetchIt(`https://${apex}/faq.html`);
  const dloc = deep.headers.get('location') || '';
  ck('apex redirect preserves the path', dloc === `${BASE}/faq.html`, dloc || 'no location');
} else if (apexRes.status === 200) {
  fail++; console.log('[FAIL] the apex serves content directly instead of redirecting to ' +
    BASE + ' - canonicals are www-form, so this is duplicate content on two hostnames.');
} else note('apex returned HTTP ' + apexRes.status);

// ---- Phase 2: consistency across every page --------------------------------
console.log('');
let canonOk = 0, canonBad = [];
for (const p of PAGES) {
  const r = await fetchIt(`${BASE}/${p}`);
  if (r.status !== 200) { canonBad.push(`${p} HTTP ${r.status}`); continue; }
  const s = await r.text();
  const m = s.match(/<link rel="canonical" href="([^"]+)"/);
  if (!m) canonBad.push(`${p} no canonical`);
  else if (!m[1].startsWith(BASE + '/')) canonBad.push(`${p} -> ${m[1]}`);
  else if (s.includes(OLD_HOST)) canonBad.push(`${p} still references the old host`);
  else canonOk++;
}
ck(`all ${PAGES.length} pages serve a ${HOST} canonical and no old-host references`,
   canonBad.length === 0, canonBad.length ? canonBad.slice(0, 4).join('; ') : canonOk + '/' + PAGES.length);

const sm = await fetchIt(BASE + '/sitemap.xml');
const smText = sm.status === 200 ? await sm.text() : '';
const locs = [...smText.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
ck('sitemap.xml reachable and fully on the new host',
   sm.status === 200 && locs.length > 0 && locs.every(u => u.startsWith(BASE + '/')),
   `${locs.length} <loc> entries`);

const rb = await fetchIt(BASE + '/robots.txt');
const rbText = rb.status === 200 ? await rb.text() : '';
ck('robots.txt points at the new sitemap', rbText.includes(`${BASE}/sitemap.xml`));
ck('robots.txt excludes the non-pages',
   rbText.includes('Disallow: /og.html') && rbText.includes('Disallow: /_chipnav-demo.html'));

// Security headers survive the domain change (they come from customHttp.yml).
const h = root.headers;
for (const [k, want] of [['x-frame-options', 'DENY'], ['x-content-type-options', 'nosniff'],
                         ['referrer-policy', 'no-referrer']]) {
  ck(`header ${k}`, (h.get(k) || '').toLowerCase() === want.toLowerCase(), h.get(k) || 'missing');
}
// HSTS only has meaning on the real domain: browsers ignore it on the amplifyapp.com
// host in practice, and a max-age under a year is not worth much.
const sts = h.get('strict-transport-security') || '';
const stsAge = parseInt((sts.match(/max-age=(\d+)/) || [])[1] || '0', 10);
ck('header strict-transport-security (>= 1 year)', stsAge >= 31536000, sts || 'missing');
if (/preload/i.test(sts)) note('HSTS carries preload', 'that is a one-way door; removal takes months');
const cspEnforce = h.get('content-security-policy');
const cspReport = h.get('content-security-policy-report-only');
ck('a CSP header is present', !!(cspEnforce || cspReport),
   cspEnforce ? 'ENFORCING' : cspReport ? 'report-only' : 'none');

// Fonts must come from our own origin now, with relative paths that follow the host.
const css = await fetchIt(BASE + '/styles.css');
const cssText = css.status === 200 ? await css.text() : '';
ck('styles.css has no Google Fonts reference',
   css.status === 200 && !/fonts\.(googleapis|gstatic)/.test(cssText));
const woff = [...cssText.matchAll(/url\('([^']+\.woff2)'\)/g)].map(m => m[1]);
ck('styles.css declares self-hosted woff2', woff.length > 0, woff.length + ' faces');
let fontsOk = 0;
for (const f of [...new Set(woff)]) {
  const r = await fetchIt(`${BASE}/${f.replace(/^\//, '')}`, { method: 'HEAD' });
  if (r.status === 200) fontsOk++;
  else console.log(`         missing font: ${f} -> HTTP ${r.status}`);
}
ck('every declared woff2 is fetchable on the new host', fontsOk === new Set(woff).size,
   `${fontsOk}/${new Set(woff).size}`);

// ---- Phase 3: live CSP violation sweep ------------------------------------
console.log('\n--- CSP violation sweep (decides whether it can be enforced) ---');
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ['--remote-debugging-port=9241', '--headless=new', '--no-first-run', '--disable-gpu',
   '--user-data-dir=/tmp/cutover-prof-' + Date.now(), 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const gj = u => new Promise((res, rej) => http.get(u, r => {
  let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
}).on('error', rej));

try {
  let tabs;
  for (let i = 0; i < 60; i++) { try { tabs = await gj('http://localhost:9241/json/list'); break; } catch { await sleep(250); } }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => { ws.onopen = r; });
  let id = 0; const w = new Map(); const jsErrs = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && w.has(m.id)) { w.get(m.id)(m); w.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') jsErrs.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  };
  const send = (me, p = {}) => new Promise(r => { const i = ++id; w.set(i, r); ws.send(JSON.stringify({ id: i, method: me, params: p })); });
  const ev = async x => (await send('Runtime.evaluate', { expression: x, returnByValue: true })).result?.result?.value;
  await send('Runtime.enable'); await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `window.__csp=[];document.addEventListener('securitypolicyviolation',e=>{
      window.__csp.push((e.effectiveDirective||e.violatedDirective)+' <- '+e.blockedURI);});`
  });

  const all = [];
  for (const p of PAGES) {
    await send('Page.navigate', { url: `${BASE}/${p}` });
    await sleep(2400);
    await ev(`(()=>{document.querySelectorAll('[data-tool-target]').forEach(b=>{try{b.click()}catch(e){}});
      document.querySelectorAll('details').forEach(d=>d.open=true);return 1})()`);
    await sleep(900);
    const v = JSON.parse((await ev('JSON.stringify(window.__csp||[])')) || '[]');
    if (v.length) { console.log(`  ${p.padEnd(18)} ${v.length} violation(s)`); v.forEach(x => all.push(x)); }
  }
  ck('zero CSP violations across all pages', all.length === 0,
     all.length ? [...new Set(all)].slice(0, 6).join(' | ') : 'clean');
  ck('no uncaught JS errors', jsErrs.length === 0, jsErrs.slice(0, 2).join(' | '));

  if (all.length === 0 && cspReport && !cspEnforce) {
    console.log('\n  -> Sweep is clean. Safe to rename Content-Security-Policy-Report-Only');
    console.log('     to Content-Security-Policy in customHttp.yml, as its own commit.');
  }
} catch (e) {
  console.error('sweep harness error:', e.message); fail++;
} finally { chrome.kill(); }

console.log(`\n${pass}/${pass + fail} checks passed${warn ? `, ${warn} warning(s)` : ''}`);
process.exit(fail ? 1 : 0);
