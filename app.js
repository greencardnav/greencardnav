/* Green Card Navigator — shared application script.
   Extracted verbatim from the original single-file tool: the main questionnaire
   IIFE, the theme-toggle IIFE, and the easter-egg IIFE. The same file loads on
   every page; each block no-ops where its target elements are absent. */

/* ================== CANONICAL HOST GUARD ==================
   The site is reachable on more than one hostname: the custom domain and the Amplify
   default, main.d20qtw2pnzotwx.amplifyapp.com, which serves the site directly (verified:
   HTTP 200, not a redirect). Amplify's own redirect rules are path-based and have no host
   condition, so the console cannot express "send this hostname to that one".

   Two problems that fixes at once:

   1. DUPLICATE CONTENT. Every page already carries a correct canonical pointing at the
      custom domain, so crawlers consolidate. Humans who land on the Amplify URL - from an
      old link or a bookmark - just stay there.

   2. SPLIT ANALYTICS. GoatCounter's count.js sends `location.pathname + location.search`
      and NEVER the hostname (read from the script itself), and it filters nothing except
      localhost and private IP ranges. So visits from every hostname were already being
      counted, but merged into one indistinguishable set of paths. Collapsing the hosts is a
      better fix than instrumenting the split, because it leaves one number that means one
      thing.

   The canonical host is READ FROM THE PAGE'S OWN CANONICAL rather than hardcoded, so
   automation/set_site_url.py stays the single place a host is ever written down.

   Runs BEFORE the analytics loader below, deliberately: after the redirect the pageview is
   counted once, on the canonical host, instead of once here and once there. */
(function () {
  "use strict";
  try {
    if (location.protocol !== "https:" && location.protocol !== "http:") return;
    // Never interfere with local development or private-network hosts. Same set count.js
    // itself ignores, so the two agree on what "not production" means.
    if (/(^localhost$|^127\.|^10\.|^172\.(1[6-9]|2[0-9]|3[0-1])\.|^192\.168\.|^0\.0\.0\.0$)/
        .test(location.hostname)) return;
    var link = document.querySelector('link[rel="canonical"][href]');
    if (!link) return;
    var a = document.createElement("a");
    a.href = link.href;
    if (!a.hostname || a.hostname === location.hostname) return;   // already canonical
    // Preserve where the visitor was actually going.
    location.replace(a.protocol + "//" + a.hostname + location.pathname +
                     location.search + location.hash);
  } catch (e) { /* never let this break the page */ }
})();

/* ===================== COOKIELESS, AGGREGATE ANALYTICS =====================
   Counts anonymous page views and a few FIXED event names (status-started /
   status-completed / result-viewed) via GoatCounter, so usage can be diagnosed
   (do visitors start a check? do they finish?). It NEVER sends case data — no
   category, country, dates, or any questionnaire value; only the literal event
   names below leave the browser. No cookies, no cross-site tracking, no ads.
   To turn it on, replace GC_CODE with your GoatCounter site code (the "xxxx" in
   xxxx.goatcounter.com). While it is the placeholder, nothing loads and nothing
   is sent — GCN_track is a safe no-op — so the tool ships fully private by default. */
(function () {
  "use strict";
  var GC_CODE = "gcnav"; // GoatCounter site code (gcnav.goatcounter.com)
  if (!GC_CODE || GC_CODE === "YOURCODE") { window.GCN_track = function () {}; return; }
  var pending = [];
  function emit(name) {
    if (window.goatcounter && window.goatcounter.count) {
      window.goatcounter.count({ path: name, title: name, event: true });
      return true;
    }
    return false;
  }
  // Public tracker: fire a fixed, anonymous event name. Queues until loaded.
  window.GCN_track = function (name) { if (!emit(name)) pending.push(name); };
  function load() {
    var s = document.createElement("script");
    s.async = true;
    // https, not protocol-relative: // downgrades to http on an http origin and
    // would force the CSP to allow both schemes for no benefit.
    s.src = "https://gc.zgo.at/count.js";
    s.setAttribute("data-goatcounter", "https://" + GC_CODE + ".goatcounter.com/count");
    s.onload = function () { var q = pending; pending = []; q.forEach(emit); };
    document.head.appendChild(s);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();

/* ================== HORIZONTAL TAB-STRIP AFFORDANCE ==================
   Three strips scroll sideways: .path-switch (EB Paths), .tool-switch (Tools) and
   .hubnav-links (top nav, below 768px). Two problems this fixes, both reported as "this
   feels broken":

   1. A CLIPPED TAB LOOKS LIKE A BUG. With 9 EB Paths tabs the strip needs ~724px inside a
      662px column, so the last tab was cut mid-word ("D" of "Decisions") with nothing to
      suggest it could be scrolled. This sets data-ovf=start|end|both and the stylesheet
      fades only the edge that genuinely has content behind it - so the hint is never a lie.

   2. THE ACTIVE TAB COULD BE OFF-SCREEN. Landing on niw-decisions.html put its own tab
      past the right edge, so the page you were on appeared to have no tab at all. On load
      the active tab is scrolled just into view.

   Both are progressive enhancement: with JS off the strips still scroll natively and no
   fade is painted, so nothing is hidden that was not already reachable.

   scrollLeft is set directly rather than via scrollIntoView(), which also scrolls every
   ancestor and would yank the page down on load. */
(function () {
  "use strict";
  var strips = document.querySelectorAll(".path-switch, .tool-switch, .hubnav-links");
  if (!strips.length) return;

  function mark(el) {
    // 1px of slack: subpixel layout leaves scrollWidth a hair over clientWidth on strips
    // that actually fit, and a permanent fade on a non-scrolling strip is just a smudge.
    var max = el.scrollWidth - el.clientWidth;
    if (max <= 1) { el.removeAttribute("data-ovf"); return; }
    var x = el.scrollLeft;
    el.setAttribute("data-ovf", x <= 1 ? "end" : (x >= max - 1 ? "start" : "both"));
  }

  strips.forEach(function (el) {
    var active = el.querySelector('a.active, a[aria-current="page"]');
    if (active) {
      // Only nudge if the active tab is actually past the right edge; never scroll left.
      var overshoot = active.offsetLeft + active.offsetWidth - el.clientWidth;
      if (overshoot > 0) el.scrollLeft = overshoot + 12;
    }
    mark(el);
    el.addEventListener("scroll", function () { mark(el); }, { passive: true });
  });

  var t;
  window.addEventListener("resize", function () {
    clearTimeout(t);
    t = setTimeout(function () { strips.forEach(mark); }, 120);
  });

  // Re-measure once webfonts land. Measured at load the EB Paths strip reported 662px of
  // content in a 662px box only AFTER Inter swapped in; with the fallback face the tabs were
  // wider, so the first pass set data-ovf="end" and left a fade on a strip that does not
  // actually scroll. Fonts change text metrics, so any width measurement taken before
  // fonts.ready is provisional.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () { strips.forEach(mark); });
  }
})();

/* ============================ MAIN APP IIFE ============================ */
(function () {
  "use strict";

  // ---- Load rulebook from inlined JSON ----
  var rulebook;
  try {
    // Shared across all pages via rulebook.js (window.__RULEBOOK__); fall back to
    // an inline #rulebook JSON block if a page still embeds one.
    if (window.__RULEBOOK__) {
      rulebook = window.__RULEBOOK__;
    } else {
      rulebook = JSON.parse(document.getElementById("rulebook").textContent);
    }
  } catch (e) {
    // Non-destructive: only replace the questionnaire region if present, never the
    // whole page (other pages share this script and have no #check element).
    var checkEl = document.getElementById("check");
    if (checkEl) { checkEl.innerHTML = "<div style='padding:40px;color:var(--worst-text)'>Failed to load rulebook. Refresh the page.</div>"; }
    return;
  }

  // ---- State ----
  var state = {
    category: null, country: null, pd: null,
    level: null, h1b: null, perm: null, i140: null, spouse: null, degree: null,
    locCurrent: null, locProspective: null,
    optExpiry: null, h1bLottery: null, eb1sub: null, roleChange: null,
    preVisa: null, preYear: null, preIntent: null,
    // Non-exclusive companion to Q1's green-card category. A person can be on
    // H-1B AND have an EB-3 case, so this is a "select all that apply" array
    // (values: "H-1B" | "L-1" | "F-1" | "None"). Optional — never gates the
    // required-question flow. Cross-category (kept across category switches),
    // cleared on full reset.
    workVisa: [],
    // Session-only, never persisted. Populated when the user pastes a newer
    // Visa Bulletin / a consular wait time / an IV scheduling-status month.
    // Cleared on reset and category switch.
    bulletinOverride: null, consular: null, ivSchedule: null
  };

  // When true, the bulletin/consular/IV cards are being shown standalone on the
  // Live tools page (tools.html), driven by the on-page category+country picker
  // rather than the questionnaire. In that mode there is no queue result to
  // recompute, so the bulletin preview shows the parsed dates as a read-only
  // "here's what I read" and omits the "Apply these dates" recompute button.
  var standaloneToolsMode = false;

  // ---- DOM refs ----
  var landing = document.getElementById("landing");
  var startBtn = document.getElementById("startBtn");
  var stepCategory = document.getElementById("step-category");
  var stepEb1Sub = document.getElementById("step-eb1sub");
  var stepCountry = document.getElementById("step-country");
  var stepPd = document.getElementById("step-pd");
  var stepRoleChange = document.getElementById("step-rolechange");
  var stepH1b = document.getElementById("step-h1b");
  var stepPerm = document.getElementById("step-perm");
  var stepI140 = document.getElementById("step-i140");
  var stepSpouse = document.getElementById("step-spouse");
  var stepDegree = document.getElementById("step-degree");
  var stepLocation = document.getElementById("step-location");
  var locCurrentSelect = document.getElementById("loc-current");
  var locProspectiveSelect = document.getElementById("loc-prospective");
  var stepSubmit = document.getElementById("step-submit");
  var stepResult = document.getElementById("step-result");
  var refineBlock = document.getElementById("refine-block");
  var pdInput = document.getElementById("pd-input");
  var pdError = document.getElementById("pd-error");
  var submitBtn = document.getElementById("submitBtn");
  var submitError = document.getElementById("submit-error");
  var resetBtn = document.getElementById("resetBtn");
  var resultContent = document.getElementById("result-content");
  var stepF1Opt = document.getElementById("step-f1-opt");
  var optExpiryInput = document.getElementById("opt-expiry-input");
  var stepPre = document.getElementById("step-pre");
  var stepWorkvisa = document.getElementById("step-workvisa");

  var optionalSteps = [stepRoleChange, stepH1b, stepPerm, stepI140, stepSpouse, stepDegree];

  // ---- Helpers ----
  function showReset() { if (resetBtn) resetBtn.classList.add("visible"); }
  function reveal(el) { el.classList.add("visible"); }
  function hide(el) { el.classList.remove("visible"); }

  function fmtDate(iso) {
    if (!iso) return null;
    if (iso === "CURRENT") return "Current";
    var parts = iso.split("-");
    if (parts.length !== 3) return iso;
    var y = parts[0], m = parts[1], d = parts[2];
    var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    var mi = parseInt(m, 10) - 1;
    if (mi < 0 || mi > 11) return iso;
    return months[mi] + " " + parseInt(d, 10) + ", " + y;
  }

  function fmtMonth(monthIso) {
    if (!monthIso) return "";
    var parts = monthIso.split("-");
    if (parts.length < 2) return monthIso;
    var y = parts[0], m = parts[1];
    var months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    var mi = parseInt(m, 10) - 1;
    if (mi < 0 || mi > 11) return monthIso;
    return months[mi] + " " + y;
  }

  function parseIsoToMs(iso) {
    if (!iso || iso === "CURRENT") return null;
    var parts = iso.split("-");
    if (parts.length !== 3) return null;
    var y = parseInt(parts[0], 10), m = parseInt(parts[1], 10), d = parseInt(parts[2], 10);
    if (isNaN(y) || isNaN(m) || isNaN(d)) return null;
    return Date.UTC(y, m - 1, d);
  }

  function diffYearsMonths(fromIsoLater, toIsoEarlier) {
    // Returns "X years Y months" from earlier to later
    var laterMs = parseIsoToMs(fromIsoLater);
    var earlierMs = parseIsoToMs(toIsoEarlier);
    if (laterMs == null || earlierMs == null) return null;
    var laterD = new Date(laterMs), earlierD = new Date(earlierMs);
    var years = laterD.getUTCFullYear() - earlierD.getUTCFullYear();
    var months = laterD.getUTCMonth() - earlierD.getUTCMonth();
    if (laterD.getUTCDate() < earlierD.getUTCDate()) months -= 1;
    if (months < 0) { years -= 1; months += 12; }
    if (years < 0) return { years: 0, months: 0, negative: true };
    return { years: years, months: months, negative: false };
  }

  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function extLink(url, text) {
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(text) + '</a>';
  }

  // Display label for a country of chargeability. ROW spells out; every other
  // country (India, China, Mexico, Philippines) passes through as its own name.
  function countryLabel(c) {
    return c === "ROW" ? "Rest of World" : c;
  }

  // Rank a Final Action Date value so that MORE CURRENT = HIGHER, per INA §202(b)
  // comparison rules: "CURRENT" is the most advanced, null (Unavailable) is the
  // most retrogressed, and an ISO date compares chronologically (later = better).
  function fadRank(v) {
    if (v === "CURRENT") return Infinity;
    if (v == null) return -Infinity;
    var ms = parseIsoToMs(v);
    return ms == null ? -Infinity : ms;
  }

  // Human-readable label for a Final Action Date value.
  function fadLabel(v) {
    if (v === "CURRENT") return "Current";
    if (v == null) return "Unavailable";
    return fmtDate(v);
  }

  // ---- Data-freshness + confidence helpers ----

  // Classify the confidence tier of a bulletin cell. Reads the status_note for
  // explicit cues ("tier-1", "medium", "single-source"), else falls back to the
  // `verified` flag. Returns one of: "unverified" | "aggregator" | "verified".
  // Leans honest: the whole dataset was capped at medium confidence because
  // travel.state.gov was blocked, so a cell with verified !== false is labelled
  // "Aggregator-sourced" (neutral) rather than a strong "Verified".
  function confidenceTier(cell) {
    if (!cell) return "aggregator";
    var note = (cell.status_note || "").toLowerCase();
    // Explicit unverified flag always wins.
    if (cell.verified === false) return "unverified";
    // tier-1 = independently confirmed against a primary source.
    if (note.indexOf("tier-1") !== -1) return "verified";
    // Weak-signal cues downgrade even when `verified` is absent.
    if (note.indexOf("single-source") !== -1) return "unverified";
    // Default for the tier-2 / medium-confidence aggregator dataset.
    return "aggregator";
  }

  // Render a small inline confidence badge (+ subtext) for a bulletin cell.
  function confidenceBadge(cell) {
    var tier = confidenceTier(cell);
    var label, note, cls;
    if (tier === "unverified") {
      cls = "conf-unverified";
      label = "Unverified";
      note = "Not independently verified. Sourced from law-firm aggregators, confirm against travel.state.gov.";
    } else if (tier === "verified") {
      cls = "conf-verified";
      label = "Confirmed (tier-1)";
      note = "Confirmed against a primary source (e.g. flag.dol.gov).";
    } else {
      cls = "conf-aggregator";
      label = "Aggregator-sourced";
      note = "Medium confidence. Cross-checked across law-firm aggregators, not confirmed against travel.state.gov.";
    }
    return '<div class="conf-badge-row">' +
      '<span class="conf-badge ' + cls + '">' + esc(label) + '</span>' +
      '<span class="conf-badge-note">' + esc(note) + '</span>' +
      '</div>';
  }

  // Parse an "as_of" month string (e.g. "2026-08") into {y, m} integers.
  function parseAsOfMonth(s) {
    if (!s) return null;
    var parts = String(s).split("-");
    if (parts.length < 2) return null;
    var y = parseInt(parts[0], 10), m = parseInt(parts[1], 10);
    if (isNaN(y) || isNaN(m)) return null;
    return { y: y, m: m };
  }

  // Stale-data guard: compare bulletin.as_of month against the month of
  // meta.last_verified. If the bulletin is more than ~2 months behind the last
  // verification, the underlying visa bulletin may have been re-published since.
  // Derived entirely from rulebook fields — no hardcoded "today".
  function isBulletinStale() {
    var asOf = parseAsOfMonth(rulebook.bulletin && rulebook.bulletin.as_of);
    var lv = parseAsOfMonth(rulebook.meta && rulebook.meta.last_verified);
    if (!asOf || !lv) return false;
    var monthsBehind = (lv.y - asOf.y) * 12 + (lv.m - asOf.m);
    return monthsBehind > 2;
  }

  // A quiet provenance footnote for an ACTUAL government cutoff number: which
  // Visa Bulletin it came from and when it was last verified. Reads only rulebook
  // meta/bulletin fields. If a specific category cell carries its own (older)
  // as_of, that month is preferred. The full provenance string is on hover. Must
  // NOT be attached to the projected scenario years — those are not government
  // data (see the "Historical-pace scenario" framing).
  function sourceStamp(cell) {
    var vb = fmtMonth(rulebook.bulletin && rulebook.bulletin.as_of);
    if (cell && cell.as_of) vb = fmtMonth(cell.as_of);
    var verified = rulebook.meta && rulebook.meta.last_verified;
    var src = (rulebook.meta && rulebook.meta.bulletin_verified_source) || "";
    return '<span class="source-stamp" title="' + esc(src) + '">' +
      'Source: ' + esc(vb) + ' Visa Bulletin &middot; verified ' + esc(fmtDate(verified)) + '</span>';
  }

  // ---- Radio card wiring ----
  function wireRadioCards(container, name, onSelect) {
    var cards = container.querySelectorAll(".radio-card:not(.disabled)");
    cards.forEach(function (card) {
      card.addEventListener("click", function () {
        var val = card.getAttribute("data-value");
        cards.forEach(function (c) { c.classList.remove("selected"); });
        card.classList.add("selected");
        var input = card.querySelector("input");
        if (input) input.checked = true;
        onSelect(val);
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); card.click(); }
      });
    });
  }

  // ---- Start ----
  if (startBtn) startBtn.addEventListener("click", function () {
    landing.classList.add("hidden");
    reveal(stepCategory);
    stepCategory.querySelector(".radio-card:not(.disabled)").focus();
    showReset();
    if (window.GCN_track) window.GCN_track("status-started");
  });

  // ---- Category-switch handling: keep cross-category answers, re-require
  //      category-specific ones, and never show stale results. ----
  function updatePdHelp(cat) {
    var pdHelp = document.getElementById("pd-help-text");
    if (!pdHelp) return;
    if (cat === "EB-1") {
      pdHelp.textContent = "For EB-1, your priority date is the day USCIS received your I-140 petition. There is no labor certification step. No petition yet? Enter today's date for an illustrative “if filed today” scenario.";
    } else if (cat === "EB-2") {
      pdHelp.textContent = "For a PERM-based EB-2, your priority date is the day the Department of Labor received your ETA-9089 labor certification. For an EB-2 National Interest Waiver, it is the day USCIS received your I-140 (no labor certification). No date yet? Enter today's date for an illustrative “if filed today” scenario.";
    } else {
      pdHelp.textContent = "Your priority date is the day the Department of Labor received your ETA-9089 labor certification. No date yet? Enter today's date for an illustrative “if filed today” scenario.";
    }
  }

  // Category-aware I-140 helper, mirroring updatePdHelp: EB-1 (and EB-2 NIW)
  // can self-petition with no PERM, so the "comes after PERM approval" framing
  // only fits standard employer-sponsored EB-2/EB-3.
  function updateI140Help(cat) {
    var el = document.getElementById("i140-help-text");
    if (!el) return;
    if (cat === "EB-1") {
      el.textContent = "Your immigrant petition. EB-1 categories (including EB-1A) can be self-petitioned and do not require PERM, so there is no PERM step before it.";
    } else if (cat === "EB-2") {
      el.textContent = "Your employer's immigrant petition, generally filed after PERM approval. The EB-2 National Interest Waiver is the exception: it is self-petitioned and needs no PERM.";
    } else {
      el.textContent = "Your employer's immigrant petition, generally filed after PERM approval.";
    }
  }

  function clearStepSelection(container, key) {
    if (container) {
      container.querySelectorAll(".radio-card").forEach(function (c) { c.classList.remove("selected"); });
      container.querySelectorAll("input[type='radio']").forEach(function (r) { r.checked = false; });
    }
    if (key) state[key] = null;
  }

  // Hide the results panel and clear its contents, forcing a fresh
  // "See my position" click before any new output appears.
  function clearResults() {
    hide(stepResult);
    if (resultContent) resultContent.innerHTML = "";
    submitError.classList.remove("visible");
    // A pasted bulletin is parsed for a specific category+country; a category or
    // country switch invalidates it. Drop the session overrides so the next
    // result starts from the built-in rulebook data.
    state.bulletinOverride = null;
    state.consular = null;
    state.ivSchedule = null;
  }

  // Drop answers that no longer apply to the new category. Cross-category
  // answers (country, level, spouse, degree, location) are preserved.
  function resetCategorySpecificAnswers(prevCat, newCat) {
    // Priority date is shared across EB-1/EB-2/EB-3, but F-1 auto-sets it to
    // today. Reset it when crossing the F-1 boundary in either direction so an
    // EB switch re-requires a real priority date and an F-1 switch re-defaults.
    // F-1 and PRE (H-1B/L-1 pre-PERM) are "no priority date" paths (pd auto-set
    // to today). Reset pd when crossing that boundary so an EB switch re-requires
    // a real priority date and a no-pd switch re-defaults it.
    var noPd = function (c) { return c === "F-1" || c === "PRE"; };
    if (noPd(prevCat) !== noPd(newCat)) {
      state.pd = null;
      if (pdInput) pdInput.value = "";
      pdError.classList.remove("visible");
    }
    // PERM applies only to EB-2 / EB-3.
    if (newCat === "EB-1" || newCat === "F-1" || newCat === "PRE") {
      clearStepSelection(stepPerm, "perm");
    }
    // EB-1 sub-category applies only to EB-1.
    if (newCat !== "EB-1") {
      clearStepSelection(stepEb1Sub, "eb1sub");
    }
    // I-140 and H-1B year do not apply to F-1 or PRE.
    if (newCat === "F-1" || newCat === "PRE") {
      clearStepSelection(stepI140, "i140");
      clearStepSelection(stepH1b, "h1b");
    }
    // F-1 OPT fields apply only to F-1.
    if (newCat !== "F-1") {
      clearStepSelection(stepF1Opt, "h1bLottery");
      state.optExpiry = null;
      if (optExpiryInput) optExpiryInput.value = "";
    }
    // Pre-PERM visa/year/intent apply only to PRE.
    if (newCat !== "PRE" && stepPre) {
      clearStepSelection(stepPre, "preVisa");
      state.preYear = null;
      state.preIntent = null;
      stepPre.querySelectorAll(".radio-card").forEach(function (c) { c.classList.remove("selected"); });
      stepPre.querySelectorAll("input[type='radio']").forEach(function (r) { r.checked = false; });
    }
  }

  // Single source of truth for which steps are visible. Purely state-driven and
  // IDEMPOTENT: given the current state it always shows exactly the right steps
  // and reveals downstream steps once their prerequisites are met. Called after
  // every interaction so no toggle sequence can strand the form with the later
  // steps / submit hidden. Reveals progressively (a step appears only once the
  // prior required answer exists), matching the original one-at-a-time flow.
  // Are all REQUIRED answers present for the current category? Mirrors the submit
  // handler's gate: category + country, plus EB-1 sub / PRE visa+intent / a valid
  // priority date for EB. Drives the "instant answer after 3 questions".
  function requiredComplete() {
    if (!state.category || !state.country) return false;
    // Work visa is now a required 4th question: at least one selection (a real
    // visa or the explicit "None of these").
    if (!state.workVisa || !state.workVisa.length) return false;
    if (state.category === "EB-1" && !state.eb1sub) return false;
    if (state.category === "PRE" && (!state.preVisa || !state.preIntent)) return false;
    if (state.category !== "F-1" && state.category !== "PRE") {
      if (!state.pd || !/^\d{4}-\d{2}-\d{2}$/.test(state.pd)) return false;
    }
    return true;
  }

  // Render the result as soon as the required answers exist, and keep it in sync
  // as optional details change. Scrolls to the result only the FIRST time it
  // appears, so refining an optional answer updates in place without yanking the
  // viewport. Optional questions live in the collapsed expander below the result.
  // Fire the "result-viewed" analytics event once, when the result actually
  // scrolls into view (covers both the "Jump to your result" link and manual
  // scrolling). Anonymous event only. No-ops without IntersectionObserver.
  var resultViewTracked = false;
  function observeResultView() {
    if (resultViewTracked || !stepResult || !("IntersectionObserver" in window)) return;
    var io = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting && !resultViewTracked) {
          resultViewTracked = true;
          if (window.GCN_track) window.GCN_track("result-viewed");
          io.disconnect();
        }
      }
    }, { threshold: 0 });  // #step-result is very tall; fire as soon as it enters view
    io.observe(stepResult);
  }

  function maybeAutoRender(allowScroll) {
    if (!requiredComplete()) return;
    var firstTime = !stepResult.classList.contains("visible");
    submitError.classList.remove("visible");
    renderResult();
    reveal(stepResult);
    showReset();
    // When the required answers first land, carry the user to the "Optional:
    // sharpen your estimate" section (the natural next step), NOT to the result.
    // This keeps the last required question consistent with the others (each one
    // auto-advances) while still not skipping the optional questions — the refine
    // block is where they live, and its "Jump to your result" link goes the rest
    // of the way when the user is ready. Only on the first completion, so editing
    // an answer later updates the result in place without yanking the viewport.
    if (allowScroll && firstTime && refineBlock && refineBlock.classList.contains("visible")) {
      scrollToStepWhenSettled(refineBlock);
    }
    // Analytics: fire once when the required answers first produce a result, and
    // start watching for the user actually reaching the result. Anonymous event
    // names only — no case values are ever attached.
    if (firstTime) {
      if (window.GCN_track) window.GCN_track("status-completed");
      observeResultView();
    }
  }

  // Ordered list (document order) of the progressive question steps the mobile
  // auto-scroll may carry the user to. Excludes the result panel, which owns its
  // own scroll via maybeAutoRender().
  var scrollableSteps = [
    stepCategory, stepEb1Sub, stepWorkvisa, stepCountry, stepPd, stepF1Opt, stepPre,
    stepRoleChange, stepH1b, stepPerm, stepI140, stepSpouse, stepDegree,
    stepLocation, stepSubmit
  ];

  function isPhoneViewport() {
    return !!(window.matchMedia && window.matchMedia("(max-width: 767px)").matches);
  }
  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  function snapshotStepVisibility() {
    // Records which candidate steps are visible right now, keyed by index into
    // scrollableSteps. Used to diff before/after a syncReveal pass.
    var vis = [];
    for (var i = 0; i < scrollableSteps.length; i++) {
      var el = scrollableSteps[i];
      vis[i] = !!(el && el.classList.contains("visible"));
    }
    return vis;
  }

  // Public entry point used by every selection/change handler. Snapshots step
  // visibility, re-derives the form (syncRevealCore), then smoothly scrolls to the
  // FIRST step that transitioned hidden->visible during this pass, so the user is
  // carried to the question that just appeared. Enabled on all viewports.
  //
  // Suppression rules:
  //  - Initial/default/restored state: steps already visible when the pass began
  //    are never scrolled to (they aren't "newly revealed this pass"). Because
  //    syncReveal only ever runs from a user action in this build, this per-pass
  //    diff is what keeps auto-scroll from firing on load; there is no separate
  //    load-time syncReveal to guard.
  //  - Result completion: when the required questions finish, syncRevealCore
  //    reveals the whole optional block AND the result at once, and
  //    maybeAutoRender already smooth-scrolls to the result the first time. In
  //    that pass we defer to that scroll and skip our own, so the existing
  //    scroll-to-result behavior is undisturbed.
  function syncReveal(skipRevealScroll) {
    var before = snapshotStepVisibility();
    var resultWasVisible = stepResult.classList.contains("visible");
    syncRevealCore();
    // Detail-step handlers pass true and own their own "advance to the next
    // question" scroll (scrollToNextStepAfter), so we don't double-scroll.
    if (!skipRevealScroll) autoScrollToRevealedStep(before, resultWasVisible);
  }

  function autoScrollToRevealedStep(before, resultWasVisible) {
    // The result just appeared for the first time this pass -> maybeAutoRender()
    // owns the scroll. Don't fight it.
    if (!resultWasVisible && stepResult.classList.contains("visible")) return;
    var firstNew = null;
    for (var i = 0; i < scrollableSteps.length; i++) {
      var el = scrollableSteps[i];
      if (el && el.classList.contains("visible") && !before[i]) { firstNew = el; break; }
    }
    if (!firstNew || !firstNew.scrollIntoView) return;
    // BUG FIX: a revealed .step animates open over 0.4s (max-height transition,
    // styles.css). Scrolling immediately aligns to a ~2px-tall element and
    // mis-lands. Wait for the
    // max-height transition to finish (with a timeout fallback), THEN scroll to
    // the fully-expanded element.
    scrollToStepWhenSettled(firstNew);
  }

  function scrollToStepWhenSettled(el) {
    var behavior = prefersReducedMotion() ? "auto" : "smooth";
    var done = false;
    function go() {
      if (done) return;
      done = true;
      el.removeEventListener("transitionend", onEnd);
      el.scrollIntoView({ behavior: behavior, block: "start" });
    }
    function onEnd(e) { if (e.propertyName === "max-height") go(); }
    el.addEventListener("transitionend", onEnd);
    setTimeout(go, 480);  // fallback > the 0.4s transition (and covers no-transition cases)
  }

  // After answering an OPTIONAL detail question, carry the user down to the next
  // question. The optional steps are all revealed at once when the 3 required
  // answers are in, so answering one reveals nothing new — meaning
  // autoScrollToRevealedStep has nothing to scroll to. This advances the user
  // through the optional cluster instead: each optional answer -> next
  // question. Uses
  // DOM order so it is robust to the scrollableSteps array vs visual order.
  // Enabled on all viewports (web too — user asked for it).
  function scrollToNextStepAfter(container) {
    if (!container) return;
    var next = null, nearest = Infinity;
    for (var i = 0; i < scrollableSteps.length; i++) {
      var el = scrollableSteps[i];
      // Skip the submit button as a landing target — the result below is the real
      // payoff, so the last optional question should advance straight to it.
      if (!el || el === container || el === stepSubmit || !el.classList.contains("visible")) continue;
      if (!(container.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      var top = el.getBoundingClientRect().top;      // nearest visible step below this one
      if (top < nearest) { nearest = top; next = el; }
    }
    // Fall through to the result once the last optional question is answered.
    if (!next && stepResult && stepResult.classList.contains("visible")) next = stepResult;
    if (next) scrollToStepWhenSettled(next);
  }

  function syncRevealCore() {
    var cat = state.category;
    if (!cat) return;

    // --- Step 1 continued: EB-1 sub-category sits between category and work visa ---
    if (cat === "EB-1") { reveal(stepEb1Sub); } else { hide(stepEb1Sub); }

    // --- Step 2: work visa (required). Shown once a category is chosen; gates the
    //     rest until at least one option is picked. ---
    reveal(stepWorkvisa);
    if (!state.workVisa || !state.workVisa.length) return;

    // --- Step 3: country ---
    reveal(stepCountry);
    if (state.country == null) return;  // don't reveal step 4+ until country picked

    // --- Step 3: category-appropriate third question ---
    if (cat === "F-1") {
      hide(stepPd); hide(stepPerm); hide(stepI140); hide(stepH1b); hide(stepPre);
      reveal(stepF1Opt);
      if (!state.pd) state.pd = new Date().toISOString().slice(0, 10);
    } else if (cat === "PRE") {
      hide(stepPd); hide(stepPerm); hide(stepI140); hide(stepH1b); hide(stepF1Opt);
      reveal(stepPre);
      if (!state.pd) state.pd = new Date().toISOString().slice(0, 10);
    } else {
      hide(stepF1Opt); hide(stepPre);
      reveal(stepPd);
    }

    // --- Steps 4-10 + submit: revealed once step 3's requirement is satisfied.
    //     F-1 and PRE have no priority date (auto-set), so country is enough; EB
    //     needs a valid priority date. ---
    var noPd = (cat === "F-1" || cat === "PRE");
    var ready = noPd
      ? true
      : (state.pd && /^\d{4}-\d{2}-\d{2}$/.test(state.pd));
    if (!ready) return;

    // Role change is a single standalone optional question - nothing gates it.
    // OPTIONAL: it never touches requiredComplete() or the required-question gate.
    if (stepRoleChange) reveal(stepRoleChange);
    if (cat !== "F-1" && cat !== "PRE") {
      reveal(stepH1b);
      reveal(stepI140);
      if (cat === "EB-1") { hide(stepPerm); } else { reveal(stepPerm); }
    }
    reveal(stepSpouse);
    reveal(stepDegree);
    reveal(stepLocation);
    reveal(stepSubmit);
    if (refineBlock) reveal(refineBlock);
    // Once the 3 required answers are in, show the result immediately.
    maybeAutoRender(true);
  }

  if (stepCategory) wireRadioCards(stepCategory, "category", function (val) {
    var prev = state.category;
    var changed = (prev !== null && prev !== val);
    state.category = val;
    updatePdHelp(val);
    updateI140Help(val);
    if (changed) {
      // A category switch invalidates any shown result and any answers that
      // don't carry across. Clear both, then re-shape the form.
      clearResults();
      resetCategorySpecificAnswers(prev, val);
    }
    // Re-derive the entire step visibility from state. Idempotent, so it works
    // for the first selection, a mid-form switch, and a post-result switch alike.
    // Allow auto-scroll: work visa is now its own step (Question 2), so carry the
    // user to the next question (EB-1 sub-category for EB-1, otherwise work visa).
    syncReveal();
    showReset();
  });

  if (stepCountry) wireRadioCards(stepCountry, "country", function (val) {
    state.country = val;
    syncReveal();
    showReset();
  });

  // ---- Detail radio wiring (steps 4-9) ----
  function wireDetailStep(container) {
    var cards = container.querySelectorAll(".radio-card");
    cards.forEach(function (card) {
      card.addEventListener("click", function () {
        var key = card.getAttribute("data-detail");
        var val = card.getAttribute("data-value");
        container.querySelectorAll('.radio-card[data-detail="' + key + '"]').forEach(function (c) {
          c.classList.remove("selected");
        });
        card.classList.add("selected");
        var input = card.querySelector("input");
        if (input) input.checked = true;
        state[key] = val;
        // Re-derive step visibility and refresh the live result in place, then
        // (phone only) carry the user down to the next optional question.
        syncReveal(true);
        scrollToNextStepAfter(container);
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); card.click(); }
      });
    });
  }
  optionalSteps.filter(Boolean).forEach(wireDetailStep);

  // Pre-select a neutral "Prefer not to say" default on the optional detail steps
  // so they never look unanswered/required (feedback: they "didn't feel
  // intuitive" when blank). Each of these values is treated identically to null
  // by the result logic (see hubAnswered: value != null && != "skip"), so this
  // changes NOTHING in the computed result — it's purely a friendlier default
  // state. `roleChange` is a standalone optional question (
  // answer is "Yes", where a real pick is expected).
  var OPTIONAL_DEFAULTS = {
    roleChange: "skip", h1b: "skip", perm: "skip",
    i140: "skip", spouse: "skip", degree: "skip"
  };
  function applyOptionalDefaults() {
    Object.keys(OPTIONAL_DEFAULTS).forEach(function (key) {
      var val = OPTIONAL_DEFAULTS[key];
      state[key] = val;
      var cards = document.querySelectorAll('.radio-card[data-detail="' + key + '"]');
      cards.forEach(function (c) {
        var on = c.getAttribute("data-value") === val;
        c.classList.toggle("selected", on);
        var inp = c.querySelector("input");
        if (inp) inp.checked = on;
      });
    });
  }
  applyOptionalDefaults();

  // ---- Multi-select wiring (non-exclusive facets, e.g. current work visa) ----
  // Array-toggle variant of wireDetailStep: toggles membership in state[key]
  // (an array) instead of overwriting a scalar, and honors a "None" option that
  // is mutually exclusive with the rest. Calls syncReveal() on every change,
  // exactly like every other control, so progressive reveal + live re-render
  // keep working with zero changes to syncRevealCore. It is OPTIONAL — nothing
  // here touches requiredComplete() or the 3-required-question gate.
  function wireMultiSelect(container, key) {
    if (!container) return;
    if (!Array.isArray(state[key])) state[key] = [];
    var chips = container.querySelectorAll('.workvisa-chip[data-multi="' + key + '"]');
    function syncChipUi() {
      chips.forEach(function (chip) {
        var v = chip.getAttribute("data-value");
        var on = state[key].indexOf(v) !== -1;
        chip.classList.toggle("selected", on);
        var input = chip.querySelector("input");
        if (input) input.checked = on;
      });
    }
    chips.forEach(function (chip) {
      function toggle() {
        var val = chip.getAttribute("data-value");
        var arr = state[key];
        var idx = arr.indexOf(val);
        var isNone = (val === "None");
        if (idx !== -1) {
          arr.splice(idx, 1); // toggle off
        } else if (isNone) {
          state[key] = ["None"]; // "None" clears everything else
        } else {
          // Selecting a real visa clears a prior "None".
          arr = arr.filter(function (x) { return x !== "None"; });
          arr.push(val);
          state[key] = arr;
        }
        syncChipUi();
        // Allow auto-scroll. The FIRST selection reveals the country step (newly),
        // so autoScrollToRevealedStep carries the user there. Later toggles reveal
        // nothing new (country already visible), so they don't yank the viewport —
        // the user can keep multi-selecting in place.
        syncReveal();
      }
      chip.addEventListener("click", function (e) {
        // The label wraps a checkbox; let our handler own the state so a native
        // label-click doesn't double-toggle. Prevent default, drive manually.
        e.preventDefault();
        toggle();
      });
      chip.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      });
    });
    syncChipUi();
  }
  if (stepWorkvisa) wireMultiSelect(stepWorkvisa, "workVisa");

  // Wire F-1 OPT step radio cards
  if (stepF1Opt) wireDetailStep(stepF1Opt);
  // Wire EB-1 sub-category step radio cards
  if (stepEb1Sub) wireDetailStep(stepEb1Sub);
  // Wire H-1B/L-1 pre-PERM step radio cards
  if (stepPre) wireDetailStep(stepPre);
  // Capture OPT expiry on input
  if (optExpiryInput) {
    optExpiryInput.addEventListener("change", function () {
      state.optExpiry = optExpiryInput.value || null;
      syncReveal();
    });
  }

  // ---- Populate location dropdowns from rulebook ----
  function populateLocationDropdowns() {
    if (!rulebook.locations || !rulebook.locations.metros) return;
    var metros = rulebook.locations.metros;
    // Current: no default selection
    metros.forEach(function (m) {
      var opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.label;
      locCurrentSelect.appendChild(opt);
    });
    // Prospective: already has "No move under consideration" as default
    metros.forEach(function (m) {
      var opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.label;
      locProspectiveSelect.appendChild(opt);
    });
  }
  if (locCurrentSelect && locProspectiveSelect) populateLocationDropdowns();

  if (locCurrentSelect) locCurrentSelect.addEventListener("change", function () {
    state.locCurrent = locCurrentSelect.value || null;
    syncReveal();
  });
  if (locProspectiveSelect) locProspectiveSelect.addEventListener("change", function () {
    var v = locProspectiveSelect.value;
    state.locProspective = (v && v !== "__none__") ? v : null;
    // This is the last field of the last optional step — advance to the result
    // (phone only). The current-location <select> above does NOT advance, so the
    // user can still set this prospective field before being carried down.
    syncReveal(true);
    scrollToNextStepAfter(stepLocation);
  });

  function findMetro(id) {
    if (!id || !rulebook.locations || !rulebook.locations.metros) return null;
    for (var i = 0; i < rulebook.locations.metros.length; i++) {
      if (rulebook.locations.metros[i].id === id) return rulebook.locations.metros[i];
    }
    return null;
  }

  function validatePd() {
    var val = pdInput.value;
    if (!val || !/^\d{4}-\d{2}-\d{2}$/.test(val)) {
      pdError.classList.add("visible");
      pdInput.focus();
      return null;
    }
    var d = new Date(val);
    if (isNaN(d.getTime())) {
      pdError.classList.add("visible");
      pdInput.focus();
      return null;
    }
    pdError.classList.remove("visible");
    return val;
  }

  function onPdEntered() {
    var val = pdInput.value;
    if (val && /^\d{4}-\d{2}-\d{2}$/.test(val)) {
      var d = new Date(val);
      if (!isNaN(d.getTime())) {
        state.pd = val;
        syncReveal();
      }
    }
  }
  if (pdInput) pdInput.addEventListener("input", function () {
    pdError.classList.remove("visible");
    onPdEntered();
  });
  if (pdInput) pdInput.addEventListener("change", onPdEntered);

  // ---- Submit (unified) ----
  var submitErrorDefault = submitError ? submitError.textContent : "";
  if (submitBtn) submitBtn.addEventListener("click", function () {
    // Reset to the default message; the EB-1 branch overrides it when needed.
    submitError.textContent = submitErrorDefault;
    if (!state.category || !state.country) {
      submitError.classList.add("visible");
      if (!state.category) {
        stepCategory.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        stepCountry.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }
    // EB-1 requires the sub-category (A/B/C or "not sure") before we can render.
    if (state.category === "EB-1" && !state.eb1sub) {
      submitError.textContent = "Please pick your EB-1 sub-category (Step 1 continued) before continuing.";
      submitError.classList.add("visible");
      stepEb1Sub.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    // PRE (H-1B/L-1, PERM not started) requires the visa type and intended EB
    // category before we can build the plan.
    if (state.category === "PRE" && (!state.preVisa || !state.preIntent)) {
      submitError.textContent = "Please pick your current visa and intended EB category (Step 3) before continuing.";
      submitError.classList.add("visible");
      stepPre.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    // F-1 and PRE users don't need a priority date — state.pd is auto-set to today.
    if (state.category !== "F-1" && state.category !== "PRE") {
      var val = validatePd();
      if (!val) {
        submitError.classList.add("visible");
        stepPd.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      state.pd = val;
    }
    // Capture OPT expiry for F-1
    if (state.category === "F-1" && optExpiryInput && optExpiryInput.value) {
      state.optExpiry = optExpiryInput.value;
    }
    submitError.classList.remove("visible");
    renderResult();
    reveal(stepResult);
    stepResult.scrollIntoView({ behavior: "smooth", block: "start" });
    showReset();
  });

  // ---- Reset ----
  function resetAll() {
    state = {
      category: null, country: null, pd: null,
      level: null, h1b: null, perm: null, i140: null, spouse: null, degree: null,
      locCurrent: null, locProspective: null,
      optExpiry: null, h1bLottery: null, eb1sub: null, roleChange: null,
      preVisa: null, preYear: null, preIntent: null,
      workVisa: [],
      bulletinOverride: null, consular: null, ivSchedule: null
    };
    // Clear the non-exclusive work-visa chips (checkboxes + selected state).
    document.querySelectorAll('.workvisa-chip').forEach(function (c) { c.classList.remove("selected"); });
    document.querySelectorAll('.workvisa-chip input[type="checkbox"]').forEach(function (cb) { cb.checked = false; });
    pdInput.value = "";
    pdError.classList.remove("visible");
    submitError.classList.remove("visible");
    document.querySelectorAll(".radio-card").forEach(function (c) { c.classList.remove("selected"); });
    document.querySelectorAll("input[type='radio']").forEach(function (r) { r.checked = false; });
    applyOptionalDefaults();  // re-pre-select the neutral "Prefer not to say" defaults
    if (locCurrentSelect) locCurrentSelect.value = "";
    if (locProspectiveSelect) locProspectiveSelect.value = "__none__";
    hide(stepCategory);
    hide(stepEb1Sub);
    hide(stepCountry);
    hide(stepPd);
    hide(stepF1Opt);
    hide(stepPre);
    hide(stepRoleChange);
    hide(stepH1b);
    hide(stepPerm);
    hide(stepI140);
    hide(stepSpouse);
    hide(stepDegree);
    hide(stepLocation);
    hide(stepSubmit);
    hide(stepResult);
    if (refineBlock) hide(refineBlock);
    landing.classList.remove("hidden");
    if (resetBtn) resetBtn.classList.remove("visible");
    resultContent.innerHTML = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  if (resetBtn) resetBtn.addEventListener("click", resetAll);

  // ---- "Clear my data" (privacy control on the landing screen) ----
  // Wipes the small preference keys this site keeps on the device. Deliberately
  // does NOT touch gc_theme (a harmless UI preference the user set on purpose).
  // Each removal is guarded like the rest of the storage code.
  var clearDataBtn = document.getElementById("clearDataBtn");
  var clearDataNote = document.getElementById("clearDataNote");
  if (clearDataBtn) clearDataBtn.addEventListener("click", function () {
    if (!window.confirm("Clear the small settings this site keeps in your browser on this device (guided-tour, bulletin-memory, and H-1B checklist progress)? Your color-theme choice is kept. This cannot be undone.")) return;
    ["gc_tour_seen", "gc_tour_optout", "gc_remember_bulletins", "gc_vb_history", "gc_h1b_checklist"].forEach(function (k) {
      try { localStorage.removeItem(k); } catch (e) {}
    });
    if (clearDataNote) {
      clearDataNote.textContent = "Cleared. Nothing this site stored on your browser remains, aside from your color-theme choice.";
      clearDataNote.classList.add("visible");
    }
  });

  // ---- Detail enrichment builders ----
  // "Answered" = user picked something other than skip / prefer-not-to-say
  function hasDetail(key) {
    return state[key] != null && state[key] !== "skip" && state[key] !== "not-h1b" && state[key] !== "not-married";
  }
  function hasDetailIncl(key) {
    // Includes "not-h1b" / "not-married" as an answered value where useful
    return state[key] != null && state[key] !== "skip";
  }

  function capTimingBlock() {
    if (!hasDetailIncl("h1b")) return "";
    var v = state.h1b;
    var msg = "";
    if (v === "1" || v === "2") {
      msg = "You have runway. PERM needs to be filed before Year 5 to guarantee §106(a) coverage before the Year 6 cap.";
    } else if (v === "3" || v === "4") {
      msg = "This is the optimal filing window. Confirm PERM is in progress.";
    } else if (v === "5") {
      msg = "Time-sensitive. §106(a) unlocks approximately one year after ETA 9089 filing. The clock matters.";
    } else if (v === "6") {
      var hasProtect = (state.perm === "filed" || state.perm === "audited" || state.perm === "approved") ||
                      (state.i140 === "pending-regular" || state.i140 === "pending-premium" || state.i140 === "approved");
      if (hasProtect) {
        msg = "Year 6 with PERM or I-140 in the pipeline. §106(a) or §104(c) is likely already available or imminent. Confirm status with your immigration attorney.";
      } else {
        msg = "Immediate risk. H-1B expires before extension protection kicks in. Escalate with your immigration attorney now.";
      }
    } else if (v === "106a") {
      msg = "Extended in 1-year increments. Continue extending until I-140 approves; then §104(c) takes over with 3-year increments.";
    } else if (v === "104c") {
      msg = "Extended in 3-year increments. Priority date is portable if you change employers.";
    } else if (v === "not-h1b") {
      msg = "Not on H-1B. AC21 cap-extension rules do not apply to your case; the priority date logic still does.";
    }
    if (!msg) return "";
    return '<div class="enrichment"><div class="head">Cap timing</div>' + esc(msg) + '</div>';
  }

  function permStageBlock() {
    if (!hasDetail("perm")) return "";
    var v = state.perm;
    var msg = "";
    if (v === "not-filed") msg = "PERM has not been filed. Your priority date has not been locked. Every day of delay is a day added to the wait.";
    else if (v === "pwd") msg = "PWD is in flight (typically 4-5 month DOL turnaround). ETA 9089 cannot be filed until PWD is issued.";
    else if (v === "lmt") msg = "Labor market test is running (typically 2-3 months). ETA 9089 filing comes after this closes.";
    else if (v === "filed") msg = "Priority date is LOCKED as of the filing date. Approval takes ~13 months. §106(a) unlocks approximately one year after this date.";
    else if (v === "audited") msg = "Audit typically adds ~9 months to processing. Random or targeted. Priority date is preserved.";
    else if (v === "approved") msg = "PERM approved. I-140 is the next filing. §106(a) is already active if PERM was pending 365+ days.";
    else if (v === "denied") msg = "Denial can be appealed or the case refiled. Your immigration attorney drives the call. Priority date is lost on denial.";
    if (!msg) return "";
    return '<div class="enrichment"><div class="head">PERM stage</div>' + esc(msg) + '</div>';
  }

  // ---- Interactive queue projector ------------------------------------------
  // Drag the "You are here" marker to any hypothetical priority date and see the
  // projected I-140 / I-485 / green-card years update live. Where we have a MEASURED
  // pace (VB_PACE below, derived from 71 monthly Visa Bulletins Oct 2019-Aug 2026) we
  // use it and say so; elsewhere we fall back to a transparent assumption and label it.
  // Either way the UI carries a retrogression caveat — cutoffs stall and move backward.
  //
  // VB_PACE per "category|country": t/f/s = typical/fast/slow cutoff-years advanced per
  // calendar year (median/p75/p25 of month-over-month movement); mo = median
  // cutoff-months/yr; retro/unavail = counts of retrogression / Unavailable months over
  // the window; yrs = years of coverage; usable = enough consistent forward movement to
  // project from (only backlogged tiers with real movement — others fall back to the
  // assumption). Built by scripts from the checked-in vb_history.json.
  var VB_PACE = {"EB-1|China":{"usable":true,"mo":2.8,"retro":0,"unavail":0,"yrs":6.8,"t":0.23,"f":1.39,"s":0.05},"EB-2|China":{"usable":true,"mo":5.6,"retro":0,"unavail":0,"yrs":6.8,"t":0.46,"f":1.54,"s":0.05},"EB-2|India":{"usable":true,"mo":3.4,"retro":2,"unavail":2,"yrs":6.8,"t":0.28,"f":2.07,"s":0.05},"EB-3|China":{"usable":true,"mo":2.8,"retro":3,"unavail":0,"yrs":6.8,"t":0.23,"f":1.12,"s":0.05},"EB-3|India":{"usable":true,"mo":2.8,"retro":1,"unavail":0,"yrs":6.8,"t":0.23,"f":1.03,"s":0.05}};
  function qpClampPct(x) { return Math.max(0, Math.min(100, x)); }
  function qpYearFrac(ms) { var d = new Date(ms); return d.getFullYear() + d.getMonth() / 12; }
  function qpPaceStats(cat, country) {
    var m = VB_PACE[(cat || "") + "|" + (country || "")];
    return (m && m.usable) ? m : null;
  }
  function qpPaceBand(cat, country) {
    var m = qpPaceStats(cat, country);
    if (m) return { fast: m.f, typ: m.t, slow: m.s, measured: true };
    var backlogged = (country === "India") || (country === "China" && (cat === "EB-2" || cat === "EB-3"));
    var b = backlogged ? { fast: 0.7, typ: 0.45, slow: 0.2 } : { fast: 1.2, typ: 0.9, slow: 0.6 };
    b.measured = false;
    return b;
  }
  // ---- Queue depth from the USCIS I-485 inventory ---------------------------
  // A second, independent reading of "how long" that does not depend on cutoff
  // movement at all. VB_PACE above measures how fast the cutoff has travelled;
  // this measures how many people are physically standing in front of you. The
  // two answer different questions and can disagree, which is the point.
  //
  // Source: the monthly USCIS pending employment-based I-485 inventory, parsed by
  // automation/fetch_eb_inventory.py into eb_inventory.json. See that script for
  // the two parsing traps (per-sheet year labels, and "D" as a suppressed 1-10).
  //
  // THE SCOPE LIMIT IS LOAD-BEARING, so it is repeated in the UI every time a
  // number is shown: the inventory counts only applications ALREADY FILED. USCIS
  // excludes anyone holding a pending or approved I-140 who has not yet filed an
  // I-485, plus the State Department consular queue and everything still at DOL.
  // In a retrogressed category most of the real queue cannot file yet, so these
  // counts are a FLOOR on the people ahead of you and never a total. Nothing here
  // may be phrased as "the queue is N people long".
  var GCN_EB_INV = null;
  var gcnEbInvTried = false;

  function qpInvSeries(cat, country) {
    if (!GCN_EB_INV || !GCN_EB_INV.series) return null;
    return GCN_EB_INV.series[(cat || "") + "|" + (country || "")] || null;
  }

  // Applications already filed whose priority date is strictly earlier than pdIso.
  // Returns known totals plus the count of suppressed cells so the caller can show
  // a band rather than a falsely precise number.
  function qpInvAhead(series, pdIso) {
    var pd = String(pdIso || "");
    var ym = pd.slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(ym)) return null;
    var known = 0, dcells = 0, inYear = 0, inMonth = 0, later = 0;
    var yr = ym.slice(0, 4);
    // "Prior Years" is an open-ended bucket older than the workbook's window, so
    // everyone in it is unambiguously ahead of any date the axis can show.
    if (series.prior_years) {
      known += series.prior_years.known || 0;
      dcells += series.prior_years.suppressed_cells || 0;
    }
    for (var i = 0; i < series.cells.length; i++) {
      var c = series.cells[i];
      if (c.pd < ym) { known += c.n || 0; dcells += c.d || 0; }
      else if (c.pd === ym) { inMonth += c.n || 0; }
      else { later += c.n || 0; }
      if (c.pd.slice(0, 4) === yr) inYear += c.n || 0;
    }
    return { known: known, dcells: dcells, inMonth: inMonth, inYear: inYear,
             later: later, total: series.known || 0,
             pastWindow: series.cells.length ? (ym > series.cells[series.cells.length - 1].pd) : false };
  }

  function qpFmtN(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  // Hover definition using the site's one existing tooltip treatment (.gloss-tip:
  // dotted underline + native title). tabindex is set explicitly because glossify
  // only adds it to the anchors it creates itself, and a span is not focusable by
  // default — without it these are unreachable by keyboard.
  function qpTip(label, def) {
    return '<span class="gloss-tip" tabindex="0" title="' + esc(def) + '">' + label + '</span>';
  }

  // A suppressed cell hides a count of 1 to 10, so N known cells give a band of
  // known+N to known+10N. Only worth showing when the band is wide enough to matter.
  function qpInvBand(known, dcells) {
    if (!dcells) return qpFmtN(known);
    var lo = known + dcells, hi = known + dcells * 10;
    if (hi - lo < Math.max(50, known * 0.01)) return "about " + qpFmtN(known);
    return qpFmtN(lo) + "&ndash;" + qpFmtN(hi);
  }

  function qpInventoryHtml(pdIso, cat, country) {
    var s = qpInvSeries(cat, country);
    if (!s || !s.cells || !s.cells.length) return "";
    var a = qpInvAhead(s, pdIso);
    if (!a) return "";
    var asOf = (GCN_EB_INV && GCN_EB_INV.as_of) ? GCN_EB_INV.as_of : "";
    var catLbl = esc(cat || ""), ctryLbl = esc(countryLabel(country));

    var h = '<div class="qp-inv-head">Who is already in line ahead of that date' +
      (asOf ? ' <span class="qp-inv-asof">USCIS inventory, ' + esc(asOf) + '</span>' : '') + '</div>';

    // When the marker sits past the newest priority date anyone has managed to file
    // under, the whole filed inventory is ahead — and the more important fact is
    // that people at the marker's date have not been able to file at all yet.
    if (a.pastWindow) {
      h += '<div class="qp-inv-big">' + qpInvBand(a.known, a.dcells) +
        ' <span class="qp-inv-unit">I-485 applications already filed and waiting</span></div>';
      h += '<p class="qp-inv-p">That is <strong>every</strong> pending ' + catLbl + ' ' + ctryLbl +
        ' application in the USCIS inventory, because nobody with a priority date as recent as ' +
        esc(fmtDate(pdIso)) + ' has been able to file an I-485 yet. Those people are in the queue too, ' +
        'they are simply not counted here, which is why this figure is a floor and not the length of the line.</p>';
    } else {
      h += '<div class="qp-inv-big">' + qpInvBand(a.known, a.dcells) +
        ' <span class="qp-inv-unit">I-485 applications already filed with an earlier priority date</span></div>';
      h += '<p class="qp-inv-p">Each one has to be decided before a visa number reaches ' +
        esc(fmtDate(pdIso)) + '.' +
        (a.inYear ? ' Another <strong>' + qpFmtN(a.inYear) + '</strong> applications share that same priority-date year, so the cutoff has to grind through that cluster too.' : '') +
        '</p>';
    }

    // The densest single year is the most actionable thing in this dataset: it is
    // where the cutoff visibly stalls, and it is invisible in bulletin movement.
    var byYear = {}, i, y;
    for (i = 0; i < s.cells.length; i++) {
      y = s.cells[i].pd.slice(0, 4);
      byYear[y] = (byYear[y] || 0) + (s.cells[i].n || 0);
    }
    var peakY = null, peakN = 0;
    for (y in byYear) { if (byYear[y] > peakN) { peakN = byYear[y]; peakY = y; } }
    // Suppress when the marker already sits in the peak year: the sentence above
    // has just quoted this exact number, and repeating it reads like a bug.
    if (peakY === String(pdIso).slice(0, 4) && !a.pastWindow) peakY = null;
    if (peakY && peakN > 0) {
      h += '<p class="qp-inv-p qp-inv-peak">The heaviest pile-up is <strong>' + esc(peakY) +
        '</strong>, with <strong>' + qpFmtN(peakN) + '</strong> filed applications carrying a priority date in that one year' +
        (peakN >= 1000 ? '. A cutoff moving at a few months per year takes a long time to clear a cluster that size.' : '.') + '</p>';
    }

    h += '<p class="qp-inv-scope">' +
      qpTip("Counts filed applications only",
        "USCIS counts only people who have already filed Form I-485. It excludes anyone with a pending or approved I-140 who has not filed yet, the State Department consular queue, and every case still at the Department of Labor.") +
      ', so it is a floor on the number ahead of you rather than the length of the queue.' +
      (s.suppressed_cells ? ' USCIS publishes small counts as ' +
        qpTip("&ldquo;D&rdquo;", "A suppressed count. USCIS prints D instead of a number when the cell is small. The smallest real number anywhere in the workbook is 11, so each D stands for a count somewhere between 1 and 10 — which is why some figures here are a range.") +
        ' instead of a number, which is why some figures are a range.' : '') +
      '</p>';
    return h;
  }

  function qpRenderInventory(pdIso, cat, country) {
    var el = document.getElementById('qp-inventory');
    if (!el) return;
    var html = qpInventoryHtml(pdIso, cat, country);
    el.innerHTML = html;
    el.style.display = html ? '' : 'none';
    if (html && window.GCN_glossify) window.GCN_glossify(el);
  }

  // Loaded lazily: only the pages that draw the projector ever need it, and a
  // failed fetch must leave the rest of the projector working untouched.
  function qpLoadInventory(after) {
    if (gcnEbInvTried) { if (after) after(); return; }
    gcnEbInvTried = true;
    if (typeof fetch !== "function") { if (after) after(); return; }
    fetch("eb_inventory.json", { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.series) GCN_EB_INV = d; if (after) after(); })
      .catch(function () { if (after) after(); });
  }

  var QP_YEAR_MS = 365.25 * 24 * 3600 * 1000;
  function qpCompute(refIso, hypoPd, cat, country) {
    var nowY = new Date().getFullYear();
    var refMs = parseIsoToMs(refIso), pdMs = parseIsoToMs(hypoPd);
    var gapYears = (refMs == null || pdMs == null) ? 0 : Math.max(0, (pdMs - refMs) / QP_YEAR_MS);
    var p = qpPaceBand(cat, country);
    // Floor the paces so a near-frozen category (measured p25 can be as low as 0.05
    // cutoff-yr/yr) doesn't project absurd centuries, and cap each wait in years so the
    // worst case reads as a clear "80+" rather than 2200. slow<=typ<=fast enforced.
    var fast = Math.max(0.15, p.fast), typ = Math.max(0.1, p.typ), slow = Math.max(0.06, p.slow);
    fast = Math.max(fast, typ); slow = Math.min(slow, typ);
    var wB = Math.min(60, gapYears / fast), wT = Math.min(70, gapYears / typ), wW = Math.min(80, gapYears / slow);
    return {
      gapYears: gapYears,
      measured: p.measured,
      i140: nowY + 1,
      i485: { best: nowY + wB, typ: nowY + wT, worst: nowY + wW },
      gc: { best: nowY + wB + 1, typ: nowY + wT + 1, worst: nowY + wW + 1 }
    };
  }
  // The projection caps the worst-case wait near 80 years, but printing a precise
  // year that far out (e.g. 2107) reads as a confident forecast when it is really
  // "indefinite at the current pace". Past this horizon we describe the tail in
  // words ("beyond ~YYYY") instead of a specific year. ~30 years keeps realistic
  // multi-decade India/China estimates as bounded ranges while flagging the
  // century-scale tails the jury called out.
  function qpHorizonYear() { return new Date().getFullYear() + 30; }
  function qpRangeText(proj) {
    var lo = Math.round(proj.gc.best), typ = Math.round(proj.gc.typ), hi = Math.round(proj.gc.worst);
    var hz = qpHorizonYear();
    // Never print a precise year past the horizon. Which years are within it
    // decides the shape. Crucially this checks the TYPICAL year too: if the
    // median itself is past the horizon, we must NOT show it as a range endpoint
    // (that produced the nonsensical "approx. 2033-2068 · worst case beyond 2056").
    if (hi <= hz) {
      return { mode: "bounded", headline: "approx. " + lo + "&ndash;" + hi, plain: "approx. " + lo + "-" + hi, lo: lo, typ: typ, hi: hi, hz: hz, floor: null };
    }
    if (typ <= hz) {
      // Best and typical are within the horizon; only the slow tail runs past it.
      return { mode: "partial", headline: "approx. " + lo + "&ndash;" + typ + ' <span class="qp-beyond">&middot; worst case beyond ' + hz + "</span>", plain: "approx. " + lo + "-" + typ + ", worst case beyond " + hz, lo: lo, typ: typ, hi: hi, hz: hz, floor: null };
    }
    // The typical (median) pace itself lands past the horizon.
    if (lo <= hz) {
      // Fastest pace still gives a within-horizon floor; show it, and put the rest in words.
      return { mode: "beyond", headline: "approx. " + lo + ' <span class="qp-beyond">to beyond ' + hz + "</span>", plain: "approx. " + lo + " to beyond " + hz, lo: lo, typ: typ, hi: hi, hz: hz, floor: lo };
    }
    // Even the fastest pace is past the horizon.
    return { mode: "beyond", headline: "beyond " + hz, plain: "beyond " + hz, lo: lo, typ: typ, hi: hi, hz: hz, floor: null };
  }
  function qpMilestonesHtml(proj) {
    var nowY = new Date().getFullYear();
    if (proj.gapYears <= 0.04) {
      return '<div class="qp-current">Your priority date is at (or ahead of) the current cutoff. If your category is current you can file I-485 now; the green card is then mostly processing time, on the order of a year.</div>';
    }
    // Single timeline: I-140 (early) and the green-card window (I-485 -> approval,
    // ~1yr apart so shown as one marker), each with its year on top of the dot.
    var hz = qpHorizonYear();
    var worstY = Math.ceil(proj.gc.worst);
    var beyond = worstY > hz;               // tail past the reliable modeling horizon
    var axisWorstY = beyond ? hz : worstY;  // cap the visual axis so near markers aren't crushed
    var span = Math.max(1, axisWorstY - nowY);
    function pct(y) { return qpClampPct(((y - nowY) / span) * 100); }
    function lbl(p) { return Math.max(6, Math.min(94, p)); }
    function pt(cls, year, name, tier2) {
      return '<div class="qp-tl-pt ' + cls + (tier2 ? ' tier2' : '') + '" style="left:' + lbl(pct(year)) + '%;">' +
        '<span class="qp-tl-year">~' + year + '</span><span class="qp-tl-dot"></span><span class="qp-tl-name">' + name + '</span></div>';
    }
    var i140Y = Math.round(proj.i140);
    var i485Y = Math.round(proj.i485.typ);
    var gcTyp = Math.round(proj.gc.typ);
    var i485Best = Math.round(proj.i485.best), gcWorst = Math.round(proj.gc.worst);
    var bandL = pct(i485Best), bandR = pct(gcWorst);
    var h = '<div class="qp-tl">';
    h += '<div class="qp-tl-axis"><span>' + nowY + '</span><span>' + axisWorstY + (beyond ? '+' : '') + '</span></div>';
    h += '<div class="qp-tl-track">';
    h += '<div class="qp-tl-band" style="left:' + bandL + '%;width:' + Math.max(2, bandR - bandL) + '%;"></div>';
    h += pt('i140', i140Y, 'I-140', false);
    h += pt('i485', i485Y, 'I-485', false);
    // Green card sits ~1yr after I-485 (near-coincident on this axis) -> second label tier.
    h += pt('gc', gcTyp, 'Green card', true);
    h += '</div>';
    var worstTxt = beyond ? ('beyond ' + hz) : String(gcWorst);
    h += '<div class="qp-tl-note">Window <strong>' + i485Best + '&ndash;' + worstTxt + '</strong> (best to worst pace)' + (beyond ? '. The slowest pace runs past the reliable modeling horizon, so the far end is shown in words' : '') + '.</div>';
    h += '</div>';
    return h;
  }
  function qpRender(root, hypoPd) {
    var ref = root.getAttribute('data-ref');
    var cat = root.getAttribute('data-cat'), country = root.getAttribute('data-country');
    var startYear = +root.getAttribute('data-start'), endYear = +root.getAttribute('data-end');
    var span = endYear - startYear;
    var pdMs = parseIsoToMs(hypoPd);
    var pdPct = qpClampPct(((qpYearFrac(pdMs) - startYear) / span) * 100);
    var you = document.getElementById('qp-you'); if (you) you.style.left = pdPct + '%';
    var youLbl = document.getElementById('qp-you-lbl');
    if (youLbl) {
      youLbl.style.left = pdPct + '%'; youLbl.innerHTML = fmtDate(hypoPd) + '<br>You are here';
      // When the priority date sits near the cutoff, the two labels (same row,
      // absolute-positioned) collide. Measure the actual boxes and, if they
      // overlap, drop the "you are here" label onto a second row. Measurement-
      // based so it's correct on any width and updates live while dragging.
      var labels = youLbl.parentNode;
      var cutoffLbl = labels ? labels.querySelector('.cutoff-lbl') : null;
      youLbl.classList.remove('stacked');
      if (labels && labels.classList) labels.classList.remove('labels-stacked');
      if (cutoffLbl && youLbl.getBoundingClientRect && cutoffLbl.getBoundingClientRect) {
        var a = cutoffLbl.getBoundingClientRect(), b = youLbl.getBoundingClientRect();
        if (a.width && b.width && !(b.left > a.right + 4 || b.right < a.left - 4)) {
          youLbl.classList.add('stacked');
          if (labels && labels.classList) labels.classList.add('labels-stacked');
        }
      }
    }
    var gapEl = document.getElementById('qp-gap');
    var gap = diffYearsMonths(hypoPd, ref);
    if (gapEl) gapEl.innerHTML = (gap && !gap.negative && (gap.years || gap.months))
      ? ('Cutoff must advance <strong>' + gap.years + 'y ' + gap.months + 'm</strong> to reach this date')
      : 'This date is at or ahead of the current cutoff';
    if (you) {
      you.setAttribute('aria-valuemin', String(startYear));
      you.setAttribute('aria-valuemax', String(endYear));
      you.setAttribute('aria-valuenow', String(new Date(pdMs).getUTCFullYear()));
      you.setAttribute('aria-valuetext', fmtDate(hypoPd) + ((gap && !gap.negative && (gap.years || gap.months))
        ? (', cutoff must advance ' + gap.years + ' years ' + gap.months + ' months')
        : ', at or ahead of the current cutoff'));
    }
    var proj = qpCompute(ref, hypoPd, cat, country);
    var head = document.getElementById('qp-headline');
    if (head) {
      if (proj.gapYears <= 0.04) {
        head.innerHTML = '<div class="qp-big">You&rsquo;re at the front of the line</div><div class="qp-sub">If your category is current, you can file now; the green card is then mostly processing time.</div>';
      } else {
        var rt = qpRangeText(proj);
        // One tight sentence per mode. The fuller "not a prediction / retrogression"
        // explanation lives once in the caveat + the "How is this calculated?" panel,
        // so this doesn't restate it at length.
        var sub;
        if (rt.mode === "bounded") {
          sub = 'A what-if from past Visa Bulletin movement, not a prediction.';
        } else if (rt.mode === "partial") {
          sub = 'Typical-to-faster pace lands in this range; the slowest pace runs beyond ' + rt.hz + ', past the reliable modeling horizon.';
        } else if (rt.floor) {
          sub = 'Fastest pace lands around ' + rt.floor + '; the typical pace runs past ' + rt.hz + ', beyond the reliable modeling horizon.';
        } else {
          sub = 'Even at the fastest pace this is decades out, beyond the reliable modeling horizon, so treat it as indefinite at the current pace.';
        }
        head.innerHTML =
          '<div class="qp-scenario-label">Historical-pace scenario</div>' +
          '<div class="qp-big">' + rt.headline + '</div>' +
          '<div class="qp-sub">' + sub + '</div>';
      }
    }
    var pace = document.getElementById('qp-pace');
    if (pace) {
      if (proj.gapYears <= 0.04) {
        pace.innerHTML = '';
      } else {
        var m = qpPaceStats(cat, country);
        if (m) {
          var bits = ['Based on ' + m.yrs + ' years of Visa Bulletin history, this cutoff advanced a median of about ' + m.mo + ' months per year'];
          if (m.retro) bits.push('retrogressed ' + m.retro + ' time' + (m.retro > 1 ? 's' : ''));
          if (m.unavail) bits.push('and was Unavailable ' + m.unavail + ' month' + (m.unavail > 1 ? 's' : ''));
          pace.innerHTML = '<strong>Measured pace:</strong> ' + bits.join(', ') + '. The scenario below uses this measured rate.';
          pace.className = 'qp-pace measured';
        } else {
          pace.innerHTML = 'No consistent movement in the record to measure a pace for this category, so the scenario below uses a rough assumption. Treat it loosely.';
          pace.className = 'qp-pace';
        }
      }
    }
    var ms = document.getElementById('qp-milestones');
    if (ms) ms.innerHTML = qpMilestonesHtml(proj);
    var why = document.getElementById('qp-why');
    if (why) why.innerHTML = qpWhyHtml(ref, hypoPd, gap, qpPaceStats(cat, country), proj);
    // Re-counted on every drag: the count of people ahead is a function of the
    // marker's date, so it has to follow the marker rather than render once.
    qpRenderInventory(hypoPd, cat, country);
  }
  function wireQueueProjector() {
    var root = document.getElementById('queue-projector');
    if (!root) return;
    var bar = document.getElementById('qp-bar');
    var you = document.getElementById('qp-you');
    var reset = document.getElementById('qp-reset');
    var startYear = +root.getAttribute('data-start'), endYear = +root.getAttribute('data-end');
    var span = endYear - startYear;
    var orig = root.getAttribute('data-pd-original');
    var cur = orig;
    function pdFromPct(pct) {
      var yf = startYear + (pct / 100) * span;
      var y = Math.floor(yf), m = Math.max(0, Math.min(11, Math.round((yf - y) * 12)));
      return y + '-' + (m < 9 ? '0' + (m + 1) : (m + 1)) + '-01';
    }
    function pctFromClientX(cx) {
      if (!bar) return 0;
      var r = bar.getBoundingClientRect();
      if (r.width <= 0) return 0;
      return qpClampPct(((cx - r.left) / r.width) * 100);
    }
    function clientX(e) { return (e.touches && e.touches[0]) ? e.touches[0].clientX : e.clientX; }
    function setFromClientX(cx) { cur = pdFromPct(pctFromClientX(cx)); qpRender(root, cur); }
    function move(e) { setFromClientX(clientX(e)); if (e.cancelable) e.preventDefault(); }
    function up() {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      document.removeEventListener('touchmove', move);
      document.removeEventListener('touchend', up);
      if (you) you.classList.remove('dragging');
    }
    function down(e) {
      if (you) you.classList.add('dragging');
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
      document.addEventListener('touchmove', move, { passive: false });
      document.addEventListener('touchend', up);
      setFromClientX(clientX(e));
      if (e.cancelable) e.preventDefault();
    }
    if (you) {
      you.addEventListener('mousedown', down);
      you.addEventListener('touchstart', down, { passive: false });
      you.addEventListener('keydown', function (e) {
        var d = (e.key === 'ArrowLeft' || e.key === 'ArrowDown') ? -1 :
                (e.key === 'ArrowRight' || e.key === 'ArrowUp') ? 1 : 0;
        if (!d) return;
        e.preventDefault();
        var dt = new Date(parseIsoToMs(cur));
        dt.setUTCMonth(dt.getUTCMonth() + d * 3);
        var y = dt.getUTCFullYear(), m = dt.getUTCMonth();
        if (y < startYear) { y = startYear; m = 0; }
        if (y > endYear) { y = endYear; m = 0; }
        cur = y + '-' + (m < 9 ? '0' + (m + 1) : (m + 1)) + '-01';
        qpRender(root, cur);
      });
    }
    // Click anywhere on the track to jump the marker there.
    if (bar) bar.addEventListener('mousedown', function (e) { if (e.target !== you) down(e); });
    if (reset) reset.addEventListener('click', function () { cur = orig; qpRender(root, orig); });
    qpRender(root, orig);
    // The inventory arrives after the first paint, so re-render just its panel
    // when it lands, against whatever date the marker is on by then.
    qpLoadInventory(function () {
      qpRenderInventory(cur, root.getAttribute('data-cat'), root.getAttribute('data-country'));
    });
  }

  // Plain-English methodology for the queue projector, kept accurate to
  // qpCompute()/qpPaceBand()/VB_PACE above. Reuses the existing <details
  // class="collapsible"> pattern. Frames the output as a historical-pace
  // scenario, never a forecast.
  function qpMethodologyHtml() {
    var h = '<details class="collapsible qp-method"><summary>How is this calculated?</summary><div class="body">';
    h += '<p>This is a <strong>historical-pace scenario</strong>, not a forecast. It is built only from <strong>past Visa Bulletins</strong>: a checked-in history of the monthly <strong>Final Action Date</strong> cutoffs (the chart that sets when a green card can actually be issued). For any month where Final Action is Unavailable, the <strong>Dates for Filing</strong> cutoff is used as a stand-in so the pace still has a value to measure. Nothing is fetched live and no case data leaves your browser. For your category and country of chargeability, the pace is measured over the last several years of that record (about 71 monthly bulletins, spanning roughly the past 6.8 years up to the current bulletin).</p>';
    h += '<p><strong>How the pace is measured.</strong> Each month is compared with the previous month to see how far the cutoff moved. The whole window is then summarized into three rates, expressed as how much of the backlog the cutoff clears per calendar year: a <em>typical</em> rate (the median month-over-month movement), a <em>faster</em> rate (the upper quartile), and a <em>slower</em> rate (the lower quartile). Because these are the median and quartiles rather than a simple average, one unusually large or small month does not swing the result. The range shown above (for example, &ldquo;approx.&nbsp;2034&ndash;2040&rdquo;) comes from dividing the gap between your priority date and today&rsquo;s cutoff by each of those rates: the faster rate gives the near end, the slower rate the far end, and the typical rate sits in between. About one more year is added on top for I-485 processing to the green card in hand.</p>';
    h += '<p><strong>Retrogression, stalls, and the October jumps.</strong> Months where the cutoff moved backward (retrogression) or did not move at all are part of that history and are counted in the pace. They pull the measured rate down, and the count of retrogression and Unavailable months is noted in the pace line above. Each October a new fiscal year&rsquo;s visa numbers are released and cutoffs often jump forward; those forward jumps are already inside the measured history, so they are reflected in the pace rather than modeled separately. The model does not try to predict <em>when</em> a future retrogression, freeze, or October jump will happen.</p>';
    h += '<p><strong>When there is not enough history.</strong> For a category and country without enough consistent movement in the record to measure a rate, the tool does not claim a measured pace. It falls back to a rough general assumption and labels it as such above. Either way, a near-frozen category is floored and the worst case is capped. Past a reliable modeling horizon (about 30 years out) the far end of the range is shown in words, &ldquo;beyond ' + qpHorizonYear() + '&rdquo;, rather than a pinpoint year, because naming a specific year that far out would be false precision.</p>';
    h += '<p><strong>What this cannot account for.</strong> Changes to law, policy, or per-country limits; shifts in demand; a sudden retrogression or a category going Unavailable; and your own case-specific processing (employer, USCIS, or consular timing). Past movement does not guarantee future movement. Treat the range as one what-if built from history, and confirm anything against the official Visa Bulletin and a licensed immigration attorney.</p>';
    h += '</div></details>';
    return h;
  }

  // "Why this number?" — consolidates the specific inputs behind THIS range into
  // one place: the current cutoff, the user's priority date, the gap, the measured
  // historical pace, the scenario assumption, and the limitation. Reuses values
  // already computed in qpRender (ref/hypoPd/gap/qpPaceStats/qpCompute) so it can
  // never drift from the number shown. Complements qpMethodologyHtml (the general
  // method); this one is the per-input breakdown the range came from.
  function qpWhyHtml(ref, hypoPd, gap, m, proj) {
    if (!proj || proj.gapYears <= 0.04) return "";
    var rt = qpRangeText(proj);
    var h = '<details class="collapsible qp-why"><summary>Why this range?</summary><div class="body"><ul class="qp-why-list">';
    h += '<li><strong>Current cutoff (latest Visa Bulletin):</strong> ' + fmtDate(ref) + '. The priority date the queue is serving now for this category and country.</li>';
    h += '<li><strong>Your priority date:</strong> ' + fmtDate(hypoPd) + '.</li>';
    if (gap && !gap.negative && (gap.years || gap.months)) {
      h += '<li><strong>Gap to close:</strong> the cutoff has to advance about ' + gap.years + 'y ' + gap.months + 'm to reach your date.</li>';
    }
    if (m) {
      var obs = 'over the last ' + m.yrs + ' years this cutoff advanced a median of about ' + m.mo + ' months per calendar year';
      if (m.retro) { obs += ', retrogressed ' + m.retro + ' time' + (m.retro > 1 ? 's' : ''); }
      if (m.unavail) { obs += ', and was Unavailable ' + m.unavail + ' month' + (m.unavail > 1 ? 's' : ''); }
      h += '<li><strong>Historical observation:</strong> ' + obs + '.</li>';
      h += '<li><strong>Scenario assumption:</strong> the gap is divided by that measured pace (faster, typical, and slower rates), then about a year is added for I-485 processing, giving ' + rt.plain + '.</li>';
    } else {
      h += '<li><strong>Scenario assumption:</strong> there is not enough consistent movement in the record to measure a pace here, so the range falls back to a rough general assumption.</li>';
    }
    if (rt.mode === "partial") {
      h += '<li><strong>Why the far end is shown in words:</strong> at the slowest historical pace the wait runs past ' + rt.hz + '. That far out, a specific year would be false precision, so the tail is described as &ldquo;beyond ' + rt.hz + '&rdquo; rather than a pinpoint year.</li>';
    } else if (rt.mode === "beyond") {
      h += '<li><strong>Why this is shown in words, not a year:</strong> at the typical historical pace the wait already runs past ' + rt.hz + '' + (rt.floor ? ' (the fastest pace could reach about ' + rt.floor + ')' : '') + '. That far out, a specific year would be false precision, so it is described as &ldquo;beyond ' + rt.hz + '&rdquo; rather than a pinpoint year.</li>';
    }
    h += '<li><strong>Important limitation:</strong> future Visa Bulletin movement can differ substantially. Retrogression, policy shifts, or a category going Unavailable can push the real date well past this range.</li>';
    h += '</ul></div></details>';
    return h;
  }

  function queueTimelineBlock(pd, countryData, cat, country) {
    if (!pd || !countryData) return "";
    var refDate = countryData.final_action_date || countryData.date_for_filing;
    if (!refDate || refDate === "CURRENT") return "";
    var pdMs = parseIsoToMs(pd);
    var refMs = parseIsoToMs(refDate);
    if (pdMs == null || refMs == null) return "";
    var startYear = 2010;
    // End the axis at least 2 years out, but always past the priority date itself
    // so a PD near/after "today+2" still calibrates instead of pinning at the edge.
    var endYear = Math.max(new Date().getFullYear() + 2, new Date(pdMs).getFullYear() + 1);
    var totalSpan = endYear - startYear;
    var refPct = qpClampPct(((qpYearFrac(refMs) - startYear) / totalSpan) * 100);
    var pdPct = qpClampPct(((qpYearFrac(pdMs) - startYear) / totalSpan) * 100);
    var isUnavailable = countryData.final_action_date == null;
    var refLabel = isUnavailable ? "DFF cutoff" : "Queue is here (FAD)";

    var h = '<div class="queue-timeline" id="queue-projector"' +
      ' data-pd-original="' + esc(pd) + '" data-ref="' + esc(refDate) + '"' +
      ' data-cat="' + esc(cat || "") + '" data-country="' + esc(country || "") + '"' +
      ' data-start="' + startYear + '" data-end="' + endYear + '">';
    h += '<div class="tl-label">Your position in the queue <span class="qp-hint">(drag the amber dot to try a different priority date)</span></div>';
    h += '<div class="tl-bar" id="qp-bar">';
    h += '<div class="tl-filled" style="width:' + refPct + '%;"></div>';
    h += '<div class="tl-marker cutoff" style="left:' + refPct + '%;"></div>';
    h += '<div class="tl-marker you" id="qp-you" tabindex="0" role="slider" aria-label="Your priority date &mdash; drag or use arrow keys" style="left:' + pdPct + '%;"></div>';
    h += '</div>';
    h += '<div class="tl-labels">';
    h += '<span class="tl-lbl" style="left:0%;">' + startYear + '</span>';
    h += '<span class="tl-lbl cutoff-lbl" style="left:' + refPct + '%;">' + fmtDate(refDate) + '<br>' + refLabel + '</span>';
    h += '<span class="tl-lbl you-lbl" id="qp-you-lbl" style="left:' + pdPct + '%;">' + fmtDate(pd) + '<br>You are here</span>';
    h += '</div>';
    // Provenance for the government cutoff marker only (not the scenario years below).
    h += '<div class="source-stamp-row">' + sourceStamp(countryData) + '</div>';
    h += '<div class="qp-gap" id="qp-gap"></div>';
    if (isUnavailable) {
      h += '<div class="tl-note">Final Action is Unavailable this month (FY visa numbers exhausted). The scenario below uses the Dates-for-Filing cutoff as a proxy.</div>';
    }
    h += '<button type="button" class="qp-reset" id="qp-reset">Reset to my priority date</button>';
    h += '<div class="qp-headline" id="qp-headline"></div>';
    h += '<div class="qp-pace" id="qp-pace"></div>';
    h += '<div class="qp-milestones" id="qp-milestones"></div>';
    h += '<div class="qp-why-wrap" id="qp-why"></div>';
    // Queue depth from the USCIS I-485 inventory. Starts hidden and stays hidden
    // unless eb_inventory.json loads AND carries a series for this tier, so a fetch
    // failure or an unmodelled category leaves the projector exactly as it was.
    h += '<div class="qp-inv" id="qp-inventory" style="display:none;"></div>';
    h += qpMethodologyHtml();
    h += '<div class="qp-legend">' +
      '<span class="qp-leg"><i class="qp-swatch i140"></i>I-140 approved (petition stage)</span>' +
      '<span class="qp-leg"><i class="qp-swatch i485"></i>I-485 fileable</span>' +
      '<span class="qp-leg"><i class="qp-swatch gc"></i>Green card in hand</span>' +
      '<span class="qp-leg-note">Dot = typical year &middot; shaded band = best to worst pace</span></div>';
    h += '<div class="qp-caveat">A historical what-if, not a forecast. Cutoffs can retrogress or freeze for years, so the real date can slip later &mdash; verify against the official Visa Bulletin and a licensed immigration attorney. Full method in &ldquo;How is this calculated?&rdquo; above.</div>';
    h += '</div>';
    return h;
  }

  // ---- Side-by-side scenario compare ----------------------------------------
  // Scenario A is the user's actual case (fixed). Scenario B is editable
  // (category / country / priority date) so they can answer "what if I were
  // EB-3 instead of EB-2?", "what if I cross-charged to my spouse's country?",
  // etc. Both columns run the same projection math as the queue projector.
  function scenarioProjection(cat, country, pd) {
    var cd = effectiveCountryData(cat, country);
    if (!cd) return { status: "nodata" };
    var pdMs = parseIsoToMs(pd);
    if (pdMs == null) return { status: "nopd" };
    var fad = cd.final_action_date, dff = cd.date_for_filing;
    if (fad === "CURRENT") return { status: "current" };
    var ref = (fad && fad !== "CURRENT") ? fad : ((dff && dff !== "CURRENT") ? dff : null);
    if (ref == null) return { status: "unavailable" };
    var proj = qpCompute(ref, pd, cat, country);
    if (proj.gapYears <= 0.04) return { status: "current", ref: ref, usedDff: (fad == null) };
    return {
      status: "project",
      usedDff: (fad == null),
      ref: ref,
      gap: diffYearsMonths(pd, ref),
      proj: proj,
      measured: proj.measured
    };
  }
  function scenarioYear(s) {
    if (!s) return null;
    if (s.status === "current") return "now";
    if (s.status === "project") return Math.round(s.proj.gc.typ);
    return null;
  }
  function compareBody(cat, country, pd) {
    var s = scenarioProjection(cat, country, pd);
    if (s.status === "nodata") return '<div class="cmp-big muted">No Visa Bulletin data for this pairing.</div>';
    if (s.status === "nopd") return '<div class="cmp-big muted">Enter a priority date.</div>';
    if (s.status === "current") return '<div class="cmp-big">Current: file now</div><div class="cmp-sub">green card then mostly processing time, on the order of a year</div>';
    if (s.status === "unavailable") return '<div class="cmp-big">Unavailable this month</div><div class="cmp-sub">no filing or final-action date is being issued right now</div>';
    var rt = qpRangeText(s.proj);
    var h = '<div class="cmp-scenario-label">Historical-pace scenario</div>';
    h += '<div class="cmp-big">' + rt.headline + '</div>';
    h += '<div class="cmp-sub">green-card range if the historical pace held' + (rt.mode !== "bounded" ? ' (slowest pace runs beyond the reliable modeling horizon, shown in words)' : '') + '</div>';
    if (s.gap && !s.gap.negative && (s.gap.years || s.gap.months)) {
      h += '<div class="cmp-gap">Cutoff must advance <strong>' + s.gap.years + 'y ' + s.gap.months + 'm</strong></div>';
    }
    h += '<div class="cmp-tag' + (s.measured ? ' measured' : '') + '">' + (s.measured ? "measured pace" : "assumed pace") + (s.usedDff ? " &middot; via filing-date proxy" : "") + '</div>';
    // Provenance for the government cutoff this scenario pivots on (not the projected years).
    h += '<div class="source-stamp-row">' + sourceStamp(effectiveCountryData(cat, country)) + '</div>';
    return h;
  }
  function compareDelta(sA, sB) {
    var ya = scenarioYear(sA), yb = scenarioYear(sB);
    if (ya == null || yb == null) return "Not enough data to compare these two directly.";
    if (ya === "now" && yb === "now") return "Both scenarios are current, so no Visa Bulletin wait in either.";
    if (yb === "now") return "Scenario B is current (file now), versus a green card around " + ya + " in Scenario A.";
    if (ya === "now") return "Scenario A is current (file now), versus a green card around " + yb + " in Scenario B.";
    var d = ya - yb; // positive => B sooner
    if (Math.abs(d) < 1) return "Both land around the same year (" + ya + ").";
    return "Scenario B centers about <strong>" + Math.abs(d) + (Math.abs(d) === 1 ? " year " : " years ") + (d > 0 ? "sooner" : "later") + "</strong> than Scenario A (" + yb + " vs " + ya + ").";
  }
  // Only offer category/country pairings the built-in bulletin snapshot actually
  // covers (EB-1/2/3 × the countries present for each), so the compare dropdowns
  // can never dead-end on a "no data" pairing. Country coverage is per-category
  // (e.g. EB-1 has no Rest-of-World cell), so it is rebuilt when category changes.
  function cmpCatKeys() {
    var cats = (rulebook.bulletin && rulebook.bulletin.categories) || {};
    return ["EB-1", "EB-2", "EB-3", "EB-4", "EB-5", "F1", "F2A", "F2B", "F3", "F4"]
      .filter(function (k) { return cats[k] && Object.keys(cats[k]).length; });
  }
  function cmpCountriesFor(cat) {
    var cats = (rulebook.bulletin && rulebook.bulletin.categories) || {};
    var have = cats[cat] ? Object.keys(cats[cat]) : [];
    return ["India", "China", "ROW", "Mexico", "Philippines"].filter(function (c) { return have.indexOf(c) !== -1; });
  }
  function cmpCountryOptions(cat, selected) {
    return cmpCountriesFor(cat).map(function (c) {
      return '<option value="' + c + '"' + (c === selected ? " selected" : "") + '>' + esc(countryLabel(c)) + '</option>';
    }).join("");
  }
  function compareScenarioBlock(pd, cat, country) {
    if (!pd) return "";
    var sA = scenarioProjection(cat, country, pd);
    if (sA.status !== "project") return ""; // only when A is a genuine waiting projection (mirrors the projector's gate)
    var catKeys = cmpCatKeys();
    // Default B category: flip EB-2<->EB-3, else the first covered category that isn't A's.
    var defCatB = (cat === "EB-2") ? "EB-3" : (cat === "EB-3") ? "EB-2" : null;
    if (!defCatB || catKeys.indexOf(defCatB) === -1) {
      defCatB = catKeys.filter(function (k) { return k !== cat; })[0] || catKeys[0];
    }
    var bCountries = cmpCountriesFor(defCatB);
    var defCountryB = (bCountries.indexOf(country) !== -1) ? country : bCountries[0];
    var defPdB = pd;
    var catOpts = catKeys.map(function (k) {
      return '<option value="' + k + '"' + (k === defCatB ? " selected" : "") + '>' + esc(VISA_TYPES[k] ? VISA_TYPES[k].label : k) + '</option>';
    }).join("");
    var couOpts = cmpCountryOptions(defCatB, defCountryB);
    var sB = scenarioProjection(defCatB, defCountryB, defPdB);

    var h = '<div class="result-block cmp-block" id="cmp-block"' +
      ' data-a-cat="' + esc(cat) + '" data-a-country="' + esc(country) + '" data-a-pd="' + esc(pd) + '">';
    h += '<h3><span class="num">&#8646;</span>Compare Another Scenario</h3>';
    h += '<p class="help">Scenario A is your case. Change Scenario B’s category, country, or priority date to see how a different path would compare. It uses the same historical-pace math as the timeline above. Covers the employment categories the tool tracks (EB-1, EB-2, EB-3).</p>';
    h += '<div class="cmp-grid">';
    // Column A (fixed)
    h += '<div class="cmp-col cmp-a">';
    h += '<div class="cmp-head"><span class="cmp-tagline">Scenario A &middot; your case</span>' +
      '<div class="cmp-scn">' + esc(VISA_TYPES[cat] ? VISA_TYPES[cat].label : cat) + '<br>' + esc(countryLabel(country)) + ' &middot; ' + esc(fmtDate(pd)) + '</div></div>';
    h += '<div class="cmp-body" id="cmp-body-A">' + compareBody(cat, country, pd) + '</div>';
    h += '</div>';
    // Column B (editable)
    h += '<div class="cmp-col cmp-b">';
    h += '<div class="cmp-head"><span class="cmp-tagline">Scenario B &middot; what if&hellip;</span>';
    h += '<div class="cmp-controls">';
    h += '<label>Category<select id="cmp-cat-b" aria-label="Scenario B category">' + catOpts + '</select></label>';
    h += '<label>Country<select id="cmp-country-b" aria-label="Scenario B country">' + couOpts + '</select></label>';
    h += '<label>Priority date<input type="date" id="cmp-pd-b" aria-label="Scenario B priority date" value="' + esc(pd) + '"></label>';
    h += '</div></div>';
    h += '<div class="cmp-body" id="cmp-body-B">' + compareBody(defCatB, defCountryB, defPdB) + '</div>';
    h += '</div>';
    h += '</div>'; // cmp-grid
    h += '<div class="cmp-delta" id="cmp-delta">' + compareDelta(sA, sB) + '</div>';
    h += '<div class="cmp-caveat">Same caveat as the timeline: a historical-pace scenario, not a promise. Cutoffs retrogress and stall. Verify against the official Visa Bulletin and a licensed immigration attorney.</div>';
    h += '</div>';
    return h;
  }
  function wireCompare() {
    var root = document.getElementById("cmp-block");
    if (!root) return;
    var catSel = document.getElementById("cmp-cat-b");
    var couSel = document.getElementById("cmp-country-b");
    var pdInp = document.getElementById("cmp-pd-b");
    var bodyB = document.getElementById("cmp-body-B");
    var deltaEl = document.getElementById("cmp-delta");
    var aCat = root.getAttribute("data-a-cat"), aCountry = root.getAttribute("data-a-country"), aPd = root.getAttribute("data-a-pd");
    function recompute() {
      var bCat = catSel ? catSel.value : aCat;
      var bCountry = couSel ? couSel.value : aCountry;
      var bPd = (pdInp && pdInp.value) ? pdInp.value : aPd;
      if (bodyB) bodyB.innerHTML = compareBody(bCat, bCountry, bPd);
      if (deltaEl) deltaEl.innerHTML = compareDelta(scenarioProjection(aCat, aCountry, aPd), scenarioProjection(bCat, bCountry, bPd));
    }
    if (catSel) catSel.addEventListener("change", function () {
      // Country coverage differs per category (e.g. EB-1 has no Rest-of-World cell),
      // so rebuild the country options; keep the current pick if it's still valid.
      var newCat = catSel.value;
      var valid = cmpCountriesFor(newCat);
      var keep = (couSel && valid.indexOf(couSel.value) !== -1) ? couSel.value : valid[0];
      if (couSel) couSel.innerHTML = cmpCountryOptions(newCat, keep);
      recompute();
    });
    if (couSel) couSel.addEventListener("change", recompute);
    if (pdInp) { pdInp.addEventListener("change", recompute); pdInp.addEventListener("input", recompute); }
  }

  // Generic "what if the PERM stalls / is delayed / is paused" guidance. No
  // employer-specific claims — options are general and sourced. Shown in the EB
  // results and the pre-PERM planning flow.
  function permStallBlock() {
    var h = '<div class="result-block">';
    h += '<h3><span class="num">i</span>If Your PERM Stalls, Is Delayed, or Is Paused</h3>';
    h += '<p class="help">A PERM can slow down or pause for reasons outside your control: a DOL audit, processing backlogs, or an employer pausing new sponsorships. Here is what generally still holds and the options people weigh. General information, not legal advice.</p>';
    h += '<ul class="timeline">';
    h += '<li><strong>Your priority date is protected once it locks.</strong> It is set the day the ETA 9089 is filed; a later delay or pause does not move it. Once the I-140 is approved, the priority date is yours and portable to a new employer (AC21 &sect;104(c)).</li>';
    h += '<li><strong>Self-petition paths skip PERM entirely.</strong> EB-1A (extraordinary ability) and EB-2 NIW (national interest waiver) need no employer and no PERM. The evidence bar is high, but they remove the dependency on a stalled PERM.</li>';
    h += '<li><strong>EB-3 downgrade.</strong> If the EB-3 cutoff is ahead of EB-2 for your country, a second I-140 under EB-3 using the same priority date can sometimes move faster.</li>';
    h += '<li><strong>Cross-chargeability.</strong> If your spouse was born in a country with a shorter queue, you may be able to charge the case to their country of birth (INA &sect;202(b)).</li>';
    h += '<li><strong>Protect your status; think hard before leaving the U.S.</strong> A pause affects the green-card timeline, not necessarily your work status. H-1B extensions under AC21 &sect;106(a) and &sect;104(c) can keep you in status through a long wait. Letting status lapse or leaving at the wrong time can forfeit progress. Talk to an attorney before any move.</li>';
    h += '</ul>';
    h += '<p class="paste-disclaimer">General information, not legal advice. Eligibility is fact-specific. Verify against official sources (' + extLink("https://www.uscis.gov/policy-manual", "uscis.gov") + ', ' + extLink("https://flag.dol.gov/", "flag.dol.gov") + ') and check with your employer&rsquo;s immigration counsel or a licensed immigration attorney before making any decisions.</p>';
    h += '</div>';
    return h;
  }

  function nextStepsBlock() {
    var v = state.perm;
    var h = '<div class="next-steps-card"><div class="ns-head">What should I do now?</div>';
    if (v === "not-filed") {
      h += '<span class="ns-action">Your employer hasn\'t started the PERM process.</span> This is the first and most important step. Talk to your immigration attorney or HR about initiating it. Every day of delay adds a day to your wait because your priority date doesn\'t lock until the PERM is filed.';
    } else if (v === "pwd") {
      h += '<span class="ns-action">You\'re waiting for the Prevailing Wage Determination (PWD) from DOL.</span> This typically takes 4-5 months. No action needed from you. Your attorney/HR handles this. The PERM application (ETA 9089) cannot be filed until the PWD comes back.';
    } else if (v === "lmt") {
      h += '<span class="ns-action">Your employer is running the required recruitment advertisements (Labor Market Test).</span> This takes 2-3 months. No action needed from you. After this closes, the ETA 9089 form will be filed with DOL and your priority date will be locked.';
    } else if (v === "filed") {
      h += '<span class="ns-action">Your PERM is filed. Your priority date is locked.</span> Now you wait for DOL analyst review (currently ~13 months processing). After approval, your employer files the I-140 petition with USCIS. Meanwhile, once the PERM has been pending 365+ days, AC21 §106(a) generally allows H-1B extensions beyond the usual 6-year limit, which usually lets you keep working while you wait. This depends on continued eligibility and timely filings. Confirm your specifics with your attorney.';
    } else if (v === "audited") {
      h += '<span class="ns-action">DOL has issued an audit. Your attorney is handling the response.</span> Audits add approximately 9 months to processing. Your priority date is preserved regardless of the audit outcome. No action needed from you unless your attorney asks for additional documentation.';
    } else if (v === "approved") {
      h += '<span class="ns-action">Your PERM is approved. Next step is the I-140 petition.</span> Your employer files Form I-140 with USCIS. Consider asking about premium processing (15 business days, $' + rulebook.i140.premium_processing.fee_usd.toLocaleString() + ' fee) vs regular processing (~8 months). Once the I-140 is approved, your priority date becomes portable. You can change jobs without losing your place in line (AC21 §104(c)).';
    } else if (v === "denied") {
      h += '<span class="ns-action">Your PERM was denied.</span> Discuss with your attorney whether to appeal (Motion to Reconsider), refile a new PERM (new priority date), or explore alternative pathways such as EB-2 NIW (self-petition, no employer needed) or EB-1 if you qualify. A denied PERM generally does not give you a priority date to carry forward. Your options (appeal, refile, or a different path) and what happens to timing should be reviewed with your attorney.';
    } else {
      h += 'Your next steps depend on where you are in the PERM process. Select your PERM status in Step 6 above to see personalized guidance here.';
    }
    h += '</div>';
    return h;
  }

  function bulletinBadgeBlock() {
    var asOf = rulebook.bulletin && rulebook.bulletin.as_of;
    if (!asOf) return "";
    var parts = asOf.split("-");
    var y = parseInt(parts[0], 10), m = parseInt(parts[1], 10);
    var months = ["","January","February","March","April","May","June","July","August","September","October","November","December"];
    var monthName = months[m] || "";
    var nextM = m + 1, nextY = y;
    if (nextM > 12) { nextM = 1; nextY++; }
    var nextMonthName = months[nextM] || "";
    var h = '<div class="bulletin-badge">Data as of: ' + esc(monthName + " " + y) + ' Visa Bulletin. ';
    h += '<a href="https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html" target="_blank" rel="noopener">View official bulletin</a></div>';
    h += '<div class="bulletin-next">Next bulletin expected: ~' + esc(nextMonthName) + ' 9, ' + nextY + ' (published around the 9th of each month for the following month)</div>';
    return h;
  }

  function eb1InfoBlock() {
    var cat = state.category;
    var country = state.country || "India";
    var eb1Data = rulebook.bulletin && rulebook.bulletin.categories && rulebook.bulletin.categories["EB-1"];
    var countryData = eb1Data && eb1Data[country];
    var fadLabel = "N/A", dffLabel = "N/A";
    if (countryData) {
      fadLabel = countryData.final_action_date === "CURRENT" ? "Current (no wait)" : (countryData.final_action_date ? fmtDate(countryData.final_action_date) : "Unavailable");
      dffLabel = countryData.date_for_filing === "CURRENT" ? "Current" : (countryData.date_for_filing ? fmtDate(countryData.date_for_filing) : "N/A");
    }
    var waitEst = rulebook.wait_estimates && rulebook.wait_estimates.bands && rulebook.wait_estimates.bands["EB-1 India, PD locked 2026"];
    var typicalWait = waitEst ? fmtBand(waitEst.typical_case_years) + " years" : "8-12 years";

    var showAs = (cat === "EB-1") ? "primary" : "sidebar";
    // The user's chosen sub-category, only meaningful in primary (EB-1) mode.
    var sub = (showAs === "primary") ? state.eb1sub : null;

    // Each sub-category's detail block. `emphasize` renders it as the user's
    // selected path (highlighted); otherwise it's a normal reference block.
    function subBlock(key, emphasize) {
      var titles = {
        "EB-1A": "EB-1A: Extraordinary Ability",
        "EB-1B": "EB-1B: Outstanding Researcher / Professor",
        "EB-1C": "EB-1C: Multinational Manager / Executive"
      };
      var bodies = {
        "EB-1A":
          '<p><strong>Who qualifies:</strong> Self-petition: no employer or job offer needed. You file the I-140 yourself. Must demonstrate extraordinary ability by meeting at least 3 of the 10 criteria below (or a one-time major award like a Nobel).</p>' +
          '<ul><li>Major awards or prizes in the field</li><li>Published scholarly articles</li><li>Judging the work of others</li><li>Original contributions of major significance</li><li>Authorship of scholarly articles</li><li>Work displayed at exhibitions</li><li>Leading/critical role in distinguished organizations</li><li>High salary relative to peers</li><li>Membership in associations requiring outstanding achievement</li><li>Commercial success in performing arts</li></ul>' +
          '<p><strong>Timeline:</strong> No PERM. File I-140 directly (with or without a job offer). Priority date = I-140 filing date. Premium processing available (15 business days, $' + rulebook.i140.premium_processing.fee_usd.toLocaleString() + ').</p>',
        "EB-1B":
          '<p><strong>Who qualifies:</strong> Employer-sponsored. Requires 3+ years of research experience AND international recognition in a specific academic area. Typically a fit for PhD researchers with a publication record.</p>' +
          '<p><strong>Evidence:</strong> Publications, citations, peer review / journal editorial service, and research contributions recognized internationally. A permanent research or tenure-track position from the sponsoring employer is expected.</p>' +
          '<p><strong>Timeline:</strong> No PERM. Employer files the I-140. Priority date = I-140 filing date. Same visa queue as EB-1A.</p>',
        "EB-1C":
          '<p><strong>Who qualifies:</strong> Employer-sponsored. You must have worked 1+ year abroad (within the last 3 years) for the same company or an affiliate, and be coming to a genuinely managerial or executive role in the US. Common for intra-company transfers, often paired with prior L-1A history.</p>' +
          '<p><strong>Key requirement:</strong> The role must be genuinely managerial or executive (managing people or a function), not a senior individual contributor with a "manager" title.</p>' +
          '<p><strong>Timeline:</strong> No PERM. Employer files the I-140. Priority date = I-140 filing date. Same visa queue as EB-1A.</p>'
      };
      var style = emphasize
        ? ' style="border-left-width:5px;border-left-color:var(--success-600);background:var(--success-50);"'
        : '';
      var badge = emphasize
        ? ' <span style="font-size:11px;font-weight:700;color:var(--success-600);text-transform:uppercase;letter-spacing:0.4px;">&middot; Your selected path</span>'
        : '';
      return '<div class="eb1-sub"' + style + '><h4>' + titles[key] + badge + '</h4>' + bodies[key] + '</div>';
    }

    var h = '<div class="eb1-panel">';
    if (showAs === "sidebar") {
      h += '<h4 style="margin:0 0 10px;font-size:16px;color:var(--primary-700);">Consider EB-1? (faster queue, no PERM required)</h4>';
      h += '<p style="font-size:12.5px;color:var(--muted);margin:0 0 12px;">EB-1 skips the PERM process entirely. Priority date = I-140 filing date. Current EB-1 ' + esc(countryLabel(country)) + ' queue: FAD ' + esc(fadLabel) + '. Typical wait for India: ' + esc(typicalWait) + '.</p>';
    } else {
      var subTitle = (sub === "EB-1A" || sub === "EB-1B" || sub === "EB-1C")
        ? sub + " Details"
        : "EB-1 Category Details";
      h += '<h3 style="margin:0 0 12px;font-size:18px;">' + esc(subTitle) + '</h3>';
      h += '<p style="font-size:13px;margin:0 0 6px;"><strong>Current queue (EB-1 ' + esc(countryLabel(country)) + '):</strong> Final Action Date: ' + esc(fadLabel) + ' &middot; Date for Filing: ' + esc(dffLabel) + '</p>';
      h += '<p style="font-size:13px;margin:0 0 14px;color:var(--muted);">Typical wait for India: ' + esc(typicalWait) + '. No PERM required for any EB-1 sub-category. All three share this same queue.</p>';
      if (sub === "unsure") {
        h += '<p style="font-size:13px;margin:0 0 14px;padding:10px 12px;background:var(--neutral-150);border-radius:8px;">You selected <strong>Not sure yet</strong>. All three EB-1 sub-types are shown below. The quickest way to narrow it down: if you can self-petition on your own achievements, look at EB-1A; if you are a published researcher with a sponsoring employer, look at EB-1B; if you transferred into a manager/executive role from an overseas office of the same company, look at EB-1C. An immigration attorney can confirm which criteria you actually meet before you file.</p>';
      }
    }

    if (sub === "EB-1A" || sub === "EB-1B" || sub === "EB-1C") {
      // Emphasize the selected sub-type first, then show the others for reference.
      h += subBlock(sub, true);
      var others = ["EB-1A", "EB-1B", "EB-1C"].filter(function (k) { return k !== sub; });
      h += '<p style="font-size:12.5px;color:var(--muted);margin:14px 0 8px;">Other EB-1 sub-categories, for reference:</p>';
      others.forEach(function (k) { h += subBlock(k, false); });
    } else {
      // Sidebar mode or "not sure": show all three equally.
      h += subBlock("EB-1A", false);
      h += subBlock("EB-1B", false);
      h += subBlock("EB-1C", false);
    }
    h += '</div>';
    return h;
  }

  function f1OptPanel() {
    var h = '<div class="f1-panel">';
    h += '<h4>F-1 OPT / STEM OPT Path to Green Card</h4>';
    h += '<p>If you are on F-1 OPT or STEM OPT and considering the green card path, here is how the pipeline works:</p>';
    h += '<div class="f1-step"><span>F-1 Student</span><span class="arrow">&rarr;</span><span>OPT (12 months)</span><span class="arrow">&rarr;</span><span>STEM OPT Extension (+24 months)</span><span class="arrow">&rarr;</span><span>H-1B or direct EB green card</span></div>';
    h += '<p style="margin-top:12px;"><strong>Key timing constraint:</strong> STEM OPT expires after 36 months total. You must have H-1B approved OR transition to another status before it expires.</p>';
    h += '<ul>';
    h += '<li><strong>H-1B lottery risk:</strong> ~30% selection rate in recent years. You get up to 3 chances during STEM OPT.</li>';
    h += '<li><strong>Cap-exempt H-1B:</strong> Universities, non-profits, and government research organizations don\'t require the lottery.</li>';
    h += '<li><strong>Direct to green card without H-1B:</strong> Possible via EB-1A (self-petition) or EB-2 NIW (National Interest Waiver). Both skip PERM AND H-1B. Requires strong credentials (publications, patents, extraordinary ability).</li>';
    h += '<li><strong>Day-1 CPT:</strong> Some schools offer this but it is legally risky. USCIS scrutinizes it heavily and it can jeopardize future immigration benefits.</li>';
    h += '</ul>';
    h += '<p style="margin-top:8px;"><strong>Key dates to remember:</strong></p>';
    h += '<ul>';
    h += '<li>OPT application: up to 90 days before graduation, no later than 60 days after</li>';
    h += '<li>STEM extension: must apply BEFORE OPT expires (recommended 90 days early)</li>';
    h += '<li>H-1B registration: March each year (for October 1 start)</li>';
    h += '</ul>';
    h += '</div>';
    return h;
  }

  function resourcesSection(showHeading) {
    // Each link carries a trust "type" so a badge can make the hierarchy obvious:
    //   official   = U.S. government primary source
    //   secondary  = law firm / third-party tool (informed but not authoritative)
    //   community  = crowd-reported experiences, not verified
    var categories = [
      { title: "Official Government Sources", links: [
        { name: "Visa Bulletin", url: "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", desc: "Monthly cutoff dates for all EB categories", type: "official" },
        { name: "USCIS Processing Times", url: "https://egov.uscis.gov/processing-times/", desc: "Current processing times for I-140, I-485, etc.", type: "official" },
        { name: "DOL PERM Processing", url: "https://flag.dol.gov/", desc: "PERM and PWD processing timelines", type: "official" },
        { name: "USCIS Policy Manual", url: "https://www.uscis.gov/policy-manual", desc: "Official USCIS policy guidance for immigration benefits", type: "official" },
        { name: "Federal Register", url: "https://www.federalregister.gov/", desc: "New rules, proposed rules, and policy changes", type: "official" }
      ]},
      { title: "Trackers & Tools", links: [
        { name: "Green Card Clock", url: "https://greencardclock.com", desc: "Queue predictions and wait time estimates", type: "secondary" },
        { name: "Trackitt", url: "https://www.trackitt.com", desc: "Community-reported processing timelines", type: "community" },
        { name: "AM22Tech", url: "https://www.am22tech.com", desc: "Immigration news and calculator tools", type: "secondary" },
        { name: "Immihelp", url: "https://www.immihelp.com", desc: "Calculators, guides, and visa information", type: "secondary" }
      ]},
      { title: "Law Firms (Free Resources & Blogs)", links: [
        { name: "Murthy Law Firm", url: "https://www.murthy.com", desc: "Weekly bulletins and EB immigration analysis", type: "secondary" },
        { name: "Fragomen", url: "https://www.fragomen.com", desc: "Global immigration law insights", type: "secondary" },
        { name: "Boundless", url: "https://www.boundless.com", desc: "Simplified immigration guidance and tools", type: "secondary" },
        { name: "Berry Appleman & Leiden (BAL)", url: "https://www.bal.com", desc: "Corporate immigration law firm. Relevant if BAL handles your employer-sponsored case", type: "secondary" },
        { name: "Ogletree Deakins", url: "https://ogletree.com/practices/immigration/", desc: "Employment & immigration law: employer-side compliance, I-9, visa processing", type: "secondary" }
      ]},
      { title: "Community", links: [
        { name: "Reddit r/immigration", url: "https://www.reddit.com/r/immigration", desc: "General immigration discussion and questions", type: "community" },
        { name: "Reddit r/h1b", url: "https://www.reddit.com/r/h1b", desc: "H-1B specific discussions and timeline sharing", type: "community" },
        { name: "Reddit r/USCIS", url: "https://www.reddit.com/r/USCIS", desc: "Case status updates and processing experiences", type: "community" }
      ]}
    ];
    var RES_BADGE = { official: "Official", secondary: "Secondary", community: "Community" };
    var h = '<div class="resources-section">';
    // Heading suppressed on the standalone Resources page (the page supplies its
    // own <h2>); kept for result-panel injections which have no other heading.
    if (showHeading !== false) { h += '<h3>Resources</h3>'; }
    // Heading levels adapt to context so levels never skip: on the standalone
    // Resources page (showHeading===false) the page supplies an <h1> + section
    // <h2>, so categories are <h3> and cards <h4>; in result-panel injections
    // this block renders its own <h3>, so categories are <h4> and cards <h5>.
    var catTag = (showHeading === false) ? 'h3' : 'h4';
    var cardTag = (showHeading === false) ? 'h4' : 'h5';
    h += '<p class="res-legend">Each source is tagged <span class="res-badge res-official">Official</span> (U.S. government), <span class="res-badge res-secondary">Secondary</span> (law firm or third-party tool), or <span class="res-badge res-community">Community</span> (crowd-reported, not verified).</p>';
    for (var i = 0; i < categories.length; i++) {
      var cat = categories[i];
      h += '<div class="resources-cat"><' + catTag + '>' + esc(cat.title) + '</' + catTag + '>';
      h += '<div class="resources-grid">';
      for (var j = 0; j < cat.links.length; j++) {
        var lnk = cat.links[j];
        var bt = lnk.type || "secondary";
        h += '<div class="resource-card"><div class="res-card-head"><' + cardTag + '>' + esc(lnk.name) + '</' + cardTag + '>';
        h += '<span class="res-badge res-' + bt + '">' + esc(RES_BADGE[bt] || bt) + '</span></div>';
        h += '<p>' + esc(lnk.desc) + '</p>';
        h += '<a href="' + esc(lnk.url) + '" target="_blank" rel="noopener">' + esc(lnk.url.replace("https://","").replace("http://","")) + '</a>';
        h += '</div>';
      }
      h += '</div></div>';
    }
    h += '</div>';
    return h;
  }

  function i140StageBlock() {
    if (!hasDetail("i140")) return "";
    var v = state.i140;
    var msg = "";
    var active = false;
    var showI140Freshness = false;
    var i140 = rulebook.i140 || {};
    if (v === "not-filed") msg = "§104(c) is not yet available. It requires I-140 approval.";
    else if (v === "pending-regular") {
      var regMonths = (i140.regular_processing_months != null) ? i140.regular_processing_months : 8;
      msg = "I-140 pending (typically ~" + regMonths + " months regular). §104(c) unlocks on approval.";
      showI140Freshness = true;
    }
    else if (v === "pending-premium") msg = "I-140 pending premium (~15 business days). §104(c) is about to unlock.";
    else if (v === "approved") { msg = "§104(c) is ACTIVE. 3-year H-1B extensions are available. Priority date is portable to a new employer."; active = true; }
    else if (v === "rfe") msg = "RFE received. Your immigration attorney handles the response. Timeline typically slips by 2-3 months.";
    else if (v === "denied") msg = "Denial can be appealed. Priority date is lost unless another approved I-140 exists.";
    if (!msg) return "";
    var style = active ? ' style="border-left-color:var(--best);background:var(--best-bg);color:var(--best-text);"' : '';
    var headColor = active ? ' style="color:var(--best);"' : '';
    var freshness = "";
    // I-140 processing-time freshness note (only when the regular-processing
    // figure is unverified and we're showing that months number).
    if (showI140Freshness && i140.regular_processing_verified === false) {
      var note = i140.regular_processing_note || "Approximate. Check current processing times.";
      var url = i140.regular_processing_source_url;
      freshness = '<div class="i140-freshness">~' +
        esc((i140.regular_processing_months != null ? i140.regular_processing_months : 8)) +
        ' months (approximate, check current at ' +
        (url ? extLink(url, "egov.uscis.gov") : "egov.uscis.gov") + ').' +
        '<span class="note">' + esc(note) + '</span></div>';
    }
    return '<div class="enrichment"' + style + '><div class="head"' + headColor + '>I-140 stage</div>' + esc(msg) + freshness + '</div>';
  }

  // Data-driven cross-chargeability. Reads the rulebook bulletin Final Action
  // Dates for the applicant's country and the spouse's country in the SAME
  // category and compares them per INA §202(b): if the spouse's country has a
  // MORE CURRENT FAD, charging the case to the spouse's country may help.
  function crossChargeBlock() {
    if (!hasDetailIncl("spouse")) return "";
    var s = state.spouse;
    var c = state.country;
    var cat = state.category;
    // Suppress entirely for the non-country options.
    if (s === "not-married" || s === "skip") return "";
    // "Same as mine" — same country, no benefit possible.
    if (s === "same" || s === c) {
      return '<div class="result-block" style="border-left:4px solid var(--amber-accent);background:var(--amber-bg);">' +
        '<h3 style="color:var(--amber-accent);"><span class="num" style="background:var(--card);color:var(--amber-accent);">*</span>Cross-chargeability note</h3>' +
        '<p style="margin:0;color:var(--amber-text);">Your spouse\'s country of birth is the same as yours (' + esc(countryLabel(c)) + '), so cross-chargeability under INA §202(b) does not help. There is no different, more-current country to charge to.</p>' +
        '</div>';
    }

    var catData = rulebook.bulletin.categories[cat];
    var applicantData = catData ? catData[c] : null;
    var spouseData = catData ? catData[s] : null;
    // Missing bulletin data for either side — cannot compare.
    if (!applicantData || !spouseData) {
      return '<div class="result-block" style="border-left:4px solid var(--amber-accent);background:var(--amber-bg);">' +
        '<h3 style="color:var(--amber-accent);"><span class="num" style="background:var(--card);color:var(--amber-accent);">*</span>Cross-chargeability note</h3>' +
        '<p style="margin:0;color:var(--amber-text);">We do not have bulletin data for ' + esc(cat) + ' in both ' + esc(countryLabel(c)) + ' and ' + esc(countryLabel(s)) + ', so we cannot compare the two queues. Check current Final Action Dates at ' +
        extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "travel.state.gov") + ' and discuss with your immigration attorney.</p>' +
        '</div>';
    }

    var applicantFAD = applicantData.final_action_date;
    var spouseFAD = spouseData.final_action_date;
    var applicantLbl = fadLabel(applicantFAD);
    var spouseLbl = fadLabel(spouseFAD);

    // Verified-data caveat if either side's bulletin data is not yet verified.
    var caveat = "";
    if (applicantData.verified === false) {
      caveat += " (Note: " + countryLabel(c) + " bulletin data is not yet independently verified. Confirm against travel.state.gov.)";
    }
    if (spouseData.verified === false) {
      caveat += " (Note: " + countryLabel(s) + " bulletin data is not yet independently verified. Confirm against travel.state.gov.)";
    }

    if (fadRank(spouseFAD) > fadRank(applicantFAD)) {
      // Spouse's country is more current — cross-chargeability HELPS.
      return '<div class="result-block" style="border-left:4px solid var(--best);background:var(--best-bg);">' +
        '<h3 style="color:var(--best-text);"><span class="num" style="background:var(--card);color:var(--best-text);">*</span>Cross-chargeability may apply</h3>' +
        '<p style="margin:0;color:var(--best-text);">Your spouse\'s country of birth (' + esc(countryLabel(s)) + ') has a more current Final Action Date for ' + esc(cat) + ' (' + esc(spouseLbl) + ') than your country (' + esc(countryLabel(c)) + ', ' + esc(applicantLbl) + '). Under INA §202(b) you may be able to charge your case to ' + esc(countryLabel(s)) + ', which could shorten your wait significantly. Requirements are strict (both spouses as beneficiaries, marriage exists at visa availability). Discuss with your immigration attorney before assuming this applies.' + esc(caveat) + '</p>' +
        '</div>';
    }

    // Spouse's country is not more current — does not help in this direction.
    return '<div class="result-block" style="border-left:4px solid var(--amber-accent);background:var(--amber-bg);">' +
      '<h3 style="color:var(--amber-accent);"><span class="num" style="background:var(--card);color:var(--amber-accent);">*</span>Cross-chargeability note</h3>' +
      '<p style="margin:0;color:var(--amber-text);">Your spouse\'s country of birth (' + esc(countryLabel(s)) + ', ' + esc(spouseLbl) + ') is not more current than your country (' + esc(countryLabel(c)) + ', ' + esc(applicantLbl) + ') for ' + esc(cat) + '. Cross-chargeability under INA §202(b) generally does not help you in this direction.' + esc(caveat) + '</p>' +
      '</div>';
  }

  function niwFrameBlock() {
    if (!hasDetail("degree")) return "";
    var v = state.degree;
    if (v === "us-masters" || v === "foreign-masters") {
      return '<p><strong>NIW eligibility.</strong> You likely meet the base EB-2 requirement for NIW. Whether NIW is worth pursuing depends on your evidence (publications, patents, national-interest impact). Not all L5s qualify.</p>';
    }
    if (v === "us-bach-5" || v === "foreign-bach-5") {
      return '<p><strong>NIW eligibility.</strong> EB-2 eligibility via "progressive experience" is fact-specific. NIW self-petition is possible but the evidence bar is meaningful.</p>';
    }
    return "";
  }

  // ---- Location verdict helper (personalized banner above the matrix) ----
  function locationVerdictBlock() {
    if (state.locCurrent == null || state.locProspective == null) return "";
    var current = findMetro(state.locCurrent);
    var prospective = findMetro(state.locProspective);
    if (!current || !prospective) return "";

    var html = '<div class="comparison-card" id="location-verdict">';
    if (current.msa) {
      html += '<div class="comparison-row"><strong>Current:</strong> ' + esc(current.label) + ', ' + esc(current.state) + ' &middot; MSA: ' + esc(current.msa) + '</div>';
    } else {
      html += '<div class="comparison-row"><strong>Current:</strong> ' + esc(current.label) + '</div>';
    }
    if (prospective.msa) {
      html += '<div class="comparison-row"><strong>Prospective:</strong> ' + esc(prospective.label) + ', ' + esc(prospective.state) + ' &middot; MSA: ' + esc(prospective.msa) + '</div>';
    } else {
      html += '<div class="comparison-row"><strong>Prospective:</strong> ' + esc(prospective.label) + '</div>';
    }
    html += '</div>';

    if (current.id === "other" || prospective.id === "other") {
      html += '<div class="verdict-banner same-state-different-msa"><div class="head">Cannot compute an MSA verdict</div>' +
        'You picked "Other" for one of your locations, so we can\'t compute an MSA verdict. Look up the US Census MSA for both locations manually, or ask your immigration attorney.</div>';
      return html;
    }

    if (current.msa === prospective.msa) {
      html += '<div class="verdict-banner same-msa"><div class="head">Same MSA: lower likelihood of a PERM location impact</div>' +
        'Both locations are in the same MSA (' + esc(current.msa) + '). A same-MSA move usually does not raise a PERM location issue on its own. Other changes (title, duties, wage) can still matter, so confirm with your immigration attorney before accepting. See the "Change location within same MSA" row below for what still applies at each stage.</div>';
    } else if (current.state === prospective.state) {
      html += '<div class="verdict-banner same-state-different-msa"><div class="head">Same state, DIFFERENT MSAs: potentially a material location change</div>' +
        'Both locations are in the same state (' + esc(current.state) + '), but they are in different MSAs (' + esc(current.msa) + ' vs ' + esc(prospective.msa) + '). A common mistake is assuming "same state = no impact." The test is the MSA, not the state line, so two cities in the same state can be different MSAs and may be treated as a location change. Confirm the MSA for both addresses. See the "Change location to different MSA (same state)" row below.</div>';
    } else {
      html += '<div class="verdict-banner different-msa"><div class="head">Different state: likely a material location change. Discuss with counsel before proceeding</div>' +
        'These are different MSAs in different states (' + esc(current.msa) + ' vs ' + esc(prospective.msa) + '). A move to a different MSA/state is usually treated as a material change (see 20 CFR §656.3 and Matter of Simeio Solutions) and often requires reassessment of the PERM and petition. The exact impact (amendment vs. refiling, and whether your priority date is affected) depends on your case stage; review with an immigration attorney. See the "Different state" row below for the impact at each stage.</div>';
    }
    return html;
  }

  // ---- Internal move impact matrix (scenario x process-stage) ----
  // Determine which process-stage column the user is currently in, from PERM + I-140 answers.
  // Returns a column index 0-4, or -1 if not determinable.
  function currentStageColumn() {
    // H-1B/L-1 pre-PERM path: no PERM/I-140 questions are asked, and the
    // applicable stage is unambiguously "Now (PERM not yet filed)".
    if (state.category === "PRE") return 0;
    var perm = state.perm, i140 = state.i140;
    // I-140 approved -> "After I-140 approved" column (index 3), regardless of PERM answer.
    if (i140 === "approved") return 3;
    // I-140 filed/pending or RFE -> also past I-140 filing; treat as "After PERM certified (before I-140)"
    // only if not yet approved. Pending I-140 implies PERM was approved.
    if (i140 === "pending-regular" || i140 === "pending-premium" || i140 === "rfe") return 2;
    // PERM approved (and I-140 not yet filed) -> "After PERM certified (before I-140)" (index 2)
    if (perm === "approved") return 2;
    // Anything in progress (PWD, labor market test, ETA 9089 filed, audited) -> "After ETA 9089 filed" (index 1)
    if (perm === "pwd" || perm === "lmt" || perm === "filed" || perm === "audited") return 1;
    // PERM not filed -> "Now" (index 0)
    if (perm === "not-filed") return 0;
    // No usable PERM/I-140 answer.
    return -1;
  }

  // 8 rows x 5 columns of matrix cells. Each cell: {cls, label, body}.
  // De-identified per instructions; legal substance ported faithfully from the reference doc.
  var IMPACT_COLS = [
    { title: "Now", sub: "(PERM not yet filed)" },
    { title: "After ETA 9089 filed", sub: "(before PERM certified)" },
    { title: "After PERM certified", sub: "(before I-140)" },
    { title: "After I-140 approved", sub: "(before I-485)" },
    { title: "After I-485 pending 180+ days", sub: "(AC21 §106(c))" }
  ];

  var IMPACT_ROWS = [
    {
      scenario: "Same-level &rarr; next-level promotion", note: "(same job family, in-line)",
      cells: [
        { cls: "safe", label: "Lower likelihood of impact", body: "Usually no new filings if duties, title, location and wage stay the same. If any change materially, an amendment may be needed. Confirm with your attorney." },
        { cls: "warn", label: "Attorney review", body: "Your immigration attorney confirms duties overlap; no re-file. <strong>I-129 amendment</strong> if title/wage changes materially." },
        { cls: "warn", label: "Attorney review", body: "Same as prior column; your attorney sanity-checks before I-140 files. <strong>I-129 amendment</strong> if material change." },
        { cls: "safe", label: "Lower likelihood of impact (PD usually preserved)", body: "<strong>No new PERM, no new I-140.</strong> With an approved I-140, the priority date can usually be preserved, but an I-129 amendment may be needed if title or wage changes materially. Confirm with your attorney." },
        { cls: "safe", label: "Lower likelihood of impact under AC21 if the new role is in the same or a similar SOC", body: "<strong>Supplement J (Confirmation of Bona Fide Job Offer / Form I-485J)</strong> attesting the new job is \"same or similar\" SOC (Standard Occupational Classification)." }
      ]
    },
    {
      scenario: "Team change", note: "(same title, same location, same duties)",
      cells: [
        { cls: "safe", label: "Lower likelihood of impact", body: "Usually no new filings if duties, title, location and wage stay the same. If any change materially, an amendment may be needed. Confirm with your attorney." },
        { cls: "safe", label: "Lower likelihood of impact", body: "No filings. Team assignment isn't a PERM factor." },
        { cls: "safe", label: "Lower likelihood of impact", body: "No filings." },
        { cls: "safe", label: "Lower likelihood of impact", body: "<strong>None</strong> if title, duties, location, wage stay the same. Simple internal transfer." },
        { cls: "safe", label: "Lower likelihood of impact", body: "<strong>Supplement J</strong> if any title/duty change; otherwise nothing." }
      ]
    },
    {
      scenario: "Job role / family change", note: "(e.g. Engineer &rarr; Manager, or a different job family)",
      cells: [
        { cls: "warn", label: "Delays PERM", body: "A role/location/entity change at this stage often requires re-doing PERM steps, and because the I-140 is not yet approved the priority date may not be preserved. The exact impact depends on your SOC and case stage. Have an attorney assess before you move. <strong>New PWD &rarr; new labor market test &rarr; new ETA 9089.</strong> New Priority Date." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "A role/location/entity change at this stage often requires re-doing PERM steps, and because the I-140 is not yet approved the priority date may not be preserved. The exact impact depends on your SOC and case stage. Have an attorney assess before you move. <strong>Restart from the PWD stage.</strong> Priority date will be the new filing date." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Certified PERM is now moot. <strong>Restart PERM at new role.</strong> Old PD not yet attached. Lost." },
        { cls: "warn", label: "Restart, PD saved", body: "Requires <strong>new PWD &rarr; new PERM &rarr; new I-140</strong> for the new role. Priority date (PD) SURVIVES via <em>AC21 (American Competitiveness in the Twenty-First Century Act) §104(c)</em> porting once new I-140 approves. Adds ~15-20 months. Also <strong>I-129 amendment</strong>. Stay in current role until new I-140 approves." },
        { cls: "warn", label: "Supp J review", body: "Depends on SOC code. <strong>Supplement J</strong> if same/similar SOC. If different SOC &rarr; new PERM/I-140 needed but <strong>I-485 stays intact</strong>." }
      ]
    },
    {
      scenario: "Change location within same MSA", note: "(e.g. Seattle &rarr; Bellevue, same Seattle-Tacoma-Bellevue MSA)",
      cells: [
        { cls: "safe", label: "Lower likelihood of impact", body: "Same MSA = same \"area of intended employment.\" No PERM or LCA impact. Confirm with your immigration attorney that the new address is in-MSA." },
        { cls: "safe", label: "Lower likelihood of impact", body: "Same MSA = the certified worksite still covers the new address. No PERM re-file, no LCA re-file." },
        { cls: "safe", label: "Lower likelihood of impact", body: "Same MSA is covered by the certified PERM. No filings required." },
        { cls: "safe", label: "Lower likelihood of impact (same MSA)", body: "No new PERM, no new I-140, no I-129 amendment required. Same MSA falls within the certified \"area of intended employment\" per 20 CFR §655.715." },
        { cls: "safe", label: "Lower likelihood of impact under AC21 if the new role is in the same or a similar SOC", body: "No Supplement J needed for a same-MSA move alone." }
      ]
    },
    {
      scenario: "Change location to different MSA", note: "(e.g. San Francisco &rarr; San Jose, different MSA, same state)",
      cells: [
        { cls: "warn", label: "New PWD/LMT", body: "Different MSA is a material change per <em>Matter of Simeio</em>. Full <strong>new PWD + new labor market test + new ETA 9089</strong> at the new MSA. New Priority Date." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Pending PERM is location-specific. Withdraw and refile at new MSA. <strong>Restart PWD/PERM.</strong> A role/location/entity change at this stage often requires re-doing PERM steps, and because the I-140 is not yet approved the priority date may not be preserved. The exact impact depends on your SOC and case stage. Have an attorney assess before you move." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Certified PERM location is fixed to the original MSA. <strong>Restart PERM at new MSA.</strong> PD not yet locked (no approved I-140). Lost." },
        { cls: "warn", label: "Restart, PD saved", body: "Requires <strong>new PWD &rarr; new PERM &rarr; new I-140</strong> at the new MSA. Priority date SURVIVES via <em>AC21 §104(c)</em>. Adds ~15-20 months. Also <strong>I-129 amendment with new LCA</strong> must be filed <strong>BEFORE the move</strong>, per <em>Matter of Simeio Solutions</em> (2015 AAO)." },
        { cls: "safe", label: "Lower likelihood of impact under AC21 if the new role is in the same or a similar SOC", body: "Portability may cover this move once the I-485 has been pending 180+ days, if the new job is \"same or similar.\" Whether it qualifies is a legal judgment. Confirm with your attorney (Supplement J / Form I-485J may be required). <strong>Supplement J</strong> for the new worksite." }
      ]
    },
    {
      scenario: "Different state", note: "(e.g. Seattle &rarr; Austin, different state)",
      cells: [
        { cls: "warn", label: "New PWD/LMT", body: "New state, new wage. Full <strong>new PWD + labor market test + PERM</strong> at the new location." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "A role/location/entity change at this stage often requires re-doing PERM steps, and because the I-140 is not yet approved the priority date may not be preserved. The exact impact depends on your SOC and case stage. Have an attorney assess before you move. <strong>Restart at the new location.</strong>" },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Certified PERM location is fixed. <strong>Restart PERM at the new location.</strong> PD not yet locked." },
        { cls: "warn", label: "Restart, PD saved", body: "Requires <strong>new PWD</strong> (new state has different wage) <strong>&rarr; new PERM &rarr; new I-140</strong> at new location. Priority date SURVIVES via <em>AC21 §104(c)</em>. Adds ~15-20 months. Also <strong>I-129 amendment with new LCA</strong> for the new worksite. Your employer might amend existing I-140 if new location's wage is compliant. Ask your immigration attorney." },
        { cls: "safe", label: "Lower likelihood of impact under AC21 if the new role is in the same or a similar SOC", body: "Portability may cover this move once the I-485 has been pending 180+ days, if the new job is \"same or similar.\" Whether it qualifies is a legal judgment. Confirm with your attorney (Supplement J / Form I-485J may be required). <strong>Supplement J.</strong>" }
      ]
    },
    {
      scenario: "Employer entity switch", note: "(e.g. parent company &rarr; a subsidiary or affiliate)",
      cells: [
        { cls: "warn", label: "Restart at new entity", body: "New entity is a new sponsor. Full <strong>new PWD, PERM, I-140</strong> at the new entity. Also new H-1B petition." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Current PERM belongs to the original legal entity and dies with the entity change." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Certified PERM is tied to the original legal entity. <strong>Restart at the new entity.</strong> PD not yet locked." },
        { cls: "warn", label: "Restart, PD saved", body: "Requires <strong>new PERM &rarr; new I-140</strong> at the new entity. Priority date SURVIVES via <em>AC21 §104(c)</em>. Adds ~15-20 months. Also <strong>new H-1B petition (I-129) from the new entity</strong>. Effectively a new employer for immigration purposes, even within the same corporate group." },
        { cls: "safe", label: "Lower likelihood of impact under AC21 if the new role is in the same or a similar SOC", body: "Portability may cover this move once the I-485 has been pending 180+ days, if the new job is \"same or similar.\" Whether it qualifies is a legal judgment. Confirm with your attorney (Supplement J / Form I-485J may be required). <strong>Supplement J</strong> naming the new entity as employer." }
      ]
    },
    {
      scenario: "Combination", note: "(e.g. promotion + location + entity together)",
      cells: [
        { cls: "warn", label: "Full restart", body: "Every trigger from the role, location, and entity rows combined. Full <strong>new PWD, PERM, I-140, I-129.</strong>" },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Kills PERM. Full restart at new (role, location, entity)." },
        { cls: "danger", label: "Discuss with counsel before proceeding", body: "Certified PERM dies. Full restart." },
        { cls: "warn", label: "Restart, PD saved", body: "Everything from the role, location, or entity rows combined. <strong>New PWD, new PERM, new I-140, I-129 amendment.</strong> ~15-20 months added. Priority date survives via AC21 §104(c)." },
        { cls: "safe", label: "Lower likelihood of impact under AC21 if the new role is in the same or a similar SOC", body: "Portability may cover this move once the I-485 has been pending 180+ days, if the new job is \"same or similar.\" Whether it qualifies is a legal judgment. Confirm with your attorney (Supplement J / Form I-485J may be required). <strong>Supplement J.</strong>" }
      ]
    }
  ];

  // Risk score for each row: count danger cells. Higher = riskier.
  function impRiskScore(row) {
    var score = 0;
    row.cells.forEach(function(c) { if (c.cls === "danger") score += 2; else if (c.cls === "warn") score += 1; });
    return score;
  }
  // Risk score for a row in a specific column only.
  function impColRisk(row, col) {
    if (col < 0 || col >= row.cells.length) return 0;
    var c = row.cells[col];
    if (c.cls === "danger") return 3;
    if (c.cls === "warn") return 2;
    return 0;
  }

  // Print / Save-as-PDF button. Native window.print(); the @media print styles
  // stamp the output with unavoidable NOT-LEGAL-ADVICE disclaimers + watermark.
  function printButtonHtml() {
    return '<button type="button" class="print-btn" onclick="window.print()">Print / Save as PDF</button>';
  }

  function impactMatrixSection(num) {
    var here = currentStageColumn(); // 0-4 or -1
    var isPre = state.category === "PRE";
    // Pre-PERM users start focused on the "Now" column, with an opt-in to see later stages.
    var focusNow = isPre;
    var html = '<div class="result-block" id="location-matrix">';
    html += '<h3><span class="num">' + num + '</span>Internal Move Impact Matrix</h3>';
    html += '<p class="help" style="margin-top:0;">Rows are the type of internal move you\'re considering. Columns are when in the green card process the move happens. Each cell shows the immigration impact and the paperwork it triggers. <strong>Click any row to expand details.</strong></p>';

    // Pre-PERM framing + explore-the-rest toggle.
    if (isPre) {
      html += '<p class="imp-note" style="border-left-color:var(--primary-600);">You haven\'t started PERM yet, so this column, <strong>Now (PERM not yet filed)</strong>, is where you are today. Here\'s how an internal move would affect you right now.</p>';
      html += '<button type="button" class="imp-explore-toggle" id="imp-explore-toggle" aria-expanded="false">See how an internal move affects you at each later stage (once PERM starts) &rarr;</button>';
    }

    // Personalized location verdict banner sits ABOVE the full matrix.
    html += locationVerdictBlock();

    // Sort controls
    html += '<div class="imp-sort-bar">';
    html += '<span class="imp-sort-label">Sort by:</span>';
    html += '<button class="imp-sort-btn active" data-sort="risk-asc">Least risky</button>';
    html += '<button class="imp-sort-btn" data-sort="risk-desc">Most risky</button>';
    html += '<button class="imp-sort-btn" data-sort="alpha">A-Z</button>';
    if (here >= 0) html += '<button class="imp-sort-btn" data-sort="relevance">Relevance to me</button>';
    html += '</div>';

    // The full matrix (desktop).
    html += '<div class="imp-matrix-wrap">';
    html += '<table class="imp-matrix' + (focusNow ? ' imp-focus-now' : '') + '" aria-label="Internal move impact by process stage" id="imp-matrix-table">';
    html += '<thead><tr><th class="imp-scenario-col" scope="col">Type of move</th>';
    IMPACT_COLS.forEach(function (col, ci) {
      var cls = (ci === here) ? ' class="imp-col-here"' : '';
      html += '<th' + cls + ' scope="col">' + col.title + '<small>' + col.sub + '</small>';
      if (ci === here) html += '<span class="imp-here-tag">You are here</span>';
      html += '</th>';
    });
    html += '</tr></thead><tbody id="imp-matrix-body">';

    // Sort rows by risk (least first) for default render.
    var sortedIndices = IMPACT_ROWS.map(function(_, i) { return i; });
    sortedIndices.sort(function(a, b) { return impRiskScore(IMPACT_ROWS[a]) - impRiskScore(IMPACT_ROWS[b]); });

    sortedIndices.forEach(function (ri) {
      var row = IMPACT_ROWS[ri];
      html += '<tr data-row-idx="' + ri + '" tabindex="0" aria-expanded="false"' +
        ' onclick="this.setAttribute(\'aria-expanded\', this.classList.toggle(\'imp-expanded\'))"' +
        ' onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();this.setAttribute(\'aria-expanded\', this.classList.toggle(\'imp-expanded\'));}">';
      html += '<td class="imp-scenario" scope="row"><span class="imp-row-toggle">&#9654;</span>' + row.scenario + '<small>' + row.note + '</small></td>';
      row.cells.forEach(function (cell, ci) {
        var icon = cell.cls === "safe" ? "&#10003;" : (cell.cls === "warn" ? "&#9888;" : "&#10007;");
        var tdCls = "imp-cell " + cell.cls + (ci === here ? " imp-col-here" : "");
        html += '<td class="' + tdCls + '">';
        html += '<div class="imp-cell-head"><span class="imp-cell-icon">' + icon + '</span><span class="imp-cell-label">' + cell.label + '</span></div>';
        html += '<div class="imp-cell-body">' + cell.body + '</div>';
        html += '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';

    // Mobile card layout
    html += '<div class="imp-mobile-cards' + (focusNow ? ' imp-focus-now' : '') + '" id="imp-mobile-cards">';
    sortedIndices.forEach(function(ri) {
      var row = IMPACT_ROWS[ri];
      html += '<div class="imp-mobile-card" data-row-idx="' + ri + '">';
      html += '<div class="imp-mobile-card-title">' + row.scenario + '</div>';
      html += '<div class="imp-mobile-card-note">' + row.note + '</div>';
      row.cells.forEach(function(cell, ci) {
        var icon = cell.cls === "safe" ? "&#10003;" : (cell.cls === "warn" ? "&#9888;" : "&#10007;");
        var hereCls = (ci === here) ? " here" : "";
        html += '<div class="imp-mobile-card-stage' + hereCls + '">';
        html += '<span class="imp-mobile-stage-name">' + IMPACT_COLS[ci].title + '</span>';
        html += '<span class="imp-mobile-stage-badge ' + cell.cls + '">' + icon + ' ' + cell.label + '</span>';
        html += '</div>';
      });
      html += '</div>';
    });
    html += '</div>';

    // Legend
    html += '<div class="imp-legend">';
    html += '<div class="imp-legend-item safe"><strong>&#10003; Lower likelihood of impact</strong>: usually little or no immigration impact on its own. Paperwork may still be needed. Not a guarantee; confirm specifics.</div>';
    html += '<div class="imp-legend-item warn"><strong>&#9888; Needs review / Potentially material</strong>: often needs new filings or an attorney sanity-check. Where a role or process restart is involved the change can be material, though the priority date can usually be preserved. Confirm for your case.</div>';
    html += '<div class="imp-legend-item danger"><strong>&#10007; Discuss with counsel before proceeding</strong>: in some situations the priority date may be at risk and the process re-started. Attorney review needed.</div>';
    html += '</div>';

    // "You are here" note only when the PERM/I-140 questions ARE askable but
    // unanswered (EB paths). Never for pre-PERM (auto-focused on "Now") or F-1.
    if (here === -1 && !isPre && state.category !== "F-1") {
      html += '<p class="imp-note">Answer the PERM and I-140 status questions to see which column applies to you.</p>';
    }

    html += '</div>';
    return html;
  }

  function restartRoleBlock() {
    if (!hasDetail("roleChange")) return "";
    var v = state.roleChange;
    var msg = "";
    if (v === "none") {
      msg = "With no role change planned, the main PERM restart triggers (employing entity, work location outside the MSA, or a duty change over 50%) are not in play. Re-check before accepting any future move.";
    } else if (v === "same-track") {
      msg = "A promotion that keeps you in the same discipline with the same duties usually does not trigger a PERM restart. What matters legally is whether the duties change materially, not the title or level. Confirm with your attorney before accepting.";
    } else if (v === "ic-to-manager") {
      msg = "A move from individual contributor to manager is typically a duty shift over 50%, which usually does trigger a PERM restart. Whether it affects yours depends on your specific duties and how the role was described on the ETA 9089. Have an immigration attorney assess the change before you accept.";
    } else if (v === "different-family") {
      msg = "Moving into a different job family or function is likely to be a material change in duties, which usually triggers a PERM restart and a new priority date. Get a written assessment from immigration counsel before accepting.";
    }
    if (!msg) return "";
    return '<p style="margin-top:8px;font-size:12.5px;"><strong>Your role change:</strong> ' + esc(msg) + '</p>';
  }

  // ---- F-1 OPT/STEM Results ----
  function renderF1Results() {
    var country = state.country;
    var optExpiry = state.optExpiry;
    var lottery = state.h1bLottery;
    var h = "";

    // Header
    h += '<div class="result-block" style="border-top:4px solid var(--purple)">';
    h += '<div class="step-num">Your situation</div>';
    h += '<h2 style="margin:4px 0 8px;font-size:22px;letter-spacing:-0.4px;">F-1 OPT/STEM · ' + esc(countryLabel(country)) + '</h2>';
    h += '<p class="help" style="margin:0;">You haven\'t started the green card process yet. Here\'s your timeline and path options.</p>';
    h += '</div>';

    // Timeline section
    h += '<div class="result-block">';
    h += '<h3><span class="num">1</span>Your Timeline</h3>';
    if (optExpiry) {
      var today = new Date();
      var expiry = new Date(optExpiry);
      var diffMs = expiry - today;
      var monthsLeft = Math.max(0, Math.round(diffMs / (1000 * 60 * 60 * 24 * 30)));
      var lotteryChances = Math.min(3, Math.ceil(monthsLeft / 12));
      h += '<div class="status-banner ' + (monthsLeft > 12 ? "current" : "unavailable") + '">';
      h += '<div class="head">OPT expires: ' + esc(fmtDate(optExpiry)) + '</div>';
      h += 'You have approximately <strong>' + monthsLeft + ' months</strong> remaining. ';
      if (monthsLeft <= 6) {
        h += '<strong style="color:var(--error-600);">Urgent:</strong> Less than 6 months left. You need a plan NOW.';
      } else if (monthsLeft <= 12) {
        h += 'Time is getting tight. Make sure you\'re registered for the next H-1B lottery (March).';
      } else {
        h += 'You have time, but start planning early.';
      }
      h += '</div>';
      h += '<div class="enrichment" style="margin-top:12px;"><div class="head">H-1B lottery windows remaining: ~' + lotteryChances + '</div>';
      h += 'The H-1B lottery registration opens each March. With ' + monthsLeft + ' months of OPT left, you can enter approximately ' + lotteryChances + ' lottery cycle(s). Selection rate is roughly 30% per attempt.</div>';
    } else {
      h += '<div class="status-banner waiting"><div class="head">OPT expiry not provided</div>';
      h += 'Enter your OPT expiry date above to see a personalized timeline.</div>';
    }
    h += '</div>';

    // Path Options
    h += '<div class="result-block">';
    h += '<h3><span class="num">2</span>Your Path Options</h3>';
    h += '<p class="help">Ranked by typical fit. Your best option depends on your qualifications and employer.</p>';

    // H-1B lottery
    var lotteryHighlight = (!lottery || lottery === "not-selected" || lottery === "not-applied");
    h += '<div class="enrichment" style="border-left-color:' + (lotteryHighlight ? "var(--primary-600)" : "var(--success-600)") + ';">';
    h += '<div class="head">Option 1: H-1B via Lottery</div>';
    if (lottery === "selected") {
      h += '<p style="color:var(--success-600);font-weight:600;">You\'ve been selected. Your employer files the H-1B petition. Once on H-1B, the PERM green card process can begin.</p>';
    } else {
      h += '<p>Register each March through your employer. ~30% selection rate. If selected, H-1B starts October 1.</p>';
      h += '<p><strong>Timeline:</strong> Register (March) → Selection (March-April) → Start (Oct 1) → Then employer can begin PERM for green card.</p>';
    }
    h += '</div>';

    // Cap-exempt
    h += '<div class="enrichment"><div class="head">Option 2: Cap-Exempt H-1B (No Lottery)</div>';
    h += '<p>If your employer is a university, non-profit, or government research org, you don\'t need the lottery at all. H-1B is filed directly and approved based on merit.</p>';
    h += '<p><strong>Key:</strong> Only the employer matters, not your field. Working AT a university qualifies even if your role isn\'t academic.</p>';
    h += '</div>';

    // O-1
    h += '<div class="enrichment"><div class="head">Option 3: O-1 Visa (Extraordinary Ability)</div>';
    h += '<p>Alternative to H-1B with no lottery and no annual cap. Requires evidence of extraordinary ability (awards, publications, high salary, critical role). Higher bar than H-1B but no luck involved.</p>';
    h += '</div>';

    // EB-1A / NIW
    h += '<div class="enrichment"><div class="head">Option 4: Skip H-1B Entirely → Direct Green Card</div>';
    h += '<p><strong>EB-1A (Extraordinary Ability):</strong> Self-petition, no employer or PERM needed. If you have publications, patents, media coverage, or awards, you may qualify. File I-140 directly.</p>';
    h += '<p><strong>EB-2 NIW (National Interest Waiver):</strong> Self-petition, no PERM needed. Requires advanced degree + work of national importance. Same EB-2 queue applies (';
    // Show queue for their country
    var eb2Data = rulebook.bulletin.categories["EB-2"] ? rulebook.bulletin.categories["EB-2"][country] : null;
    if (eb2Data && eb2Data.final_action_date) {
      h += 'currently serving ' + esc(fmtDate(eb2Data.final_action_date));
    } else if (eb2Data && eb2Data.final_action_date === null) {
      h += 'currently unavailable for ' + esc(countryLabel(country));
    }
    h += ').</p>';
    h += '</div>';

    // Standard PERM path
    h += '<div class="enrichment"><div class="head">Option 5: Standard Employer-Sponsored Green Card (PERM → I-140)</div>';
    h += '<p>The most common path: get on H-1B first, then employer files PERM labor certification → I-140 → wait for priority date to become current → I-485.</p>';
    h += '<p><strong>Total timeline for ' + esc(countryLabel(country)) + ':</strong> ';
    if (country === "India") {
      h += 'PERM filing (~15-25 months) + EB-2/EB-3 queue (~10-15+ years). This is the reality of the India backlog.';
    } else if (country === "China") {
      h += 'PERM filing (~15-25 months) + EB-2 queue (~5-8 years).';
    } else {
      h += 'PERM filing (~15-25 months) + queue is typically Current for your country (no additional wait).';
    }
    h += '</p></div>';

    if (lottery === "not-selected") {
      h += '<div class="status-banner unavailable" style="margin-top:12px;"><div class="head">Not selected in H-1B lottery</div>';
      h += 'Consider Options 2-4 above as alternatives. You can also re-enter the lottery next March. If your OPT is expiring soon, explore O-1 or a cap-exempt employer to maintain status.</div>';
    }
    h += '</div>';

    // Key dates
    h += '<div class="result-block">';
    h += '<h3><span class="num">3</span>Key Dates &amp; Deadlines</h3>';
    h += '<div class="enrichment"><div class="head">Critical deadlines to track</div>';
    h += '<ul style="margin:8px 0 0;padding-left:18px;">';
    h += '<li><strong>H-1B registration:</strong> Opens early March each year. Your employer must register you.</li>';
    h += '<li><strong>STEM OPT extension:</strong> Must apply BEFORE your initial OPT expires. Recommended: file 90 days early.</li>';
    h += '<li><strong>60-day grace period:</strong> After OPT expires, you have 60 days to find a new employer, change status, or depart.</li>';
    h += '<li><strong>E-Verify requirement:</strong> Your employer MUST be E-Verify enrolled for STEM OPT.</li>';
    h += '<li><strong>Training plan (I-983):</strong> Must be signed by employer before STEM OPT starts. Updated at 12 and 24 months.</li>';
    h += '</ul></div>';
    h += '</div>';

    // Queue preview
    h += '<div class="result-block">';
    h += '<h3><span class="num">4</span>Queue Preview: If You Eventually File for a Green Card</h3>';
    h += '<p class="help">This is what the green card queue looks like today for ' + esc(countryLabel(country)) + '. It shows where you\'d stand if you started the PERM process now.</p>';
    var cats = ["EB-1", "EB-2", "EB-3"];
    h += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:12px;">';
    for (var ci = 0; ci < cats.length; ci++) {
      var c = cats[ci];
      var d = rulebook.bulletin.categories[c] ? rulebook.bulletin.categories[c][country] : null;
      h += '<div style="background:var(--card);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;">';
      h += '<div style="font-weight:700;font-size:14px;margin-bottom:6px;">' + esc(c) + '</div>';
      if (d) {
        if (d.final_action_date === "CURRENT") {
          h += '<div style="color:var(--success-600);font-weight:600;">Current (no wait)</div>';
        } else if (d.final_action_date === null) {
          h += '<div style="color:var(--error-600);font-weight:600;">Unavailable</div>';
          if (d.date_for_filing) h += '<div style="font-size:12px;color:var(--muted);">DFF: ' + esc(fmtDate(d.date_for_filing)) + '</div>';
        } else {
          h += '<div>FAD: ' + esc(fmtDate(d.final_action_date)) + '</div>';
          var fadMs = parseIsoToMs(d.final_action_date);
          var nowMs = Date.now();
          if (fadMs) {
            var yrsBack = Math.round((nowMs - fadMs) / (365.25 * 24 * 60 * 60 * 1000));
            h += '<div style="font-size:12px;color:var(--muted);">~' + yrsBack + ' year wait if filed today</div>';
          }
        }
      } else {
        h += '<div style="color:var(--muted);">No data</div>';
      }
      h += '</div>';
    }
    h += '</div>';
    h += '</div>';

    return h;
  }

  // ---- H-1B / L-1, PERM-not-started: forward-planning results ----
  function renderPrePermResults() {
    var country = state.country;
    var visa = state.preVisa || "H-1B";
    var year = (state.preYear && state.preYear !== "skip") ? parseInt(state.preYear, 10) : null;
    var intent = state.preIntent || "unsure";
    var projCat = (intent === "EB-2" || intent === "EB-3") ? intent : "EB-2";
    var isL1 = (visa === "L-1A" || visa === "L-1B");
    var cap = visa === "L-1A" ? 7 : visa === "L-1B" ? 5 : 6;
    var visaLabel = visa === "L-1A" ? "L-1A" : visa === "L-1B" ? "L-1B" : "H-1B";
    var h = "";

    // Header
    h += '<div class="result-block" style="border-top:4px solid var(--purple)">';
    h += '<div class="step-num">Your situation</div>';
    h += '<h2 style="margin:4px 0 8px;font-size:22px;letter-spacing:-0.4px;">' + esc(visaLabel) + ' · ' + esc(countryLabel(country)) + ' · green card not started</h2>';
    h += '<p class="help" style="margin:0;">You don\'t have a priority date yet, so there\'s no queue position to show. This is a forward-looking plan: how much visa runway you have, when to start PERM, and what the wait would look like if you filed today.</p>';
    h += '</div>';

    // 1. Status runway
    h += '<div class="result-block">';
    h += '<h3><span class="num">1</span>Your Status Runway</h3>';
    if (visa === "H-1B") {
      h += '<div class="status-banner ' + (year && year >= 5 ? "waiting" : "current") + '"><div class="head">H-1B: 6-year cap</div>';
      if (year) {
        var remH = Math.max(0, cap - year);
        h += 'You\'re in <strong>year ' + year + '</strong> of 6, so roughly <strong>' + remH + ' year' + (remH === 1 ? "" : "s") + '</strong> of H-1B time remain before the cap.';
      } else {
        h += 'H-1B is capped at 6 years total.';
      }
      h += '</div>';
      h += '<div class="plain-explain"><div class="pe-label">Why this matters</div>Once your PERM has been pending 365+ days (AC21 §106(a)) or your I-140 is approved (AC21 §104(c)), you can extend H-1B past the 6-year cap indefinitely while you wait in the green-card queue. The trick is to start PERM early enough that those protections kick in <em>before</em> year 6. Otherwise your status can lapse.</div>';
    } else {
      h += '<div class="status-banner ' + (year && year >= cap - 1 ? "unavailable" : "waiting") + '"><div class="head">' + esc(visaLabel) + ': ' + cap + '-year maximum</div>';
      if (year) {
        var remL = Math.max(0, cap - year);
        h += 'You\'re in <strong>year ' + year + '</strong> of ' + cap + ', so roughly <strong>' + remL + ' year' + (remL === 1 ? "" : "s") + '</strong> of ' + esc(visaLabel) + ' time remain.';
      } else {
        h += esc(visaLabel) + ' is capped at ' + cap + ' years total.';
      }
      h += '</div>';
      h += '<div class="plain-explain"><div class="pe-label">Why this is urgent for L-1</div><strong>AC21 extensions apply to H-1B, not L-1.</strong> L-1 cannot be extended past its ' + cap + '-year maximum. So before you hit that cap you need EITHER an approved I-140 (which lets you keep going toward the green card) OR a switch to H-1B. That makes starting PERM early even more important on L-1 than on H-1B.</div>';
      if (visa === "L-1A") {
        h += '<div class="enrichment" style="margin-top:12px;"><div class="head">L-1A managers: EB-1C may be your fastest path</div>';
        h += 'As an L-1A manager/executive you already meet the core EB-1C test (a year abroad with the company, coming into a managerial/executive role). EB-1C requires <strong>no PERM</strong> and its queue is usually years ahead of EB-2/EB-3 ' + esc(countryLabel(country)) + '. Worth raising with your immigration attorney.</div>';
      }
    }
    h += '</div>';

    // 2. When to start PERM
    h += '<div class="result-block">';
    h += '<h3><span class="num">2</span>When to Start PERM</h3>';
    var perm = rulebook.perm || {};
    var permMonths = perm.total_duration_months;
    h += '<p class="help">PERM itself takes time before your priority date even locks. Currently about ' + (permMonths ? fmtBand(permMonths) + ' months' : 'a year or two') + ' from PWD to a filed ETA 9089.</p>';
    if (rulebook.ac21 && rulebook.ac21.optimal_perm_timing) {
      h += '<div class="enrichment"><div class="head">Optimal timing</div>' + esc(rulebook.ac21.optimal_perm_timing) + '</div>';
    }
    // Personalized nudge based on visa + year
    h += '<div class="next-steps-card"><div class="ns-head">Your timing read</div>';
    if (isL1) {
      h += '<span class="ns-action">Start PERM (or the EB-1C I-140) as soon as possible.</span> On ' + esc(visaLabel) + ' there\'s no AC21 safety net, so the green card process needs to be well underway before your ' + cap + '-year cap. If you\'re past the halfway mark, treat this as time-critical and talk to your attorney now.';
    } else if (year && year >= 4) {
      h += '<span class="ns-action">Start PERM now. You\'re at year ' + year + '.</span> To keep H-1B from lapsing at the 6-year cap you want §106(a) to unlock (PERM pending 365+ days) before then. Every month of delay narrows that window.';
    } else if (year && year >= 3) {
      h += '<span class="ns-action">This is the ideal window to start.</span> Filing PERM around year 3 means §106(a) unlocks around year 4, so your H-1B never lapses during the multi-year wait.';
    } else {
      h += '<span class="ns-action">You have runway, but plan ahead.</span> Filing PERM around H-1B year 3 is the sweet spot. Starting earlier is fine; starting late (year 5+) risks a gap at the 6-year cap.';
    }
    h += '</div>';
    h += adviceNote("general");
    h += '</div>';

    // 3. Projection: if PERM were filed today
    h += '<div class="result-block">';
    h += '<h3><span class="num">3</span>If Your PERM Were Filed Today</h3>';
    h += '<p class="help">You don\'t have a priority date yet. This is a <strong>forward-looking projection</strong>: where you\'d enter the ' + esc(projCat) + ' ' + esc(countryLabel(country)) + ' queue if PERM were filed now. It is not a current position.' + (intent === "unsure" ? ' (Assuming EB-2 since you weren\'t sure.)' : '') + '</p>';
    var projData = effectiveCountryData(projCat, country);
    if (projData) {
      if (projData.final_action_date === "CURRENT") {
        h += '<div class="status-banner current"><div class="head">' + esc(projCat) + ' ' + esc(countryLabel(country)) + ': Current</div>No backlog for your country. Once PERM + I-140 are approved you could file I-485 right away.</div>';
      } else if (projData.final_action_date == null) {
        h += '<div class="status-banner unavailable"><div class="head">' + esc(projCat) + ' ' + esc(countryLabel(country)) + ': Unavailable this month</div>All visa numbers for this fiscal year are used up (resets October 1). Even with a priority date you couldn\'t be approved right now. The Date for Filing cutoff is ' + esc(fadLabel(projData.date_for_filing)) + '.</div>';
      } else {
        h += '<div class="status-banner waiting"><div class="head">' + esc(projCat) + ' ' + esc(countryLabel(country)) + ' is serving priority dates around ' + esc(fmtDate(projData.final_action_date)) + '</div>';
        var gap = diffYearsMonths(new Date().toISOString().slice(0, 10), projData.final_action_date);
        if (gap) {
          h += 'A priority date filed today sits roughly <strong>' + gap.years + ' years ' + gap.months + ' months</strong> behind the current cutoff.';
        }
        h += '</div>';
      }
    } else {
      h += '<div class="status-banner unknown"><div class="head">No bulletin data</div>We don\'t have ' + esc(projCat) + ' ' + esc(countryLabel(country)) + ' in the rulebook. Check the current bulletin at ' + extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "travel.state.gov") + '.</div>';
    }
    // Wait band
    var bandKey1 = projCat + " " + (country === "ROW" ? "" : country) + ", PD locked 2026";
    var bandData = rulebook.wait_estimates.bands[bandKey1] || rulebook.wait_estimates.bands[projCat + " " + country + ", PD locked 2026"];
    if (bandData) {
      h += '<div class="wait-bands" style="margin-top:12px;">';
      h += '<div class="wait-band best"><div class="label">Best case</div><div class="years">' + fmtBand(bandData.best_case_years) + '</div><div class="years-sub">years</div></div>';
      h += '<div class="wait-band typical"><div class="label">Typical</div><div class="years">' + fmtBand(bandData.typical_case_years) + '</div><div class="years-sub">years</div></div>';
      h += '<div class="wait-band worst"><div class="label">Worst case</div><div class="years">' + fmtBand(bandData.worst_case_years) + '</div><div class="years-sub">years</div></div>';
      h += '</div>';
      h += '<p class="band-caveat" style="margin-top:8px;">Projected total wait once a priority date is locked. This is on top of the PERM + I-140 time above. Ranges are structural. Legislative changes to per-country caps are the main thing that moves them.</p>';
    } else {
      h += '<p class="help" style="margin-top:8px;">For ' + esc(countryLabel(country)) + ', ' + esc(projCat) + ' is typically Current or a short wait. The multi-year backlog mainly affects India and China.</p>';
    }
    h += '</div>';

    // 4. How to start
    h += '<div class="result-block">';
    h += '<h3><span class="num">4</span>How to Get PERM Started</h3>';
    h += '<div class="next-steps-card"><div class="ns-head">Concrete next step</div>';
    h += '<span class="ns-action">Talk to your immigration counsel / HR about initiating PERM.</span> ';
    h += 'At most large employers this starts with an internal case intake through HR. ';
    h += 'Your employer\'s immigration attorney prepares the PWD request, runs the recruitment (labor market test), and files the ETA 9089. The day DOL receives it is your priority date.';
    h += '</div>';
    h += '<p class="help" style="margin-top:8px;">If counsel is unresponsive, ask HR how to escalate an immigration case — most large employers have a defined path.</p>';
    h += adviceNote();
    h += '</div>';

    return h;
  }

  // ---- Result rendering ----
  // ============================================================
  // PASTE-IN & ANALYZE
  // The tool never fetches the bot-blocked federal sites. Instead the USER
  // opens them in their own browser, copies the relevant text, and pastes it
  // here; these functions parse it DETERMINISTICALLY in client-side JS (no
  // network, no LLM, nothing saved) and drive what the tool shows next.
  // ============================================================

  var MON_NUM = { JAN:"01", FEB:"02", MAR:"03", APR:"04", MAY:"05", JUN:"06",
                  JUL:"07", AUG:"08", SEP:"09", OCT:"10", NOV:"11", DEC:"12" };
  // Column order of the Visa Bulletin employment-based table.
  var COUNTRY_COL = { ROW: 0, China: 1, India: 2, Mexico: 3, Philippines: 4 };
  // Regex that recognizes a preference row for each category, across the
  // Employment-Based (1st-5th) and Family-Sponsored (F1-F4) bulletin tables.
  var PREF_RE = {
    "EB-1": /\b(1ST|FIRST)\b/, "EB-2": /\b(2ND|SECOND)\b/, "EB-3": /\b(3RD|THIRD)\b/,
    "EB-4": /\b(4TH|FOURTH)\b/, "EB-5": /\b(5TH|FIFTH)\b/,
    "F1": /\bF1\b/, "F2A": /\bF2A\b/, "F2B": /\bF2B\b/, "F3": /\bF3\b/, "F4": /\bF4\b/
  };

  // The Visa Timeline Explorer picker (tools.html). Every value maps to a "kind"
  // that decides which timeline cards render:
  //   eb     - employment green-card category: Visa Bulletin reader + consular + IV
  //   family - family-sponsored category:      Visa Bulletin reader (family table) + consular + IV
  //   niv    - nonimmigrant work visa:         per-visa timeline card + consular (no bulletin, no IV)
  // `row` is the preference-row label as it appears in the bulletin; `table` picks
  // the Employment-Based vs Family-Sponsored chart; `baseline` flags whether the
  // rulebook ships built-in dates for it (only EB-1/2/3 do today).
  var VISA_TYPES = {
    "EB-1": { kind: "eb", table: "employment", row: "1st", label: "EB-1 (1st Preference)", baseline: true },
    "EB-2": { kind: "eb", table: "employment", row: "2nd", label: "EB-2 (2nd Preference)", baseline: true },
    "EB-3": { kind: "eb", table: "employment", row: "3rd", label: "EB-3 (3rd Preference)", baseline: true },
    "EB-4": { kind: "eb", table: "employment", row: "4th", label: "EB-4 (4th Preference)", baseline: false },
    "EB-5": { kind: "eb", table: "employment", row: "5th", label: "EB-5 (5th Preference)", baseline: false },
    "F1":  { kind: "family", table: "family", row: "F1",  label: "F1 (Family 1st Preference)", baseline: false },
    "F2A": { kind: "family", table: "family", row: "F2A", label: "F2A (Family 2nd Preference, Spouses/Children)", baseline: false },
    "F2B": { kind: "family", table: "family", row: "F2B", label: "F2B (Family 2nd Preference, Adult Children)", baseline: false },
    "F3":  { kind: "family", table: "family", row: "F3",  label: "F3 (Family 3rd Preference)", baseline: false },
    "F4":  { kind: "family", table: "family", row: "F4",  label: "F4 (Family 4th Preference)", baseline: false },
    "H-1B": { kind: "niv", label: "H-1B" },
    "L-1":  { kind: "niv", label: "L-1" },
    "O-1":  { kind: "niv", label: "O-1" },
    "F-1":  { kind: "niv", label: "F-1 / OPT" },
    "TN":   { kind: "niv", label: "TN" }
  };
  function visaType(cat) { return VISA_TYPES[cat] || { kind: "eb", table: "employment", row: "your", baseline: false }; }

  // A single bulletin cell token -> our internal value.
  // "C" -> "CURRENT"; "U" -> null (unavailable, a VALID value); a DDMONYY date
  // -> ISO "YYYY-MM-DD". Anything else -> undefined (not a cell token).
  function bulletinToken(tok) {
    tok = String(tok).toUpperCase().replace(/[.,]$/, "");
    if (tok === "C") return "CURRENT";
    if (tok === "U") return null;
    var m = tok.match(/^(\d{1,2})([A-Z]{3})(\d{2,4})$/);
    if (m) {
      var mon = MON_NUM[m[2]];
      if (!mon) return undefined;
      var d = m[1].length === 1 ? "0" + m[1] : m[1];
      var yr = m[3];
      if (yr.length === 2) yr = (parseInt(yr, 10) <= 60 ? "20" : "19") + yr;
      return yr + "-" + mon + "-" + d;
    }
    return undefined;
  }

  // From one text region (e.g. the Final Action chart), find the preference row
  // for `cat` and return the cell value for `country`'s column. Requires the row
  // to expose all five country columns so the column mapping is unambiguous.
  function extractBulletinCell(regionText, cat, country) {
    if (!regionText) return { found: false };
    var colIdx = COUNTRY_COL[country];
    if (colIdx == null) return { found: false };
    var prefRe = PREF_RE[cat];
    if (!prefRe) return { found: false };
    var lines = regionText.split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var up = lines[i].toUpperCase();
      if (up.indexOf("OTHER WORKERS") !== -1) continue; // distinct EB-3 sub-row
      if (!prefRe.test(up)) continue;
      var cells = [];
      up.split(/[\s\t]+/).forEach(function (t) {
        if (!t) return;
        var v = bulletinToken(t);
        if (v !== undefined) cells.push(v); // includes null (U) and "CURRENT"
      });
      if (cells.length === 5) return { found: true, value: cells[colIdx], line: lines[i].trim() };
      // Tolerate a trailing "Other Workers"-free 6-cell shape only if the first 5 look right
      if (cells.length === 6) return { found: true, value: cells[colIdx], loose: true, line: lines[i].trim() };
    }
    return { found: false };
  }

  // pdf.js emits bulletin dates with stray spaces inside them: the cell "01SEP21"
  // comes out of the PDF text layer as "01 SEP 2 1". The whitespace tokenizer in
  // extractBulletinCell can't reassemble that, so rows fail to parse. This glues a
  // day + 3-letter month + 2 year digits back into "DDMONYY", regardless of the
  // stray spaces pdf.js inserted. Safe on already-clean pasted text (a well-formed
  // "01SEP21" is matched and re-emitted unchanged).
  function normalizePdfDates(text) {
    var MON = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC";
    var re = new RegExp("(\\d{1,2})\\s*(" + MON + ")\\s*(\\d)\\s*(\\d)(?!\\d)", "gi");
    return String(text).replace(re, function (_m, d, mon, a, b) {
      return d + mon.toUpperCase() + a + b;
    });
  }

  // Parse a pasted Visa Bulletin. Splits Final Action Dates vs Dates for Filing
  // regions, extracts the user's category+country cell from each, and detects the
  // bulletin month/year if present.
  function parseVisaBulletin(raw, cat, country, tableKind) {
    if (!raw || !raw.trim()) return { ok: false, error: "empty" };
    // Glue PDF-split dates first so both the drop-a-PDF and paste-text paths agree.
    var text = normalizePdfDates(raw);
    var up = text.toUpperCase();
    var isFamily = tableKind === "family";
    // The FULL bulletin PDF contains BOTH the Family-Sponsored and Employment-Based
    // charts. Scope to the headers for the chart this category lives in so we don't
    // slice on the wrong section. If the user pasted only the rows (no headers),
    // fall back to the generic first-"Dates for Filing" split. (The preference-row
    // regexes also disambiguate: F1-F4 never match 1st-5th, and vice-versa.)
    var faHdrRe  = isFamily ? /FINAL\s+ACTION\s+DATES\s+FOR\s+FAMILY/ : /FINAL\s+ACTION\s+DATES\s+FOR\s+EMPLOYMENT/;
    var dffHdrRe = isFamily ? /DATES?\s+FOR\s+FILING\s+(?:OF\s+|FOR\s+)?FAMILY/ : /DATES?\s+FOR\s+FILING\s+OF\s+EMPLOYMENT/;
    var empFa = up.search(faHdrRe);
    var empDff = up.search(dffHdrRe);
    var faRegion, dffRegion, dffIdx;
    if (empFa !== -1 || empDff !== -1) {
      var faStart = empFa !== -1 ? empFa : 0;
      if (empDff !== -1 && empDff > faStart) { faRegion = text.slice(faStart, empDff); dffRegion = text.slice(empDff); }
      else if (empDff !== -1) { dffRegion = text.slice(empDff, faStart); faRegion = text.slice(faStart); }
      else { faRegion = text.slice(faStart); dffRegion = ""; }
      dffIdx = empDff;
    } else {
      dffIdx = up.search(/DATES?\s+FOR\s+FILING/);
      if (dffIdx !== -1) { faRegion = text.slice(0, dffIdx); dffRegion = text.slice(dffIdx); }
      else { faRegion = text; dffRegion = ""; }
    }

    var fa = extractBulletinCell(faRegion, cat, country);
    var dff = extractBulletinCell(dffRegion, cat, country);
    // If there was no "Dates for Filing" region at all, a single chart was
    // pasted; treat it as Final Action unless the text clearly says filing-only.
    if (dffIdx === -1) { dff = { found: false }; }

    var monthLabel = null;
    var mm = up.match(/\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{4})\b/);
    if (mm) {
      monthLabel = mm[1].charAt(0) + mm[1].slice(1).toLowerCase() + " " + mm[2];
    }

    if (!fa.found && !dff.found) {
      var tableName = isFamily ? "Family-Sponsored table" : "Employment-Based table";
      return { ok: false, error: "no-row",
               msg: "Couldn't find a " + cat + " row with all five country columns. Copy the full " + cat + " row (or the whole " + tableName + ") including the All-Chargeability, China, India, Mexico, and Philippines columns." };
    }
    return {
      ok: true,
      fadFound: fa.found, fad: fa.found ? fa.value : undefined,
      dffFound: dff.found, dff: dff.found ? dff.value : undefined,
      faLine: fa.line, dffLine: dff.line,
      monthLabel: monthLabel
    };
  }

  // Turn a pasted wait-time snippet into a day count. Accepts days, weeks,
  // months, and years, whole or decimal, singular/plural or abbreviated:
  // "45", "45 days", "6 weeks", "1.5 months", "18 mos", "2 years", "1 yr".
  // Bare numbers are treated as days. Returns integer days or null.
  function parseWaitDays(raw) {
    if (!raw) return null;
    var s = String(raw).toLowerCase().replace(/,/g, "").trim();
    // Longest-first alternation so "months" isn't matched as "mo".
    var m = s.match(/(\d+(?:\.\d+)?)\s*(years?|yrs?|months?|mos?|weeks?|wks?|days?|d|w|y)?\b/);
    if (!m) return null;
    var n = parseFloat(m[1]);
    if (isNaN(n)) return null;
    var u = m[2] || "day";
    if (u[0] === "y") n = n * 365;
    else if (u[0] === "m") n = n * 30;      // month / mo (not matched to year, which starts with y)
    else if (u[0] === "w") n = n * 7;
    // else days (d / day / bare number)
    return Math.round(n);
  }

  // Render a day count as a human-friendly duration for display.
  function formatWaitDuration(days) {
    if (days == null) return "";
    if (days < 14) return days + (days === 1 ? " day" : " days");
    if (days < 60) {
      var wk = Math.round(days / 7);
      return "about " + wk + (wk === 1 ? " week" : " weeks");
    }
    if (days < 365) {
      var mo = Math.round(days / 30 * 10) / 10;
      return "about " + mo + (mo === 1 ? " month" : " months");
    }
    var yr = Math.round(days / 365 * 10) / 10;
    return "about " + yr + (yr === 1 ? " year" : " years");
  }

  function labelForBulletinValue(v, missing) {
    if (v === undefined) return missing || "(unchanged)";
    if (v === "CURRENT") return "Current";
    if (v === null) return "Unavailable";
    return fmtDate(v);
  }

  // Effective bulletin cell for a category+country: the user's pasted override
  // takes precedence over the built-in rulebook data when it matches.
  function effectiveCountryData(cat, country) {
    var catData = rulebook.bulletin.categories[cat];
    var base = catData ? catData[country] : null;
    var ov = state.bulletinOverride;
    if (ov && ov.cat === cat && ov.country === country) {
      var eff = {};
      if (base) { for (var k in base) { if (Object.prototype.hasOwnProperty.call(base, k)) eff[k] = base[k]; } }
      if (ov.fadFound) eff.final_action_date = ov.fad;
      if (ov.dffFound) eff.date_for_filing = ov.dff;
      eff.verified = true;
      eff._overridden = true;
      eff.status_note = "Using dates you pasted from the " + (ov.monthLabel || "latest") +
        " Visa Bulletin, verified by you against travel.state.gov.";
      return eff;
    }
    return base;
  }

  var BULLETIN_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html";
  // Nonimmigrant (e.g. H-1B) visa STAMPING appointment wait times.
  var WAITTIME_URL = "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/global-visa-wait-times.html";
  // Immigrant Visa (IV) interview scheduling status by post — a DIFFERENT thing:
  // how far behind NVC is scheduling green-card interviews at a given consulate.
  var IV_URL = "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/iv-wait-times.html";

  // Build the direct State Dept bulletin PDF URL for the newest LIKELY-published
  // bulletin, from today's date. Pattern:
  //   .../Bulletins/visabulletin_{FullMonthName}{Year}.pdf  (e.g. visabulletin_August2026.pdf)
  // Links to the CURRENT calendar month's bulletin (the one in effect now) — e.g.
  // in August it links to the August bulletin, not September. The current month's
  // bulletin is always already published, so the direct link is reliable; the index
  // page is offered as a fallback if a user wants a different/newer month. A plain
  // anchor href the USER clicks — no fetch from the tool (cross-origin + Cloudflare).
  var MONTH_FULL = ["January","February","March","April","May","June","July",
                    "August","September","October","November","December"];
  function latestBulletinPdf(today) {
    var d = today || new Date();
    var y = d.getUTCFullYear();
    var m = d.getUTCMonth(); // 0-11 = current calendar month
    var label = MONTH_FULL[m] + " " + y;
    var url = "https://travel.state.gov/content/dam/visas/Bulletins/visabulletin_" +
              MONTH_FULL[m] + y + ".pdf";
    return { url: url, label: label };
  }

  // ---- pdf.js (lazy, CDN + SRI) for the "drop the PDF" path ----
  // Pinned pdfjs-dist 3.11.174 on cdnjs, integrity-checked. Loaded ONLY when the
  // user actually drops/selects a PDF, so a user who never uses PDF mode makes
  // zero external requests. The user's PDF is parsed in-browser and never leaves
  // the device; only this library is fetched from the CDN.
  var PDFJS_SRC = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
  var PDFJS_SRI = "sha384-/1qUCSGwTur9vjf/z9lmu/eCUYbpOTgSjmpbMQZ1/CtX2v/WcAIKqRv+U1DUCG6e";
  var PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  var PDFJS_WORKER_SRI = "sha384-SnzOobpRMLXZ52iJvZm/C0fYw0OQemTXzTjIsdsfMcrCtCEe9qgzxTd3RSklO5x2";
  var _pdfjsPromise = null;
  function loadPdfJs() {
    if (_pdfjsPromise) return _pdfjsPromise;
    _pdfjsPromise = new Promise(function (resolve, reject) {
      if (window.pdfjsLib) { resolve(window.pdfjsLib); return; }
      var s = document.createElement("script");
      s.src = PDFJS_SRC;
      s.integrity = PDFJS_SRI;
      s.crossOrigin = "anonymous";
      s.referrerPolicy = "no-referrer";
      s.onload = function () {
        if (!window.pdfjsLib) { reject(new Error("pdfjs-not-available")); return; }
        try { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; } catch (e) {}
        resolve(window.pdfjsLib);
      };
      s.onerror = function () { _pdfjsPromise = null; reject(new Error("pdfjs-load-failed")); };
      document.head.appendChild(s);
    });
    return _pdfjsPromise;
  }

  // Reconstruct pdftotext-style layout from a pdf.js page: group text items into
  // lines by their y-coordinate, order each line left-to-right by x, join with
  // spaces. This yields text the existing table parser can read line-by-line.
  function pageItemsToText(textContent) {
    var lines = [];
    (textContent.items || []).forEach(function (it) {
      var str = (it.str || "");
      if (!str) return;
      var tr = it.transform || [1, 0, 0, 1, 0, 0];
      var x = tr[4], y = tr[5];
      var line = null;
      for (var i = 0; i < lines.length; i++) {
        if (Math.abs(lines[i].y - y) <= 3) { line = lines[i]; break; }
      }
      if (!line) { line = { y: y, parts: [] }; lines.push(line); }
      line.parts.push({ x: x, str: str });
    });
    lines.sort(function (a, b) { return b.y - a.y; }); // PDF y grows upward
    return lines.map(function (ln) {
      ln.parts.sort(function (a, b) { return a.x - b.x; });
      return ln.parts.map(function (p) { return p.str; }).join(" ");
    }).join("\n");
  }

  // Extract all text from an in-memory PDF ArrayBuffer via pdf.js.
  function extractPdfText(arrayBuffer) {
    return loadPdfJs().then(function (pdfjsLib) {
      return pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    }).then(function (pdf) {
      var pageTexts = [];
      var chain = Promise.resolve();
      for (var p = 1; p <= pdf.numPages; p++) {
        (function (pageNum) {
          chain = chain.then(function () {
            return pdf.getPage(pageNum).then(function (page) {
              return page.getTextContent().then(function (tc) {
                pageTexts.push(pageItemsToText(tc));
              });
            });
          });
        })(p);
      }
      return chain.then(function () { return pageTexts.join("\n"); });
    });
  }

  // Detect when the user pasted a URL/link instead of table text.
  function looksLikeUrl(s) {
    var t = String(s || "").trim();
    if (!t || /\s.*\s/.test(t) && t.split(/\s+/).length > 3) {
      // multi-word text (a table) is not a bare URL
    }
    if (/^https?:\/\/\S+$/i.test(t)) return true;
    if (/^www\.\S+$/i.test(t) && t.split(/\s+/).length === 1) return true;
    // A lone travel.state.gov / visabulletin link even without scheme
    if (t.split(/\s+/).length <= 2 && /(travel\.state\.gov|visabulletin)/i.test(t) && !/\d{1,2}[A-Z]{3}\d{2}/i.test(t.toUpperCase())) return true;
    return false;
  }
  function extractFirstUrl(s) {
    var m = String(s || "").match(/https?:\/\/\S+/i);
    return m ? m[0] : null;
  }

  function pasteDisclaimer(kind) {
    if (kind === "bulletin") {
      return '<p class="paste-disclaimer">This reads only what you paste or the PDF you drop in. Your input is processed entirely in your browser and is never uploaded or saved. (PDF mode loads a small reader library from a public CDN the first time; your file never leaves your device.) Always confirm against the official source linked above. Not legal advice.</p>';
    }
    return '<p class="paste-disclaimer">This reads only the numbers you paste in. It does not fetch anything and nothing is saved. Always confirm against the official source linked above. Not legal advice.</p>';
  }

  // Per-visa timeline facts for the nonimmigrant work-visa cards. Concise,
  // verifiable, and paired with the "how the green card fits" note. Not advice.
  var NIV_INFO = {
    "H-1B": {
      title: "H-1B: Specialty Occupation",
      points: [
        "Granted in up to 3-year increments, <strong>6 years maximum</strong> on the base status.",
        "Cap-subject roles go through the <strong>annual lottery</strong>: registration each March, roughly a 30% selection rate in recent years, an October 1 start if selected. Universities, non-profits, and government research orgs are <strong>cap-exempt</strong> (no lottery).",
        "Past the 6-year cap: <strong>AC21 extensions</strong> keep you in status while a green card is pending: 1-year extensions once a PERM has been pending 365+ days (§106(a)), 3-year extensions once an I-140 is approved (§104(c)).",
        "<strong>Dual intent</strong> is allowed, so pursuing a green card does not jeopardize H-1B."
      ],
      gc: "EB-1, EB-2, or EB-3"
    },
    "L-1": {
      title: "L-1: Intracompany Transfer",
      points: [
        "Requires 1 continuous year with the company abroad in the prior 3 years.",
        "<strong>L-1A</strong> (managers &amp; executives) has a <strong>7-year maximum</strong>; <strong>L-1B</strong> (specialized knowledge) a <strong>5-year maximum</strong>.",
        "<strong>No lottery and no annual cap.</strong>",
        "<strong>Dual intent</strong> is allowed. L-1A pairs naturally with the <strong>EB-1C</strong> green card, which skips PERM."
      ],
      gc: "EB-1 (often EB-1C for L-1A), EB-2, or EB-3"
    },
    "O-1": {
      title: "O-1: Extraordinary Ability",
      points: [
        "Initial grant of up to 3 years, then <strong>1-year extensions with no fixed maximum</strong> as long as the work continues.",
        "<strong>No lottery and no annual cap.</strong>",
        "Dual intent is tolerated in practice.",
        "Pairs naturally with the <strong>EB-1A</strong> green card (self-petition, no employer or PERM required)."
      ],
      gc: "EB-1 (often EB-1A), or EB-2 NIW"
    },
    "F-1": {
      title: "F-1 / OPT: Student &amp; Work Authorization",
      points: [
        "<strong>12 months of OPT</strong> after graduation; a STEM degree adds a <strong>24-month STEM OPT extension</strong>, for 36 months of work authorization in total.",
        "OPT is the bridge to H-1B: you get up to <strong>3 lottery cycles</strong> during it, with cap-gap protection if selected.",
        "You can also go <strong>directly to a green card</strong> via EB-1A or EB-2 NIW (both skip H-1B and PERM) if your credentials support it."
      ],
      gc: "EB-1A or EB-2 NIW directly, or EB-2 / EB-3 after H-1B"
    },
    "TN": {
      title: "TN: USMCA Professional (Canada / Mexico)",
      points: [
        "For Canadian and Mexican citizens in qualifying professions under USMCA (formerly NAFTA).",
        "Granted in up to 3-year increments, <strong>renewable indefinitely</strong>, with no cap and no lottery.",
        "<strong>Not a dual-intent visa.</strong> Actively pursuing a green card can jeopardize TN renewals and re-entry. Plan the switch (usually to H-1B) with an attorney <em>before</em> filing green-card paperwork."
      ],
      gc: "EB-2 or EB-3 (usually after moving to H-1B first)"
    }
  };

  // Context card shown at the top of the Visa Timeline Explorer for the chosen
  // visa/path. For green-card categories it frames the bulletin reader below;
  // for work visas it IS the timeline (they aren't in the bulletin).
  function visaContextBlock(cat, country) {
    var vt = visaType(cat);
    var h = '<div class="result-block">';
    if (vt.kind === "niv") {
      var info = NIV_INFO[cat] || { title: cat, points: [], gc: "an employment category" };
      h += '<h3><span class="num">i</span>' + info.title + '</h3>';
      if (cat === "F-1") {
        h += '<p class="paste-map" style="margin-top:0;">Heads up on the letter &ldquo;F&rdquo;: this <strong>F-1</strong> is the <strong>student visa</strong>. It is a different thing from the family green-card categories <strong>F1 / F2A / F2B / F3 / F4</strong> (listed under Green card). Same letter, unrelated.</p>';
      }
      h += '<p class="help" style="margin-top:0;">This is a <strong>nonimmigrant ' + (cat === "F-1" ? "student" : "work") + ' visa</strong>. It is <strong>not in the Visa Bulletin</strong> and has no priority-date queue. Its timeline is about how long you can stay and how you extend it:</p>';
      h += '<ul style="margin:8px 0 0 18px;font-size:14px;line-height:1.6;">';
      info.points.forEach(function (p) { h += '<li>' + p + '</li>'; });
      h += '</ul>';
      h += '<div class="enrichment" style="margin-top:14px;"><div class="head">How the green card fits</div>';
      h += 'A green card is a separate, immigrant process. When you pursue one you will file under an employment category, likely <strong>' + esc(info.gc) + '</strong>. Switch the picker above to that category to read its current Visa Bulletin queue. The consular stamping estimator below applies to your ' + esc(vt.label || cat) + ' visa.</div>';
      h += '<p class="paste-disclaimer" style="margin-top:12px;">General information, not legal advice. Rules and timelines change. Verify with official sources (uscis.gov, travel.state.gov) and check with your employer&rsquo;s immigration counsel or a licensed immigration attorney before making any decisions.</p>';
    } else {
      var isFamily = vt.table === "family";
      h += '<h3><span class="num">i</span>' + esc(vt.label || cat) + '</h3>';
      if (isFamily) {
        h += '<p class="help" style="margin-top:0;">This is a <strong>family-sponsored green-card category</strong>. Your place in line is set by your <strong>priority date</strong> (the day the I-130 petition was filed) against the monthly <strong>Family-Sponsored</strong> Visa Bulletin cutoffs, a separate chart from the employment one. Read the current cutoffs for your category and country below.</p>';
        h += '<p class="paste-map" style="margin-top:0;">Heads up on the letter &ldquo;F&rdquo;: <strong>' + esc(cat) + '</strong> here is a <strong>family green-card category</strong>. That is a different thing from the <strong>F-1 student visa</strong> (listed under Work visas). Same letter, unrelated.</p>';
      } else {
        h += '<p class="help" style="margin-top:0;">This is an <strong>employment-based green-card category</strong>. Your place in line is set by your <strong>priority date</strong> (for EB-2/EB-3, the day your PERM was filed; for EB-1, the day your I-140 was filed) against the monthly Visa Bulletin cutoffs. Read the current cutoffs for your category and country below.</p>';
      }
      if (!vt.baseline) {
        h += '<div class="enrichment" style="margin-top:12px;"><div class="head">No built-in dates for ' + esc(cat) + ' yet</div>';
        h += 'The tool ships verified built-in cutoffs for EB-1, EB-2, and EB-3. For ' + esc(cat) + ', read your row straight from the bulletin using the reader below.</div>';
      }
      h += '<p class="paste-disclaimer" style="margin-top:12px;">General information, not legal advice. Verify against the official Visa Bulletin and consult a licensed immigration attorney.</p>';
    }
    h += '</div>';
    return h;
  }

  // Card: paste a newer Visa Bulletin to override the queue dates.
  // ---- Opt-in "remember bulletins on this device" (month-over-month diff) ----
  // OFF by default. Stores ONLY public bulletin cutoffs, keyed by the chosen
  // category+country, in this browser — never transmitted, never the priority date.
  function vbRememberOn() {
    try { return localStorage.getItem('gc_remember_bulletins') === '1'; } catch (e) { return false; }
  }
  function vbSetRemember(on) {
    try {
      if (on) { localStorage.setItem('gc_remember_bulletins', '1'); }
      else { localStorage.removeItem('gc_remember_bulletins'); localStorage.removeItem('gc_vb_history'); }
    } catch (e) {}
  }
  function vbHistoryClear() { try { localStorage.removeItem('gc_vb_history'); } catch (e) {} }
  function vbHistoryGet() {
    try { return JSON.parse(localStorage.getItem('gc_vb_history') || '{}') || {}; } catch (e) { return {}; }
  }
  function vbLatest(cat, country) {
    var arr = vbHistoryGet()[cat + '|' + country];
    return (arr && arr.length) ? arr[arr.length - 1] : null;
  }
  function vbMaybeSave(cat, country, res) {
    if (!vbRememberOn() || !res || !res.ok) return;
    try {
      var h = vbHistoryGet(), key = cat + '|' + country, arr = h[key] || [];
      var entry = { month: res.monthLabel || null,
                    fad: res.fadFound ? res.fad : undefined,
                    dff: res.dffFound ? res.dff : undefined,
                    savedAt: Date.now() };
      var last = arr[arr.length - 1];
      if (last && last.month === entry.month && last.fad === entry.fad && last.dff === entry.dff) return;
      arr.push(entry); if (arr.length > 12) arr = arr.slice(-12); h[key] = arr;
      localStorage.setItem('gc_vb_history', JSON.stringify(h));
    } catch (e) {}
  }
  function vbMonthsBetween(a, b) {
    var am = parseIsoToMs(a), bm = parseIsoToMs(b); if (am == null || bm == null) return null;
    var ad = new Date(am), bd = new Date(bm);
    return (bd.getUTCFullYear() - ad.getUTCFullYear()) * 12 + (bd.getUTCMonth() - ad.getUTCMonth());
  }
  function vbHumanMonths(m) {
    if (m >= 12) { var y = Math.floor(m / 12), r = m % 12; return y + (y === 1 ? ' year' : ' years') + (r ? ' ' + r + (r === 1 ? ' month' : ' months') : ''); }
    return m + (m === 1 ? ' month' : ' months');
  }
  function vbCellDiff(prev, cur) {
    if (prev === undefined || cur === undefined) return null;
    var isDate = function (v) { return typeof v === 'string' && /^\d{4}-/.test(v); };
    if (isDate(prev) && isDate(cur)) {
      var m = vbMonthsBetween(prev, cur);
      if (m === 0) return { text: 'unchanged at ' + fmtDate(cur), retro: false };
      if (m > 0) return { text: 'advanced ' + vbHumanMonths(m) + ' (' + fmtDate(prev) + ' → ' + fmtDate(cur) + ')', retro: false };
      return { text: 'retrogressed ' + vbHumanMonths(-m) + ' (' + fmtDate(prev) + ' → ' + fmtDate(cur) + ')', retro: true };
    }
    if (isDate(prev) && cur === null) return { text: 'went Unavailable (was ' + fmtDate(prev) + ')', retro: true };
    if (prev === null && isDate(cur)) return { text: 'reopened to ' + fmtDate(cur), retro: false };
    if (isDate(prev) && cur === 'CURRENT') return { text: 'became Current', retro: false };
    if (prev === 'CURRENT' && isDate(cur)) return { text: 'retrogressed from Current to ' + fmtDate(cur), retro: true };
    if (prev === 'CURRENT' && cur === 'CURRENT') return { text: 'still Current', retro: false };
    if (prev === null && cur === null) return { text: 'still Unavailable', retro: false };
    return null;
  }
  function vbDiffHtml(cat, country, res) {
    var prior = vbLatest(cat, country);
    if (!prior) return '';
    var curFad = res.fadFound ? res.fad : undefined, curDff = res.dffFound ? res.dff : undefined;
    if (prior.month && res.monthLabel && prior.month === res.monthLabel && prior.fad === curFad && prior.dff === curDff) return '';
    var fad = vbCellDiff(prior.fad, curFad), dff = vbCellDiff(prior.dff, curDff);
    if (!fad && !dff) return '';
    var retro = (fad && fad.retro) || (dff && dff.retro);
    var parts = [];
    if (fad) parts.push('Final Action Date ' + fad.text);
    if (dff) parts.push('Filing date ' + dff.text);
    var since = prior.month ? ('the ' + esc(prior.month) + ' bulletin') : 'the last one you saved';
    return '<div class="vb-diff' + (retro ? ' retro' : '') + '">Since ' + since + ', ' +
      esc(cat) + ' ' + esc(countryLabel(country)) + ': ' + parts.join('; ') + '.</div>';
  }

  function bulletinPasteBlock(cat, country) {
    var vt = visaType(cat);
    if (vt.kind === "niv") return ""; // work visas aren't in the Visa Bulletin
    var isFamily = vt.table === "family";
    var tableName = isFamily ? "Family-Sponsored" : "Employment-Based";
    var ov = state.bulletinOverride;
    var active = ov && ov.cat === cat && ov.country === country;
    var h = '<div class="result-block paste-card" id="bulletin-paste">';
    h += '<h3><span class="num">↺</span>Have a Newer Visa Bulletin? Paste It Here</h3>';
    if (active) {
      h += '<div class="paste-active">';
      h += '<div class="paste-active-head">Override active: using your pasted ' + esc(ov.monthLabel || "latest") + ' bulletin</div>';
      h += '<ul style="margin:8px 0 0 18px;font-size:13px;">';
      if (ov.fadFound) h += '<li>Final Action Date: <strong>' + esc(labelForBulletinValue(ov.fad)) + '</strong></li>';
      if (ov.dffFound) h += '<li>Date for Filing: <strong>' + esc(labelForBulletinValue(ov.dff)) + '</strong></li>';
      h += '</ul>';
      h += '<button type="button" class="paste-btn secondary" id="bp-clear" style="margin-top:12px;">Clear and use built-in data</button>';
      h += '</div>';
    } else {
      var prefLabel = vt.row || "your";
      var builtinNote = vt.baseline
        ? "The built-in dates are refreshed periodically but can lag. Grab the newest numbers straight from the government bulletin and give them to the tool below to recompute your position."
        : "The tool doesn't ship built-in dates for " + esc(cat) + " yet, so read your row straight from the bulletin: open it below, then drop the PDF or paste the table.";
      h += '<p class="help" style="margin-top:0;">' + builtinNote + ' The tool only reads what you provide, it does not fetch anything.</p>';
      var pdf = latestBulletinPdf();
      h += '<p class="paste-label" style="margin-bottom:6px;">Get the latest bulletin:</p>';
      h += '<ol class="paste-steps">';
      h += '<li>' + extLink(pdf.url, "Open the " + esc(pdf.label) + " Visa Bulletin (PDF)") + ', then either <strong>drop that PDF here (Option A)</strong> or <strong>copy the tables (Option B)</strong> below.</li>';
      h += '<li>If the link says <em>not found</em>, the newest month may not be posted yet, so ' + extLink(BULLETIN_URL, "browse all bulletins") + ' and pick the top item.</li>';
      h += '</ol>';
      h += '<p class="help" style="margin:0 0 4px;">On the bulletin, use the two ' + tableName + ' tables: <strong>A. Final Action Dates</strong> and <strong>B. Dates for Filing</strong>.</p>';
      if (isFamily) {
        h += '<div class="paste-map">In the bulletin, find the <strong>Family-Sponsored</strong> charts (they come <em>before</em> the Employment-Based ones). Your category is the <strong>' + esc(prefLabel) + '</strong> row, <strong>' + esc(countryLabel(country)) + '</strong> column.</div>';
      } else {
        h += '<div class="paste-map">In the bulletin, your category is the <strong>preference</strong> row: <strong>1st</strong> = EB-1, <strong>2nd</strong> = EB-2, <strong>3rd</strong> = EB-3, <strong>4th</strong> = EB-4, <strong>5th</strong> = EB-5. You are <strong>' + esc(cat) + '</strong> (the <strong>' + esc(prefLabel) + '</strong> preference row), <strong>' + esc(countryLabel(country)) + '</strong> column.' + (cat === "EB-5" ? ' For EB-5, use the <strong>Unreserved</strong> 5th row unless you are in a set-aside category.' : '') + '</div>';
      }

      // ---- Option A: drop the PDF ----
      h += '<p class="paste-optlabel">Option A: drop the bulletin PDF</p>';
      h += '<div id="bp-drop" class="pdf-drop" tabindex="0" role="button" aria-label="Drop the Visa Bulletin PDF here, or click to choose a file">';
      h += '<div class="pdf-drop-main">Drop the bulletin PDF here</div>';
      h += '<div class="pdf-drop-sub">or click to choose the file you downloaded</div>';
      h += '</div>';
      h += '<input type="file" id="bp-file" accept="application/pdf,.pdf" style="display:none;">';
      h += '<div id="bp-pdf-status" class="pdf-status" style="display:none;"></div>';
      h += '<p class="paste-disclaimer" style="margin-top:8px;">Your PDF is read entirely in your browser and is never uploaded, sent, or saved. The first time you use PDF mode, a small PDF-reading library loads from a public CDN (cdnjs); your PDF file itself never leaves your device.</p>';

      // ---- Option B: paste the table text ----
      h += '<div class="paste-or">or</div>';
      h += '<p class="paste-optlabel">Option B: paste the table text</p>';
      h += '<details class="paste-example"><summary>Show me exactly what to copy</summary>';
      if (isFamily) {
        h += '<pre>A.  FINAL ACTION DATES FOR FAMILY-SPONSORED...\n' +
             'Family-Sponsored  All Chargeability  CHINA  INDIA  MEXICO  PHILIPPINES\n' +
             'F1    01NOV15   01NOV15   01NOV15   01MAR05   01APR12\n' +
             'F2A   01SEP24   01SEP24   01SEP24   15AUG24   01SEP24\n' +
             'F2B   01MAY16   01MAY16   01MAY16   01JUN05   01OCT12\n\n' +
             'B.  DATES FOR FILING FAMILY-SPONSORED...\n' +
             'F1    01SEP17   01SEP17   01SEP17   01JUL06   22APR15\n' +
             'F2A   01OCT24   01OCT24   01OCT24   01OCT24   01OCT24</pre>';
      } else {
        h += '<pre>A.  FINAL ACTION DATES FOR EMPLOYMENT-BASED...\n' +
             'Employment-based  All Chargeability  CHINA  INDIA  MEXICO  PHILIPPINES\n' +
             '1st   C          01JUL23   15OCT22   C   C\n' +
             '2nd   C          01SEP21   U         C   C\n' +
             '3rd   01SEP24    01JAN22   01JAN14   01SEP24   01AUG23\n\n' +
             'B.  DATES FOR FILING OF EMPLOYMENT-BASED...\n' +
             '1st   C   01DEC23   01DEC23   C   C\n' +
             '2nd   C   01JAN22   15JAN15   C   C\n' +
             '3rd   C   08JAN22   15JAN15   C   01JAN24</pre>';
      }
      h += '<p class="help" style="margin:8px 0 0;">Copy the real table, not this example (dates shown are illustrative). The tool reads whatever you paste. Pasting only your one row, or only one of the two tables, still works.</p>';
      h += '</details>';
      h += '<label class="paste-label" for="bp-input">Paste the ' + tableName + ' table (or just your ' + esc(prefLabel) + (isFamily ? '' : '-preference') + ' / ' + esc(countryLabel(country)) + ' row) here:</label>';
      h += '<textarea id="bp-input" class="paste-textarea" rows="6" placeholder="Paste the copied ' + tableName + ' table here, e.g.\n' + (isFamily ? 'F2A   01SEP24   01SEP24   01SEP24   15AUG24   01SEP24' : '2nd   C   01SEP21   U   C   C') + '"></textarea>';
      h += '<button type="button" class="paste-btn" id="bp-parse">Analyze paste</button>';
      h += '<div id="bp-preview" class="paste-preview" style="display:none;"></div>';
    }
    h += '<div class="vb-remember">';
    h += '<label class="vb-remember-lbl"><input type="checkbox" id="vb-remember-cb"' + (vbRememberOn() ? ' checked' : '') + '> Remember these cutoffs on this device, to show month-over-month changes</label>';
    h += ' <button type="button" id="vb-remember-clear" class="vb-clear-link">Clear saved</button>';
    h += '<div class="help" style="margin:4px 0 0;">Stored only in this browser, never sent anywhere. Just public cutoff dates for your category, never your priority date.</div>';
    h += '</div>';
    h += pasteDisclaimer(active ? "default" : "bulletin");
    h += '</div>';
    return h;
  }

  // Card: paste a consulate wait time to get a stamping-timeline estimate.
  // The State Dept global wait-time table splits appointment waits into columns
  // BY VISA CLASS. Tell the user which column to read for their selected visa.
  function waitTimeColumnHint(cat) {
    if (cat === "H-1B" || cat === "L-1" || cat === "O-1") {
      return 'Read the <strong>Petition-Based (H, L, O, P, Q)</strong> column. That covers ' + esc(cat) + '.';
    }
    if (cat === "F-1") {
      return 'Read the <strong>F, M, J</strong> column (students &amp; exchange visitors). That covers the F-1 student visa.';
    }
    if (cat === "TN") {
      return 'The table has <strong>no TN column</strong>. Canadian citizens are visa-exempt and apply at the border (no stamping appointment); Mexican citizens apply at a consulate, so check that post&rsquo;s website, since TN isn&rsquo;t broken out here.';
    }
    // Green-card categories: the stamp is for whatever nonimmigrant status you hold now.
    return 'Read the column for the visa you currently hold: <strong>Petition-Based (H, L, O, P, Q)</strong> for H-1B/L-1/O-1, or <strong>F, M, J</strong> for an F-1.';
  }

  function consularPasteBlock(cat) {
    var h = '<div class="result-block paste-card" id="consular-paste">';
    h += '<h3><span class="num">↺</span>Visa Stamping Wait (Appointment)</h3>';
    h += '<p class="help" style="margin-top:0;">This is the <strong>nonimmigrant visa appointment wait</strong>: how long until you can get a <em>stamping</em> interview slot at a consulate for a work visa (H-1B, L-1, O-1, TN) or an F-1. It is <strong>not</strong> the green-card (immigrant visa) interview wait. Open the official global wait-time page, find your consulate\'s appointment wait, and enter it for a rough stamping-timeline estimate.</p>';
    h += '<p style="margin:0 0 6px;">Step 1: ' + extLink(WAITTIME_URL, "Open the official global visa wait-time page") + '.</p>';
    h += '<div class="paste-map" style="margin-bottom:10px;">' + waitTimeColumnHint(cat) + ' The page shows values like &ldquo;2 Months&rdquo; or &ldquo;&lt; 0.5 Month&rdquo; (a half-month is about 15 days).</div>';
    h += '<div class="paste-row">';
    h += '<label class="paste-label" for="cs-consulate">Consulate</label>';
    h += '<select id="cs-consulate" class="paste-select">';
    ["Mumbai", "New Delhi", "Hyderabad", "Chennai", "Kolkata", "Other"].forEach(function (c) {
      var sel = (state.consular && state.consular.consulate === c) ? " selected" : "";
      h += '<option value="' + esc(c) + '"' + sel + '>' + esc(c) + '</option>';
    });
    h += '</select>';
    h += '</div>';
    h += '<label class="paste-label" for="cs-qty" style="margin-top:10px;">Step 2: enter the number you see, then pick its unit (this avoids typos):</label>';
    h += '<div class="paste-row" style="align-items:center;gap:8px;">';
    h += '<input id="cs-qty" class="paste-input" type="number" min="0" step="0.1" inputmode="decimal" style="max-width:120px;" placeholder="e.g. 1.5"' +
         (state.consular && state.consular.qty != null ? ' value="' + esc(String(state.consular.qty)) + '"' : "") + '>';
    var csUnit = (state.consular && state.consular.unit) || "days";
    h += '<select id="cs-unit" class="paste-select" aria-label="Unit for the wait time you entered" style="max-width:160px;">';
    [["days","days"],["weeks","weeks"],["months","months"],["years","years"]].forEach(function (u) {
      h += '<option value="' + u[0] + '"' + (csUnit === u[0] ? " selected" : "") + '>' + u[1] + '</option>';
    });
    h += '</select>';
    h += '</div>';
    h += '<button type="button" class="paste-btn" id="cs-parse">Estimate timeline</button>';
    h += '<div id="cs-out" class="paste-preview"' + (state.consular ? '' : ' style="display:none;"') + '>';
    if (state.consular) h += consularOutputHtml(state.consular.consulate, state.consular.days);
    h += '</div>';
    h += pasteDisclaimer();
    h += '</div>';
    return h;
  }

  function consularOutputHtml(consulate, days) {
    var now = new Date();
    var target = new Date(now.getTime() + days * 24 * 3600 * 1000);
    var months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    var when = months[target.getUTCMonth()] + " " + target.getUTCDate() + ", " + target.getUTCFullYear();
    var h = '<div class="paste-active-head">Estimate for ' + esc(consulate) + '</div>';
    h += '<p style="margin:8px 0 0;font-size:13.5px;">At a wait of <strong>' + esc(formatWaitDuration(days)) + '</strong>, if you requested an interview appointment today you would interview around <strong>' + esc(when) + '</strong>. This is a rough projection from the number you entered, not a booking.</p>';
    h += '<p style="margin:10px 0 0;font-size:13px;color:var(--text-soft);"><strong>Dropbox (interview waiver):</strong> may let you skip the in-person interview and cut the wait sharply. As of 2025 it generally requires a prior visa in the same classification, still valid or expired within the last 12 months. Confirm your eligibility on the official site before assuming it applies.</p>';
    return h;
  }

  // Parse an IV "scheduling from" month value: "Jun-2026", "June 2026",
  // "06/2026", "2026-06", "Jun 2026". Returns {year, month(1-12), label} or null.
  function parseIvMonth(raw) {
    if (!raw) return null;
    var s = String(raw).trim();
    var monthNames = ["january","february","march","april","may","june","july",
                      "august","september","october","november","december"];
    var mo = null, yr = null;
    // Try "Mon-YYYY" / "Month YYYY" / "Mon YYYY"
    var m = s.match(/([A-Za-z]{3,})[\s\-\/]+(\d{4})/);
    if (m) {
      var name = m[1].toLowerCase();
      for (var i = 0; i < 12; i++) {
        if (monthNames[i] === name || monthNames[i].slice(0, 3) === name.slice(0, 3)) { mo = i + 1; break; }
      }
      yr = parseInt(m[2], 10);
    }
    // Try "MM/YYYY" or "YYYY-MM"
    if (mo == null) {
      var m2 = s.match(/^(\d{1,2})[\s\-\/](\d{4})$/);
      if (m2) { mo = parseInt(m2[1], 10); yr = parseInt(m2[2], 10); }
      else {
        var m3 = s.match(/^(\d{4})[\s\-\/](\d{1,2})$/);
        if (m3) { yr = parseInt(m3[1], 10); mo = parseInt(m3[2], 10); }
      }
    }
    if (mo == null || yr == null || mo < 1 || mo > 12 || yr < 2000 || yr > 2100) return null;
    var full = ["January","February","March","April","May","June","July",
                "August","September","October","November","December"];
    return { year: yr, month: mo, label: full[mo - 1] + " " + yr };
  }

  // Card: enter the IV Scheduling Status Tool's "scheduling from" month for a
  // consular immigrant-visa interview. Distinct from the H-1B stamping card above.
  function ivSchedulePasteBlock() {
    var h = '<div class="result-block paste-card" id="iv-paste">';
    h += '<h3><span class="num">↺</span>Immigrant Visa Interview Scheduling (Consular Processing)</h3>';
    h += '<p class="help" style="margin-top:0;"><strong>For consular processing only</strong>: an immigrant-visa (green card) interview at a U.S. embassy or consulate abroad. <strong>Skip this if you are filing Form I-485 (adjustment of status) inside the U.S.</strong> This shows how far behind the National Visa Center (NVC) is in scheduling green-card interviews at a given post.</p>';
    h += '<p style="margin:0 0 10px;">Step 1: ' + extLink(IV_URL, "Open the IV Scheduling Status Tool") + '. Choose <strong>Employment-Based Preference</strong> and your consulate, then copy the month it shows after &ldquo;NVC is currently scheduling documentarily complete cases with visas available from&rdquo;.</p>';
    h += '<div class="paste-row">';
    h += '<label class="paste-label" for="iv-consulate">Consulate</label>';
    h += '<select id="iv-consulate" class="paste-select">';
    ["Mumbai", "New Delhi", "Hyderabad", "Chennai", "Kolkata", "Other"].forEach(function (c) {
      var sel = (state.ivSchedule && state.ivSchedule.consulate === c) ? " selected" : "";
      h += '<option value="' + esc(c) + '"' + sel + '>' + esc(c) + '</option>';
    });
    h += '</select>';
    h += '</div>';
    h += '<label class="paste-label" for="iv-month" style="margin-top:10px;">Step 2: enter the &ldquo;scheduling from&rdquo; month (e.g. &ldquo;Jun-2026&rdquo;):</label>';
    h += '<input id="iv-month" class="paste-input" type="text" placeholder="Jun-2026"' +
         (state.ivSchedule ? ' value="' + esc(state.ivSchedule.rawInput || "") + '"' : "") + '>';
    h += '<label class="paste-label" for="iv-updated" style="margin-top:10px;">Step 3 (optional): the &ldquo;Last Updated&rdquo; date shown:</label>';
    h += '<input id="iv-updated" class="paste-input" type="text" placeholder="August 07, 2026"' +
         (state.ivSchedule && state.ivSchedule.updated ? ' value="' + esc(state.ivSchedule.updated) + '"' : "") + '>';
    h += '<button type="button" class="paste-btn" id="iv-parse">Read this</button>';
    h += '<div id="iv-out" class="paste-preview"' + (state.ivSchedule ? '' : ' style="display:none;"') + '>';
    if (state.ivSchedule) h += ivScheduleOutputHtml(state.ivSchedule);
    h += '</div>';
    h += pasteDisclaimer();
    h += '</div>';
    return h;
  }

  function ivScheduleOutputHtml(iv) {
    var asOf = iv.updated ? (" as of " + esc(iv.updated)) : "";
    var h = '<div class="paste-active-head">NVC scheduling at ' + esc(iv.consulate) + '</div>';
    h += '<p style="margin:8px 0 0;font-size:13.5px;">The National Visa Center' + asOf +
         ' is scheduling employment-based immigrant-visa interviews at <strong>' + esc(iv.consulate) +
         '</strong> for cases that became documentarily complete around <strong>' + esc(iv.label) +
         '</strong>.</p>';
    // If we know the user's priority date, offer a plain-English read on where they sit.
    if (state.pd) {
      var pdMs = parseIsoToMs(state.pd);
      var ivMs = Date.UTC(iv.year, iv.month - 1, 1);
      if (pdMs != null) {
        if (pdMs <= ivMs) {
          h += '<p style="margin:10px 0 0;font-size:13px;color:var(--text-soft);">Your priority date (' +
               esc(fmtDate(state.pd)) + ') is on or before this scheduling month, so, <strong>if your category is current on the Visa Bulletin</strong> and your case is documentarily complete, you are within the window NVC is actively scheduling. Interview scheduling is the next gate.</p>';
        } else {
          h += '<p style="margin:10px 0 0;font-size:13px;color:var(--text-soft);">Your priority date (' +
               esc(fmtDate(state.pd)) + ') is more recent than this scheduling month, so NVC has not yet reached cases like yours at this post. This moves month to month.</p>';
        }
      }
    }
    h += '<p style="margin:10px 0 0;font-size:12.5px;color:var(--text-soft);">This is NVC scheduling progress, not a guarantee or a booking, and it changes every month. A visa must also be available for your category on the ' + extLink(BULLETIN_URL, "Visa Bulletin") + ' before an interview can be scheduled. Confirm on the official tool.</p>';
    return h;
  }

  // Empty, hidden container for the community-chatter snapshot. Populated
  // asynchronously by loadCommunitySnapshot() after render; stays hidden if the
  // same-origin community.json is missing/empty (e.g. local/dev), so it never
  // shows a broken or empty state.
  function communitySnapshotPlaceholder() {
    return '<div class="community-snapshot community-card" style="display:none;"></div>';
  }

  // Fetch the SAME-ORIGIN community.json (published by our daily pipeline; the
  // browser makes no third-party request) and render Reddit date-report items.
  // The data file is a rolling 21-day window; we show the last-7-day items by
  // default and hide the 8-21-day "older" ones behind a "Show older" control.
  //
  // schema:2 adds a category taxonomy: above the list we render a chip row (with
  // per-category counts, empty categories omitted) and, once a category is
  // selected, a row of subreddit sub-chips. The DEFAULT ("All") view is byte-for-
  // byte the same behaviour as before (recent-7-day list + "Show older" toggle);
  // filtering only narrows the input array. A schema<2 / taxonomy-less file (or an
  // empty category) degrades to the plain single list. Anything wrong -> hide.
  function loadCommunitySnapshot() {
    var boxes = document.querySelectorAll(".community-snapshot");
    if (!boxes.length) return;
    var emptyNote = document.getElementById("community-empty");
    var hideAll = function () {
      for (var i = 0; i < boxes.length; i++) { boxes[i].style.display = "none"; }
      // In the standalone "Community" hub section, show a friendly empty note
      // instead of a blank panel; in-result placeholders just stay hidden.
      if (emptyNote) { emptyNote.style.display = "block"; }
    };
    // Age of a "YYYY-MM-DD" date in whole days relative to the client's current
    // date. A bad/blank date returns null so callers can treat it as "older".
    var ageInDays = function (dateStr) {
      if (!dateStr) return null;
      var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(dateStr));
      if (!m) return null;
      var then = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
      if (isNaN(then.getTime())) return null;
      var now = new Date();
      var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      return Math.floor((today.getTime() - then.getTime()) / 86400000);
    };
    var itemHtml = function (it) {
      var title = esc(it.title || "(no title)");
      var url = it.url || "";
      var src = esc(it.source || "reddit");
      var date = esc(it.date || "");
      var titleHtml = url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + title + '</a>'
        : title;
      return '<li class="community-item">' + titleHtml +
             '<div class="community-meta">' + src + (date ? ' &middot; ' + date : '') + '</div></li>';
    };
    var categoriesOf = function (it) {
      return (it && Array.isArray(it.categories)) ? it.categories : [];
    };
    // Read a category id from the URL hash (#community=<id>); "" if none.
    var hashCat = function () {
      try {
        var m = /^#community=([A-Za-z0-9_-]+)$/.exec(window.location.hash || "");
        return m ? m[1] : "";
      } catch (e) { return ""; }
    };
    // Reflect the active category into the hash WITHOUT adding history entries
    // and WITHOUT touching storage (consistent with "nothing about you is saved").
    var setHashCat = function (cat) {
      try {
        if (cat) {
          window.history.replaceState(null, "", "#community=" + encodeURIComponent(cat));
        } else if (/^#community=/.test(window.location.hash || "")) {
          window.history.replaceState(null, "", window.location.pathname + window.location.search);
        }
      } catch (e) { /* hash is a nicety; never break rendering */ }
    };

    fetch("community.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("no file"); return r.json(); })
      .then(function (data) {
        var items = (data && Array.isArray(data.items)) ? data.items : [];
        if (!items.length) { hideAll(); return; }

        // Feature-detect the taxonomy. Only enable chips for schema>=2 with a
        // non-empty taxonomy AND items that actually carry category arrays.
        var taxonomy = (data && Number(data.schema) >= 2 && Array.isArray(data.taxonomy))
          ? data.taxonomy : null;
        var hasCats = taxonomy && items.some(function (it) { return categoriesOf(it).length; });

        // Per-category counts over the full window (drives chip labels; empty
        // categories are omitted from the chip row).
        var counts = {};
        if (hasCats) {
          items.forEach(function (it) {
            categoriesOf(it).forEach(function (c) { counts[c] = (counts[c] || 0) + 1; });
          });
        }
        var cats = hasCats
          ? taxonomy.filter(function (t) { return counts[t.id] > 0; })
          : [];

        var whenRaw = data.generated_at || "";
        var when = whenRaw;
        try {
          var d = new Date(whenRaw);
          if (!isNaN(d.getTime())) {
            when = d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
          }
        } catch (e) { /* keep raw */ }
        var headerHtml =
          '<h3>Recent Community Chatter on Visa Dates <span class="community-tag">Unverified</span></h3>' +
          '<p class="community-sub">Anecdotal reports from Reddit (e.g. someone got a visa appointment or noticed a date move), gathered at our last update' +
          (when ? ' on <strong>' + esc(when) + '</strong>' : '') +
          '. These are not the tool’s computed guidance. Confirm anything against official sources (travel.state.gov, uscis.gov). Not legal advice.</p>';

        // The list section: recent-7-day up front + "Show older" toggle to 21
        // days (or the past-21-day fallback list). Reused for All AND filtered
        // views so the 7/21 split is preserved within every filter.
        var listSection = function (list) {
          var recent = [], older = [];
          list.forEach(function (it) {
            var age = ageInDays(it && it.date);
            if (age !== null && age <= 7) { recent.push(it); }
            else { older.push(it); }
          });
          var h = "";
          if (recent.length) {
            h += '<ul class="community-list">';
            recent.slice(0, 10).forEach(function (it) { h += itemHtml(it); });
            h += '</ul>';
            if (older.length) {
              h += '<button type="button" class="community-showall">Show older chatter (' +
                   older.length + ' more from the past 21 days)</button>';
              h += '<ul class="community-list community-older" hidden>';
              older.slice(0, 20).forEach(function (it) { h += itemHtml(it); });
              h += '</ul>';
            }
          } else {
            h += '<p class="community-sub community-older-note">Nothing new in the past week, so showing the past 21 days.</p>';
            h += '<ul class="community-list">';
            older.slice(0, 20).forEach(function (it) { h += itemHtml(it); });
            h += '</ul>';
          }
          return h;
        };

        var chipRow = function (activeCat) {
          if (!cats.length) return "";
          var h = '<div class="community-chips" role="group" aria-label="Filter community chatter by category">';
          h += '<button type="button" class="community-chip' + (!activeCat ? ' is-active' : '') +
               '" data-cat="" aria-pressed="' + (!activeCat ? 'true' : 'false') + '">All (' + items.length + ')</button>';
          cats.forEach(function (t) {
            var on = activeCat === t.id;
            h += '<button type="button" class="community-chip' + (on ? ' is-active' : '') +
                 '" data-cat="' + esc(t.id) + '" aria-pressed="' + (on ? 'true' : 'false') + '">' +
                 esc(t.label) + ' (' + counts[t.id] + ')</button>';
          });
          h += '</div>';
          return h;
        };

        var subChipRow = function (activeCat, activeSub) {
          if (!activeCat || !taxonomy) return "";
          var tax = null;
          for (var i = 0; i < taxonomy.length; i++) {
            if (taxonomy[i].id === activeCat) { tax = taxonomy[i]; break; }
          }
          if (!tax) return "";
          var subCounts = {};
          items.forEach(function (it) {
            if (categoriesOf(it).indexOf(activeCat) === -1) return;
            var s = (it.subreddit || "");
            if (!s) return;
            subCounts[s] = (subCounts[s] || 0) + 1;
          });
          var subs = (tax.subs || []).filter(function (s) { return subCounts[s] > 0; });
          if (!subs.length) return "";
          var total = 0;
          for (var k in subCounts) { if (subCounts.hasOwnProperty(k)) total += subCounts[k]; }
          var h = '<div class="community-subchips" role="group" aria-label="Filter by subreddit">';
          h += '<span class="community-subchips-label">' + esc(tax.label) + ' ▸</span>';
          h += '<button type="button" class="community-subchip' + (!activeSub ? ' is-active' : '') +
               '" data-sub="" aria-pressed="' + (!activeSub ? 'true' : 'false') + '">all subs (' + total + ')</button>';
          subs.forEach(function (s) {
            var on = activeSub === s;
            h += '<button type="button" class="community-subchip' + (on ? ' is-active' : '') +
                 '" data-sub="' + esc(s) + '" aria-pressed="' + (on ? 'true' : 'false') + '">r/' +
                 esc(s) + ' (' + subCounts[s] + ')</button>';
          });
          h += '</div>';
          return h;
        };

        var filtered = function (activeCat, activeSub) {
          if (!activeCat) return items;
          return items.filter(function (it) {
            if (categoriesOf(it).indexOf(activeCat) === -1) return false;
            if (activeSub && (it.subreddit || "") !== activeSub) return false;
            return true;
          });
        };

        var wire = function (box, activeCat, activeSub) {
          var btn = box.querySelector(".community-showall");
          if (btn) {
            btn.addEventListener("click", function () {
              var ol = box.querySelector(".community-older");
              if (ol) { ol.hidden = false; }
              btn.style.display = "none";
            });
          }
          var chips = box.querySelectorAll(".community-chip");
          for (var i = 0; i < chips.length; i++) {
            chips[i].addEventListener("click", function () {
              var c = this.getAttribute("data-cat") || "";
              var nc = c || null;
              setHashCat(nc);
              renderBox(box, nc, null);
            });
          }
          var subchips = box.querySelectorAll(".community-subchip");
          for (var j = 0; j < subchips.length; j++) {
            subchips[j].addEventListener("click", function () {
              var s = this.getAttribute("data-sub") || "";
              renderBox(box, activeCat, s || null);
            });
          }
        };

        function renderBox(box, activeCat, activeSub) {
          // Guard: a category that isn't present in the window is not a valid
          // filter -> fall back to All.
          if (activeCat && !counts[activeCat]) { activeCat = null; activeSub = null; }
          var list = filtered(activeCat, activeSub);
          var emptyFilterNote = "";
          if (activeCat && !list.length) {
            // Never show a blank panel: revert to All with a friendly note.
            emptyFilterNote = '<p class="community-sub community-older-note">Nothing here in the past 21 days for this filter, so showing everything.</p>';
            activeCat = null; activeSub = null; list = items;
          }
          box.innerHTML = headerHtml + chipRow(activeCat) +
                          subChipRow(activeCat, activeSub) + emptyFilterNote +
                          listSection(list);
          box.style.display = "block";
          wire(box, activeCat, activeSub);
        }

        // Initial category from the deep-link hash (only if it maps to a
        // non-empty category); default is All.
        var initialCat = null;
        var hc = hashCat();
        if (hasCats && hc && counts[hc]) { initialCat = hc; }

        for (var b = 0; b < boxes.length; b++) { renderBox(boxes[b], initialCat, null); }
        if (emptyNote) { emptyNote.style.display = "none"; }
      })
      .catch(function () { hideAll(); });
  }

  // ==========================================================================
  // RESULT HUB — a compact, personalized lead-in rendered ABOVE the existing
  // detailed result blocks ("input -> DIAGNOSIS -> EXPLANATION -> OPTIONS").
  // Renders only what applies (levers / attorney questions gate on answered
  // fields). Additive: today's full result is preserved verbatim inside the
  // "Full breakdown" collapsible below. EB path only for now; F-1 and PRE keep
  // their own dedicated result pages. Reuses existing helpers rather than
  // duplicating their logic: currentStageColumn, capTimingBlock, nextStepsBlock,
  // i140StageBlock, diffYearsMonths, effectiveCountryData, findMetro.
  // ==========================================================================

  // Is the priority date behind the current cutoff (still waiting on the queue)?
  // Treats an Unavailable Final Action Date as effectively waiting.
  function hubWaiting(countryData, pd) {
    if (!countryData) return false;
    if (countryData.final_action_date === "CURRENT") return false;
    if (countryData.final_action_date == null) return true;
    var pdMs = parseIsoToMs(pd), fadMs = parseIsoToMs(countryData.final_action_date);
    if (pdMs == null || fadMs == null) return false;
    return pdMs > fadMs;
  }

  // On a work visa we can speak to (H-1B/L-1 via the new multi-select, or the
  // detailed H-1B-year question). Drives the dual-track diagnosis strip.
  function hubOnWorkVisa() {
    var wv = state.workVisa || [];
    return wv.indexOf("H-1B") !== -1 || wv.indexOf("L-1") !== -1 || hasDetailIncl("h1b");
  }

  var PIPELINE_STAGES = ["PERM", "I-140", "Priority-date wait", "I-485", "Green card"];

  // Generalizes currentStageColumn() into a 5-node "You are here" index for the
  // PERM -> I-140 -> priority-date wait -> I-485 -> Green card pipeline. When
  // PERM/I-140 are unanswered we lean on the priority-date comparison (spec 2.1)
  // and flag the placement as not confident so we don't over-claim completion.
  function pipelineNode(countryData, pd) {
    var col = currentStageColumn(); // -1..4 from perm + i140
    var waiting = hubWaiting(countryData, pd);
    if (col === 3) return { here: waiting ? 2 : 3, confident: true }; // I-140 approved
    if (col === 2) return { here: 1, confident: true };              // PERM certified / I-140 pending
    if (col === 1 || col === 0) return { here: 0, confident: true }; // PERM in progress / not filed
    return { here: waiting ? 2 : 0, confident: false };              // no PERM/I-140 answer
  }

  function pipelineTrackerBlock(countryData, pd) {
    var node = pipelineNode(countryData, pd);
    var here = node.here;
    var h = '<div class="gc-pipeline" role="list" aria-label="Where you are in the green card pipeline">';
    PIPELINE_STAGES.forEach(function (label, i) {
      var cls = i < here ? "done" : (i === here ? "here" : "future");
      if (cls === "done" && !node.confident) cls = "assumed"; // don't assert completion we can't confirm
      h += '<div class="gc-node ' + cls + '" role="listitem">';
      h += '<span class="gc-node-dot" aria-hidden="true">' + (cls === "done" ? "&#10003;" : (cls === "here" ? "&#9679;" : "")) + '</span>';
      h += '<span class="gc-node-label">' + esc(label) + '</span>';
      if (i === here) h += '<span class="gc-node-here">You are here</span>';
      h += '</div>';
      if (i < PIPELINE_STAGES.length - 1) h += '<span class="gc-node-arrow" aria-hidden="true">&rarr;</span>';
    });
    h += '</div>';
    if (!node.confident) {
      h += '<p class="gc-pipeline-note">This places you by your priority date because you haven\'t told us your PERM and I-140 status yet. Answer the optional PERM and I-140 questions to sharpen it.</p>';
    }
    return h;
  }

  // ---- "My Immigration Journey" north-star map --------------------------------
  // The full lifecycle, start to green card, with the user's current stage
  // highlighted. Reuses pipelineNode() for the green-card position so it can never
  // disagree with the detailed pipeline below. The nonimmigrant prefix (F-1 -> OPT
  // -> STEM OPT -> work visa) is shown as neutral CONTEXT, never asserted as the
  // user's actual history (we don't know it) — only green-card stages we computed
  // are marked done. General lifecycle, not a prediction.
  // The "work visa" label on the journey map is resolved at render time so it
  // reads the user's actual visa (e.g. "H-1B") instead of the generic word. Uses
  // the multi-select workVisa from question 1 if the user answered it, or the
  // PRE-flow's preVisa when applicable. Falls back to the generic label.
  function journeyWorkVisaLabel() {
    if (state.category === "PRE" && state.preVisa) {
      // preVisa is one of: "H-1B", "L-1A", "L-1B". Collapse L-1 variants.
      if (state.preVisa === "L-1A" || state.preVisa === "L-1B") return "L-1";
      return state.preVisa;
    }
    var wv = (state.workVisa || []).filter(function (v) { return v !== "None" && v !== "F-1 / OPT"; });
    if (wv.length === 1) return wv[0];
    if (wv.length > 1) return wv.join(" / ");
    return "Work visa";
  }
  var JOURNEY_STAGES = [
    { key: "f1",   label: "F-1",                phase: "status" },
    { key: "opt",  label: "OPT",                phase: "status" },
    { key: "stem", label: "STEM OPT",           phase: "status" },
    { key: "work", label: null /* dynamic */,   phase: "status" },
    { key: "perm", label: "PERM",               phase: "gc" },
    { key: "i140", label: "I-140",              phase: "gc" },
    { key: "wait", label: "PD wait",            phase: "gc" },
    { key: "i485", label: "I-485",              phase: "gc" },
    { key: "gc",   label: "Green card",         phase: "gc" }
  ];
  function journeyHere(cat, countryData, pd) {
    if (cat === "F-1") return { here: 1, confident: false };   // on OPT/STEM (student phase)
    if (cat === "PRE") return { here: 3, confident: true };    // on a work visa, GC not started
    var node = pipelineNode(countryData, pd);                  // 0..4 across the GC stages
    return { here: 4 + node.here, confident: node.confident };
  }
  function journeyMapBlock(cat, countryData, pd) {
    var n = journeyHere(cat, countryData, pd), here = n.here;
    var workLabel = journeyWorkVisaLabel();
    var h = '<div class="result-block journey-map" id="journey-map">';
    h += '<h3 class="jm-title">Your immigration journey</h3>';
    h += '<p class="help" style="margin:0 0 4px;">The whole path, start to green card, with your current stage highlighted. This is the general lifecycle, not a prediction of your specific case.</p>';
    // Dots-on-a-line timeline. No boxes, no arrow characters, no redundant color
    // legend below — the phase (status vs green card) is encoded in the dot color
    // and stays readable at a glance.
    h += '<ol class="jm-timeline" role="list" aria-label="Your immigration journey; your current stage is highlighted">';
    JOURNEY_STAGES.forEach(function (s, i) {
      var cls;
      if (i === here) cls = "here";
      else if (i > here) cls = "future";
      else if (s.phase === "gc") cls = n.confident ? "done" : "assumed"; // GC stages we computed
      else cls = "context"; // nonimmigrant prefix — shown, never asserted as done
      var label = s.label != null ? s.label : (s.key === "work" ? workLabel : "");
      h += '<li class="jm-step jm-phase-' + s.phase + ' jm-' + cls + '" role="listitem">';
      h += '<span class="jm-dot" aria-hidden="true"></span>';
      h += '<span class="jm-label">' + esc(label) + '</span>';
      if (i === here) h += '<span class="jm-here-tag">You are here</span>';
      h += '</li>';
    });
    h += '</ol>';
    if (!n.confident) {
      h += '<p class="jm-caveat">Add your PERM and I-140 status above to place this precisely.</p>';
    }
    h += '</div>';
    return h;
  }

  // One-line plain-language status. Mirrors the "In simple terms" copy from the
  // Where-You-Stand block (block 1) without duplicating its full branching.
  // Raw one-line plain-language status sentence (no wrapper), reused by both the
  // hub diagnosis line and the answer-first hero card so they never diverge.
  function diagnosisSentence(cat, country, pd, countryData) {
    if (!countryData) {
      return "We don't have Visa Bulletin data for " + esc(cat) + " " + esc(countryLabel(country)) + ", so we can't compare your priority date to the queue.";
    }
    if (countryData.final_action_date == null) {
      return "Approvals are paused this month for " + esc(cat) + " " + esc(countryLabel(country)) + ": the Final Action Date, the chart that governs approval, is Unavailable because the year's visa numbers are used up. It is a temporary pause that resets when the fiscal year turns over on October 1, not a rejection. Your filing position is shown separately below.";
    }
    if (!hubWaiting(countryData, pd)) {
      return "Your priority date is at or ahead of this month's Final Action Date, the chart that governs approval. If your I-140 is approved and the rest of your case is ready, you may be able to file I-485. Confirm the controlling chart on the current Visa Bulletin, and see your filing and approval positions below.";
    }
    var gap = diffYearsMonths(pd, countryData.final_action_date);
    var span = gap ? (gap.years + " years " + gap.months + " months") : "some time";
    return "On the Final Action Dates chart, the queue is currently serving priority dates about " + span +
      " before yours, so it needs to advance that far before your green card can be approved. Whether you can " +
      "file the I-485 sooner is a separate question, answered by your filing position below. Nothing you file " +
      "speeds the queue itself. This is a structural wait.";
  }

  // ---- The two Visa Bulletin charts, shown side by side -----------------------
  // The bulletin publishes TWO charts that answer DIFFERENT questions, so a single
  // "current / not current" verdict collapses them and teaches the wrong model.
  // The Dates for Filing chart is the one that, in the months USCIS honors it,
  // controls when the I-485 may be FILED; the Final Action Dates chart controls
  // when the green card can actually be ISSUED. Which chart may be used for filing
  // in a given month is a USCIS determination — we do NOT compute or guess it. We
  // render the bulletin's own chart note from the rulebook verbatim and let it say.
  // Returns RAW strings; the caller escapes them at the render site.
  function chartPosition(cutoff, pd, isFilingChart) {
    if (cutoff === "CURRENT") {
      return { value: "Current", cls: " current",
        body: "There is no cutoff on this chart this month, so every priority date in this category counts as reached." };
    }
    if (cutoff == null) {
      return isFilingChart
        ? { value: "Not published", cls: "",
            body: "No Dates for Filing cutoff is published for this category this month." }
        : { value: "Unavailable", cls: " unavailable",
            body: "No Final Action Date is published this month, so no green card in this category can be approved right now." };
    }
    var label = fmtDate(cutoff);
    var pdMs = parseIsoToMs(pd), cutoffMs = parseIsoToMs(cutoff);
    if (pdMs == null || cutoffMs == null) {
      return { value: label, cls: "", body: "We could not compare your priority date to this cutoff." };
    }
    var pdLabel = fmtDate(pd);
    if (pdMs <= cutoffMs) {
      var ahead = diffYearsMonths(cutoff, pd);
      var by = (ahead && (ahead.years || ahead.months))
        ? (", by " + ahead.years + " years " + ahead.months + " months")
        : "";
      return { value: label, cls: "",
        body: "Reached. Your priority date (" + pdLabel + ") is at or before this cutoff" + by + "." };
    }
    var behind = diffYearsMonths(pd, cutoff);
    var behindSpan = behind ? (behind.years + " years " + behind.months + " months") : "some time";
    return { value: label, cls: "",
      body: "Not reached. Your priority date (" + pdLabel + ") is " + behindSpan + " more recent than this cutoff." };
  }

  // Two labelled positions, each naming the chart it came from, so no single
  // current/not-current verdict ever stands on its own. Reuses the existing
  // .bulletin-row / .bulletin-cell component (already responsive on mobile).
  function chartPositionsBlock(countryData, pd) {
    if (!countryData) return "";
    var filing = chartPosition(countryData.date_for_filing, pd, true);
    var approval = chartPosition(countryData.final_action_date, pd, false);
    var h = '<div class="bulletin-row">';
    h += '<div class="bulletin-cell"><div class="label">Filing position &middot; Dates for Filing chart</div>';
    h += '<div class="value' + filing.cls + '">' + esc(filing.value) + '</div>';
    h += '<div class="sub">' + esc(filing.body) +
      ' This is the chart that, in the months USCIS honors it, controls when the I-485 may be filed.</div></div>';
    h += '<div class="bulletin-cell"><div class="label">Approval position &middot; Final Action Dates chart</div>';
    h += '<div class="value' + approval.cls + '">' + esc(approval.value) + '</div>';
    h += '<div class="sub">' + esc(approval.body) +
      ' This chart controls when the green card can actually be issued, whichever chart was used to file.</div></div>';
    h += '</div>';
    if (rulebook && rulebook.bulletin && rulebook.bulletin.chart_note) {
      h += '<p class="band-caveat">USCIS decides each month which chart may be used for filing. Per the ' +
        esc(fmtMonth(rulebook.bulletin.as_of)) + ' Visa Bulletin: ' + esc(rulebook.bulletin.chart_note) + '</p>';
    }
    return h;
  }

  function diagnosisLineBlock(cat, country, pd, countryData) {
    return '<p class="gc-diagnosis-line">' + diagnosisSentence(cat, country, pd, countryData) + '</p>';
  }

  // Second mini-track shown alongside the queue when on a work visa (spec 2.1).
  // Reuses capTimingBlock()'s per-year read when the detailed H-1B year is known.
  function dualTrackStrip() {
    if (!hubOnWorkVisa()) return "";
    var wv = state.workVisa || [];
    var onH1b = wv.indexOf("H-1B") !== -1 || hasDetailIncl("h1b");
    var onL1 = wv.indexOf("L-1") !== -1;
    var parts = [];
    if (onH1b) {
      parts.push("<strong>H-1B</strong>: cap extensions may be available via AC21 &sect;106(a) (once PERM or the I-140 has been pending 365+ days) and &sect;104(c) (after your I-140 is approved), which can generally keep you in status through the green-card wait.");
    }
    if (onL1) {
      parts.push("<strong>L-1</strong>: the L-1 has a hard maximum (7 years for L-1A, 5 for L-1B) and no AC21-style extension, so the green-card timeline matters for maintaining status.");
    }
    if (!parts.length) {
      parts.push("Your work visa and your green-card queue are two separate clocks.");
    }
    var h = '<div class="gc-dualtrack">';
    h += '<div class="gc-dualtrack-label">Work-visa track</div>';
    h += '<p class="gc-dualtrack-body">' + parts.join(" ") + ' Your green-card queue and your work-visa runway move on separate clocks. Confirm the specifics with an immigration attorney.</p>';
    var cap = capTimingBlock(); // gates on the detailed H-1B-year answer; empty otherwise
    if (cap) h += cap;
    h += '</div>';
    return h;
  }

  // Section 2.2 — the single binding constraint + WHY + concrete next micro-step.
  // Reuses nextStepsBlock() (per-PERM action copy) and i140StageBlock().
  function blockingStepBlock(cat, country, pd, countryData) {
    var col = currentStageColumn();
    var waiting = hubWaiting(countryData, pd);
    var i140Pending = (state.i140 === "pending-regular" || state.i140 === "pending-premium" || state.i140 === "rfe");
    var title, why;
    if (col === 0) {
      title = "PERM hasn't been filed yet.";
      why = "Your priority date doesn't lock until the ETA 9089 (PERM) is filed, so your place in line hasn't started counting.";
    } else if (col === 1) {
      title = "Your PERM is pending at DOL.";
      why = "The I-140 can't be filed until PERM is certified. Your priority date is already locked as of the PERM filing date.";
    } else if (col === 2) {
      if (i140Pending) {
        title = "Your I-140 is still pending.";
        why = "Until the I-140 is approved, AC21 §104(c) portability isn't available and the case can't move toward I-485.";
      } else {
        title = "PERM is certified; the I-140 is the next filing.";
        why = "The I-140 comes next. Once it's approved your priority date becomes portable to a new employer.";
      }
    } else if (col === 3) {
      if (waiting) {
        title = "The binding constraint is the visa queue.";
        why = "Your PERM and I-140 are done, so nothing you file next speeds things up. The wait is now the " + esc(cat) + " " + esc(countryLabel(country)) + " cutoff catching up to your priority date, a structural wait.";
      } else {
        title = "Your priority date is current: the next step is your I-485.";
        why = "With an approved I-140 and a current priority date, filing and adjudicating your I-485 (or consular processing) is what's left. Confirm the controlling chart.";
      }
    } else {
      if (waiting) {
        title = "The visa queue is likely your binding constraint.";
        why = "For " + esc(cat) + " " + esc(countryLabel(country)) + " the cutoff is behind your priority date, so the wait is structural. Answer the PERM and I-140 questions to confirm nothing earlier in the pipeline is the real blocker.";
      } else {
        title = "Tell us your PERM and I-140 status to pin down the blocker.";
        why = "Your priority date isn't behind the cutoff, so the binding step depends on where your PERM and I-140 stand.";
      }
    }
    var h = '<div class="gc-blocker">';
    h += '<div class="gc-blocker-title">' + title + '</div>';
    h += '<p class="gc-why"><span class="gc-why-label">Why</span> ' +why + '</p>';
    var micro = (col === 2 && i140Pending) ? i140StageBlock() : "";
    if (!micro) micro = nextStepsBlock();
    h += '<div class="gc-microstep">' + micro + '</div>';
    h += '<p class="gc-caveat">Timelines and consequences here are general. Confirm your specifics with an immigration attorney.</p>';
    h += '</div>';
    return h;
  }

  // Section 2.3 — levers, each gated on the answers actually given.
  function timelineLeversBlock(cat, country, pd, countryData) {
    var levers = [];
    var sp = state.spouse;
    var spouseAnswered = (sp != null && sp !== "skip");
    var spouseDiffers = spouseAnswered && sp !== "same" && sp !== "not-married" && sp !== country;
    if (!spouseAnswered || spouseDiffers) {
      levers.push({
        label: "Cross-chargeability",
        why: (!spouseAnswered
          ? "If your spouse was born in a shorter-queue country, you may be able to charge your case to their country of birth (INA §202(b)). You haven't told us their country yet."
          : "Your spouse's country of birth may have a shorter queue; charging your case to it under INA §202(b) could cut the wait."),
        link: spouseDiffers ? "#cross-charge" : "glossary.html",
        text: spouseDiffers ? "See the cross-chargeability note" : "Look it up in the glossary"
      });
    }
    if (cat === "EB-2" || cat === "EB-3") {
      levers.push({
        label: "EB-2 vs EB-3",
        why: "If the other category's applicable cutoff for " + esc(countryLabel(country)) + " is further ahead, counsel may evaluate whether a second petition in that category could provide an earlier filing opportunity while preserving your existing priority date where permitted.",
        link: "#strategies-block", text: "See the Strategies section"
      });
    }
    if (cat !== "EB-1") {
      var strong = (state.degree === "us-masters" || state.degree === "foreign-masters");
      levers.push({
        label: "NIW / EB-1" + (strong ? " (you may be a fit)" : ""),
        why: (strong ? "You hold an advanced degree, which is the base bar for EB-2 NIW. " : "") + "NIW and EB-1A are self-petitions that skip PERM and the employer dependency. The evidence bar is high.",
        link: "eb1a.html", text: "See EB Paths"
      });
    }
    levers.push({
      label: "Job or location change",
      why: "A same-MSA move is generally lower risk. Duties, title, wage, employer entity, and case stage can still matter, and a move to a different MSA may require counsel to reassess whether new PERM steps are needed. Confirm with an attorney.",
      link: "#location-matrix", text: "See the Internal Move Impact Matrix"
    });
    if (!levers.length) return "";
    var h = '<ul class="gc-levers">';
    levers.forEach(function (l) {
      var isAnchor = l.link.charAt(0) === "#";
      var attrs = isAnchor ? 'href="' + esc(l.link) + '" class="gc-hub-link"' : 'href="' + esc(l.link) + '"';
      h += '<li class="gc-lever">';
      h += '<div class="gc-lever-label">' + esc(l.label) + '</div>';
      h += '<p class="gc-why"><span class="gc-why-label">Why</span> ' +l.why + '</p>';
      h += '<a ' + attrs + '>' + esc(l.text) + ' &rarr;</a>';
      h += '</li>';
    });
    h += '</ul>';
    return h;
  }

  // Section 2.4 — concept cards linking glossary/paths by stage. Reuses the
  // existing ns-card component (the wrapping section carries the .next-steps class).
  function conceptCardsBlock(cat, country, pd, countryData) {
    var cards = [];
    cards.push({ href: "glossary.html", title: "Priority date", sub: "What locks it, why it is your place in line, and when it becomes portable." });
    if (hubWaiting(countryData, pd)) {
      cards.push({ href: "glossary.html", title: "Final Action Date vs Date for Filing", sub: "The two Visa Bulletin charts, and which one controls whether you can file." });
    }
    var col = currentStageColumn();
    if (col === 2 && (state.i140 === "pending-regular" || state.i140 === "pending-premium" || state.i140 === "rfe")) {
      cards.push({ href: "glossary.html", title: "AC21 §104(c) portability", sub: "Once your I-140 is approved, changing jobs without losing your priority date." });
    } else {
      cards.push({ href: "eb1a.html", title: "EB categories and paths", sub: "How EB-1, EB-2, EB-3, and self-petition routes differ." });
    }
    cards = cards.slice(0, 3);
    var h = '<div class="ns-grid">';
    cards.forEach(function (c) {
      h += '<a class="ns-card" href="' + esc(c.href) + '">' + esc(c.title) + '<span>' + esc(c.sub) + '</span></a>';
    });
    h += '</div>';
    return h;
  }

  // Section 2.5 — a short, personalized attorney checklist, each item with a WHY.
  // Only items whose triggering answers are present render.
  function attorneyQuestionsBlock(cat, country, pd, countryData) {
    var items = [];
    var waiting = hubWaiting(countryData, pd);
    if (state.i140 === "pending-regular") {
      items.push(["Is my pending I-140 worth premium processing?", "It is pending under regular processing; premium processing is about 15 business days."]);
    }
    if (state.perm === "not-filed") {
      items.push(["When will my PERM be filed?", "Your priority date doesn't lock until it is filed, so the start date drives your whole timeline."]);
    }
    if (cat === "EB-2" && waiting && (country === "India" || country === "China")) {
      items.push(["Should I file an EB-3 downgrade?", "EB-2 " + countryLabel(country) + " is behind your priority date; if EB-3 is ahead, a second I-140 may reach I-485 sooner."]);
    }
    if (state.locProspective) {
      var cur = findMetro(state.locCurrent), pro = findMetro(state.locProspective);
      items.push(["Does my planned move to " + (pro ? pro.label : "the new location") + " trigger a PERM restart?",
        "It may be a different MSA than " + (cur ? cur.label : "your current location") + ", which can be treated as a material change."]);
    }
    var sp = state.spouse;
    if (sp == null || (sp !== "same" && sp !== "not-married" && sp !== "skip" && sp !== country)) {
      items.push(["Can we charge my case to my spouse's country of birth?", "If their country has a shorter queue, cross-chargeability under INA §202(b) could shorten your wait."]);
    }
    if (cat === "EB-1" && state.eb1sub === "unsure") {
      items.push(["Which EB-1 sub-category fits my case?", "EB-1A, EB-1B, and EB-1C have different eligibility rules; which criteria you actually meet decides the path."]);
    }
    if (hubOnWorkVisa()) {
      items.push(["What keeps my work authorization valid through the green-card wait?", "Maintaining status is a separate track from the green-card queue, and the rules depend on your visa."]);
    }
    if (!items.length) {
      items.push(["Is my case on the fastest category available to me?", "Category choice can materially change the wait for your country."]);
      items.push(["What should I avoid doing that could reset my priority date?", "Some job, location, or employer changes can restart PERM."]);
    }
    var h = '<ul class="gc-attorney">';
    items.forEach(function (it) {
      h += '<li><div class="gc-q">' + esc(it[0]) + '</div><p class="gc-why"><span class="gc-why-label">Why</span> ' +esc(it[1]) + '</p></li>';
    });
    h += '</ul>';
    return h;
  }

  // ---- Answer-first hero card -------------------------------------------------
  // The dominant lead the user sees before anything else: one plain status
  // sentence, one big "time to green card" number, and the next milestone. Reuses
  // the SAME projection math (scenarioProjection/qpRangeText) as the queue
  // timeline, so the headline number can never disagree with the projector below.
  function heroTimeToGc(cat, country, pd) {
    var s = scenarioProjection(cat, country, pd);
    if (!s || s.status === "nodata" || s.status === "nopd") return null;
    if (s.status === "current") {
      // "current" is decided off final_action_date (see scenarioProjection), so the
      // label must not say "file": being current on the approval chart is a stronger
      // position than merely being allowed to file, and calling it "File now" makes
      // an approval-chart fact wear filing-chart words. usedDff marks the one branch
      // where the Dates for Filing chart was the reference, and filing IS the signal.
      if (s.usedDff) {
        return { big: "You can file now", sub: "your date is current on the Dates for Filing chart, so the I-485 can go in; approval still waits on the Final Action chart plus processing time", milestone: "" };
      }
      return { big: "Your date is current", sub: "current on the Final Action Dates chart, the one that governs approval, so what is left is mostly processing time, on the order of a year to the green card in hand", milestone: "" };
    }
    if (s.status === "unavailable") {
      return { big: "Paused this month", sub: "no green cards are being issued in this category right now; it resets when the fiscal year turns over on October 1", milestone: "" };
    }
    // status === "project"
    var rt = qpRangeText(s.proj);
    var nowY = new Date().getFullYear();
    var loD = Math.max(0, rt.lo - nowY), typD = Math.max(0, rt.typ - nowY), hzD = rt.hz - nowY;
    var big, sub;
    if (rt.mode === "bounded") {
      var hiD = Math.max(loD, rt.hi - nowY);
      big = (loD === hiD) ? ("~" + loD + " years") : ("~" + loD + "&ndash;" + hiD + " years");
      sub = "estimated wait to your green card (about " + rt.lo + "&ndash;" + rt.hi + ")";
    } else if (rt.mode === "partial") {
      big = "~" + loD + "&ndash;" + typD + " years";
      sub = "estimated wait to your green card; at the slowest historical pace it runs beyond " + rt.hz;
    } else { // beyond — the typical (median) pace runs past the modeling horizon
      if (rt.floor) {
        // Fastest pace gives a within-horizon floor; show the full span, not just
        // the optimistic floor, so the number can't be mistaken for "~7 years".
        big = (loD < hzD) ? ("~" + loD + "&ndash;" + hzD + "+ years") : (hzD + "+ years");
        sub = "a very wide range: about " + loD + " years at the fastest historical pace, but at the typical pace the wait runs beyond " + rt.hz + ", effectively indefinite at the current rate";
      } else {
        big = hzD + "+ years";
        sub = "the wait runs beyond the reliable modeling horizon (" + rt.hz + ") even at the fastest historical pace";
      }
    }
    // Next milestone(s) — only show years that fall within the modeling horizon.
    var i485Y = Math.round(s.proj.i485.typ), gcY = Math.round(s.proj.gc.typ);
    var ms = "";
    if (i485Y <= rt.hz) ms = "Next: I-485 filing around <strong>" + i485Y + "</strong>" + (gcY <= rt.hz ? " &middot; green card around <strong>" + gcY + "</strong>" : "");
    return { big: big, sub: sub, milestone: ms };
  }
  function heroCardBlock(cat, country, pd, countryData) {
    var catLabel = cat;
    if (cat === "EB-1" && (state.eb1sub === "EB-1A" || state.eb1sub === "EB-1B" || state.eb1sub === "EB-1C")) catLabel = state.eb1sub;
    var inputs = esc(catLabel) + ' <span class="gc-dot">&middot;</span> ' + esc(countryLabel(country)) +
      ' <span class="gc-dot">&middot;</span> PD ' + esc(fmtDate(pd));
    // Slim hero: just the identity line + the one headline wait number. The
    // plain-English diagnosis ("paused this month" etc.) is NOT repeated here —
    // it lives once in the hub's "What this means" below, so the two don't echo.
    var h = '<section class="hero-card" aria-label="Your status and estimated time to green card">';
    h += '<div class="hero-top"><span class="hero-eyebrow">Where you stand</span><span class="hero-inputs">' + inputs + '</span></div>';
    var t = heroTimeToGc(cat, country, pd);
    if (t) {
      h += '<div class="hero-metric"><div class="hero-number">' + t.big + '</div>' +
        '<div class="hero-number-sub">' + t.sub + '</div></div>';
      if (t.milestone) h += '<p class="hero-milestone">' + t.milestone + '</p>';
    }
    h += '</section>';
    return h;
  }

  // Assembles the five hub sections. Rendered inside the "Full breakdown".
  function renderStatusHub(cat, country, pd, countryData) {
    var catLabel = cat;
    if (cat === "EB-1" && (state.eb1sub === "EB-1A" || state.eb1sub === "EB-1B" || state.eb1sub === "EB-1C")) catLabel = state.eb1sub;
    var summaryBits = [esc(catLabel), esc(countryLabel(country)), "Priority date " + esc(fmtDate(pd))];
    var visaBits = (state.workVisa || []).filter(function (v) { return v !== "None"; });
    if (visaBits.length) summaryBits.push("Also on " + esc(visaBits.join(" + ")));

    var h = '<section class="status-hub" aria-label="Your status at a glance">';
    h += '<p class="gc-hub-summary">' + summaryBits.join(' <span class="gc-dot">&middot;</span> ') + '</p>';

    // The 9-node journey map above is the single "you are here" visual; the hub
    // no longer repeats a second (5-node) pipeline tracker here.
    // The two sections that ARE the answer stay open and visible.
    h += '<div class="gc-hub-section">';
    h += '<h3 class="gc-hub-h">What this means</h3>';
    h += diagnosisLineBlock(cat, country, pd, countryData);
    // Never let the plain-language line stand alone as a single current/not-current
    // verdict: the two chart positions sit directly under it, each naming its chart.
    h += chartPositionsBlock(countryData, pd);
    h += dualTrackStrip();
    h += '</div>';

    h += '<div class="gc-hub-section">';
    h += '<h3 class="gc-hub-h">What you\'re waiting on</h3>';
    h += blockingStepBlock(cat, country, pd, countryData);
    h += '</div>';

    // Everything below the answer collapses into labeled dropdowns so the page
    // opens clean. Each is a native <details> with a rotating arrow (see .gc-drop).
    var levers = timelineLeversBlock(cat, country, pd, countryData);
    if (levers) {
      h += '<details class="gc-drop"><summary>Ways to move faster</summary><div class="gc-drop-body">';
      h += levers;
      h += '</div></details>';
    }

    h += '<details class="gc-drop"><summary>Good to know</summary><div class="gc-drop-body">';
    h += conceptCardsBlock(cat, country, pd, countryData);
    h += '</div></details>';

    h += '<details class="gc-drop"><summary>Questions for your attorney</summary><div class="gc-drop-body">';
    h += attorneyQuestionsBlock(cat, country, pd, countryData);
    h += '</div></details>';

    h += '</section>';
    return h;
  }

  function renderResult() {
    // Guard: the questionnaire result container only exists on status.html.
    // On the standalone Live tools page there is nothing to recompute, so
    // never touch a null element (this keeps the shared paste-in wiring safe
    // to reuse on tools.html).
    if (!resultContent) return;
    var cat = state.category, country = state.country, pd = state.pd;
    var countryData = effectiveCountryData(cat, country);

    var html = "";

    // ====== F-1 OPT/STEM: entirely different results page ======
    if (cat === "F-1") {
      html += journeyMapBlock(cat, countryData, pd);
      html += renderF1Results();
      html += consularPasteBlock(cat); // stamping-timeline estimate is relevant to F-1 too
      html += communitySnapshotPlaceholder();
      html += '<div class="result-footer">';
      html += '<button class="reset-inline" type="button" id="resetInlineBtn">Start over</button>';
      html += printButtonHtml();
      html += '<div style="margin-top:6px;">A rough, personal projection. Confirm your own case with a licensed immigration attorney.</div>';
      html += '</div>';
      resultContent.innerHTML = html;
      wireResultInteractions();
      return;
    }

    // ====== H-1B / L-1, PERM not started yet: forward-planning page ======
    if (cat === "PRE") {
      if (isBulletinStale()) {
        html += '<div class="stale-banner" role="alert">' +
          '<div class="head">This bulletin data may be stale</div>' +
          'The projection below uses the built-in bulletin dates, which may lag. Confirm the latest at ' +
          extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "travel.state.gov") + '.</div>';
      }
      html += journeyMapBlock(cat, countryData, pd);
      html += renderPrePermResults();
      html += permStallBlock();
      html += impactMatrixSection(5);
      html += '<div class="result-block">';
      html += resourcesSection();
      html += '</div>';
      html += communitySnapshotPlaceholder();
      html += '<div class="result-footer">';
      html += '<button class="reset-inline" type="button" id="resetInlineBtn">Start over</button>';
      html += printButtonHtml();
      html += '<div style="margin-top:6px;">A rough, personal projection. Confirm your own case with a licensed immigration attorney.</div>';
      html += '</div>';
      resultContent.innerHTML = html;
      wireResultInteractions();
      return;
    }

    // -- STALE-DATA GUARD (derived from rulebook fields, not a hardcoded date) --
    if (isBulletinStale()) {
      html += '<div class="stale-banner" role="alert">' +
        '<div class="head">This bulletin data may be stale</div>' +
        'The latest visa bulletin may have been published since this was last verified (' +
        esc(rulebook.meta.last_verified) + ', bulletin as of ' + esc(fmtMonth(rulebook.bulletin.as_of)) +
        '). Check ' + extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "travel.state.gov") + '.' +
        '</div>';
    }

    // ====== ANSWER-FIRST LEAD (expanded, above the fold) ======
    // The three things testers said they want first: where they stand, one
    // dominant "time to green card" number, and their position over time. Every-
    // thing else (diagnosis detail, queue state, strategy, methodology) moves into
    // the collapsed "Full breakdown" below so the page opens with the answer.
    html += heroCardBlock(cat, country, pd, countryData);

    // "You are here" stepper (horizontal on desktop, vertical on mobile — see the
    // .jm-* media query in styles.css).
    html += journeyMapBlock(cat, countryData, pd);

    // Queue-position timeline — the "how long" answer. Pulled up out of the old
    // section 2 so it is visible without expanding anything. Renders empty for
    // current / paused / no-data cases (the hero already states those).
    var leadTimeline = queueTimelineBlock(pd, countryData, cat, country);
    if (leadTimeline) {
      html += '<div class="result-block queue-timeline-lead">' +
        '<h3 class="qtl-h">How long, at the historical pace</h3>' + leadTimeline + '</div>';
    }

    // Personalized hub (diagnosis, blocking step, timeline levers, concept cards,
    // attorney questions) — kept EXPANDED, right under the timeline. This is the
    // "what this means for YOU" content the hero summarizes; it must stay visible,
    // not behind the toggle. Only the heavy shared reference (queue tables, wait
    // bands, strategies, methodology) is collapsed below.
    html += renderStatusHub(cat, country, pd, countryData);

    // ====== FULL BREAKDOWN (collapsed by default) — heavy shared reference ======
    var catLabel = esc(cat);
    if (cat === "EB-1" && (state.eb1sub === "EB-1A" || state.eb1sub === "EB-1B" || state.eb1sub === "EB-1C")) {
      catLabel = esc(state.eb1sub);
    }
    // The detail below is grouped into labeled dropdown categories (see .result-drop),
    // all collapsed by default so the page opens on the answer above. Each category
    // opens on click; hub deep-links open the right one automatically.
    html += '<div class="result-breakdown">';
    html += '<p class="rb-lead">The full detail, grouped. Open any section.</p>';
    html += '<details class="result-drop"><summary>The current cutoffs</summary><div class="result-drop-body">';

    // -- BULLETIN DATE BADGE + inputs recap (reference) --
    html += bulletinBadgeBlock();
    html += '<div class="result-block" style="border-top:4px solid var(--purple)">';
    html += '<div class="step-num">Your inputs</div>';
    html += '<h2 style="margin:4px 0 8px;font-size:22px;letter-spacing:-0.4px;">' +
      catLabel + " · " + esc(countryLabel(country)) +
      " · PD " + esc(fmtDate(pd)) + '</h2>';
    html += '<p class="help" style="margin:0;">Per the ' + esc(fmtMonth(rulebook.bulletin.as_of)) + ' Visa Bulletin: ' + esc(rulebook.bulletin.chart_note) + '</p>';
    // Global data-freshness line — subtle, reads entirely from rulebook meta.
    html += '<p class="freshness-line">Bulletin data as of ' + esc(fmtMonth(rulebook.bulletin.as_of)) +
      ' · last verified ' + esc(rulebook.meta.last_verified) +
      ' · rulebook v' + esc(rulebook.meta.version) + '</p>';
    html += '</div>';

    // -- 1. WHERE YOU STAND (personalized; was section 2) --
    html += '<div class="result-block">';
    html += '<h3><span class="num">1</span>Where You Stand</h3>';

    if (!countryData) {
      html += '<div class="status-banner unknown"><div class="head">Cannot compute</div>' +
        'Without bulletin data for ' + esc(cat) + " / " + esc(countryLabel(country)) + ', we cannot compare your priority date to the current queue.</div>';
    } else if (countryData.final_action_date == null && countryData.date_for_filing == null) {
      // EB-2 India case: FAD unavailable
      html += '<div class="status-banner unavailable"><div class="head">This category is paused this month</div>' +
        '<p style="margin:0 0 8px;">No green cards in this category are being issued right now. This is a pause, not a rejection. It usually means the year\'s visa numbers have run out, which is outside your control, and it resets when the new fiscal year begins on October 1.</p>' +
        esc(countryData.status_note || "The Final Action Date is currently unavailable for this category and country.") +
        '</div>';
    } else if (countryData.final_action_date == null && countryData.date_for_filing) {
      // Special EB-2 India: FAD unavailable but DFA published
      html += '<div class="status-banner unavailable"><div class="head">Your category is paused this month</div>' +
        '<strong>Final Action Date: Unavailable.</strong> All of this year\'s ' + esc(cat) + ' ' + esc(countryLabel(country)) + ' green cards have been issued (the fiscal year ends September 30), so approvals are on hold for now. This is frustrating, and it is outside your control, but it is temporary.' +
        '<br><br>Fresh visa numbers become available when the new fiscal year begins on October 1, and the queue starts moving again.</div>';
      // Still show comparison to DFA
      var dfaCmp = diffYearsMonths(countryData.date_for_filing, pd);
      var pdMs = parseIsoToMs(pd);
      var dfaMs = parseIsoToMs(countryData.date_for_filing);
      html += '<div class="status-banner waiting" style="margin-top:10px;"><div class="head">Date for Filing (DFF): ' + esc(fmtDate(countryData.date_for_filing)) + '</div>';
      if (pdMs != null && dfaMs != null) {
        if (pdMs <= dfaMs) {
          var d1 = diffYearsMonths(countryData.date_for_filing, pd);
          html += "Your priority date is <strong>" + (d1 ? (d1.years + " years " + d1.months + " months") : "") + "</strong> ahead of the Date for Filing cutoff.";
          html += '<div class="plain-explain"><div class="pe-label">In simple terms</div>If USCIS were accepting new filings this month, you would qualify. But they\'re not. The queue is paused.</div>';
        } else {
          var d2 = diffYearsMonths(pd, countryData.date_for_filing);
          html += "Your priority date is <strong>" + (d2 ? (d2.years + " years " + d2.months + " months") : "") + "</strong> more recent than the Date for Filing cutoff.";
          html += '<div class="plain-explain"><div class="pe-label">In simple terms</div>The queue is currently serving people who filed about ' + (d2 ? d2.years : "?") + ' years before you. Even when the queue unpauses in October, it needs to advance ' + (d2 ? (d2.years + " years " + d2.months + " months") : "significantly") + ' before reaching your priority date.</div>';
        }
      }
      html += '</div>';
    } else if (countryData.final_action_date === "CURRENT") {
      html += '<div class="status-banner current"><div class="head">Looks current</div>If USCIS is honoring this chart for your category this month and the rest of your case is ready, you may be able to file I-485. Confirm the controlling chart on the current Visa Bulletin.</div>';
    } else if (countryData.final_action_date) {
      var pdMs2 = parseIsoToMs(pd);
      var fadMs = parseIsoToMs(countryData.final_action_date);
      if (pdMs2 != null && fadMs != null) {
        if (pdMs2 <= fadMs) {
          html += '<div class="status-banner current"><div class="head">Looks current</div>Your priority date (' + esc(fmtDate(pd)) + ') is at or before the Final Action Date (' + esc(fmtDate(countryData.final_action_date)) + '). If USCIS is honoring this chart for your category this month and the rest of your case is ready, you may be able to file I-485. Confirm the controlling chart on the current Visa Bulletin.</div>';
        } else {
          var gap = diffYearsMonths(pd, countryData.final_action_date);
          if (gap && gap.years === 0 && gap.months === 0) {
            html += '<div class="status-banner current"><div class="head">Basically current</div>Your priority date lines up with the current Final Action Date.</div>';
          } else if (gap) {
            html += '<div class="status-banner waiting"><div class="head">Waiting</div>Your priority date (' + esc(fmtDate(pd)) + ') is <strong>' + gap.years + ' years ' + gap.months + ' months</strong> more recent than the current Final Action Date (' + esc(fmtDate(countryData.final_action_date)) + ').</div>';
            html += '<div class="plain-explain"><div class="pe-label">In simple terms</div>The government is currently processing green cards for people who filed about ' + gap.years + ' years before you. The queue needs to advance ' + gap.years + ' years ' + gap.months + ' months before reaching your priority date. Only then can you file your I-485 (the final green card application).</div>';
          }
        }
      }
    }
    // Honest caveat when the bulletin data for this country is not yet verified.
    if (countryData && countryData.verified === false) {
      html += '<p class="band-caveat" style="color:var(--amber-accent);margin-top:10px;"><strong>Not fully verified:</strong> ' + esc(countryLabel(country)) + ' bulletin data for ' + esc(cat) + ' is not yet independently verified. Confirm against travel.state.gov.</p>';
    }
    // Enrichment B: PERM stage
    html += permStageBlock();
    html += '</div>';

    // Cross-chargeability callout (between the personalized section and the reference bulletin section)
    // Wrapped in an anchor target so the hub "Cross-chargeability" lever can deep-link to it.
    html += '<div id="cross-charge">' + crossChargeBlock() + '</div>';

    // -- 2. CURRENT QUEUE STATE (shared/reference; was section 1) --
    var countryLabelForHeader = countryLabel(country);
    html += '<div class="result-block">';
    html += '<h3><span class="num">2</span>Current Queue State: ' + esc(cat) + ' ' + esc(countryLabelForHeader) + '</h3>';
    if (countryData && countryData._overridden) {
      html += '<div class="override-badge">Using your pasted ' + esc((state.bulletinOverride && state.bulletinOverride.monthLabel) || "latest") + ' bulletin (verified by you). Clear it in the paste box below to revert to the built-in data.</div>';
    }
    html += '<p class="help" style="margin-top:0;">This is the current bulletin cutoff for ' + esc(cat) + ' ' + esc(countryLabelForHeader) + '. It is the same for everyone in this category and does NOT vary by your priority date. Your comparison to it is above.</p>';

    // Per-cell confidence badge for this category+country cell.
    if (countryData) {
      html += confidenceBadge(countryData);
    }

    if (!countryData) {
      html += '<div class="status-banner unknown"><div class="head">No data</div>' +
        'We do not have bulletin data for ' + esc(cat) + " / " + esc(country) + '.</div>';
    } else if (countryData.verified === false) {
      html += '<div class="status-banner unknown"><div class="head">Data not verified in our source yet</div>' +
        'This category / country combination is not verified in the rulebook. Check the current bulletin directly at ' +
        extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "travel.state.gov") + '.</div>';
      if (countryData.status_note) {
        html += '<p class="help" style="margin-top:10px;">' + esc(countryData.status_note) + '</p>';
      }
    } else {
      html += '<div class="bulletin-row">';
      html += '<div class="bulletin-cell"><div class="label">Final Action Date <span style="font-weight:400;font-size:10px;color:var(--muted);">(per ' + esc(fmtMonth(rulebook.bulletin.as_of)) + ' bulletin)</span></div>';
      if (countryData.final_action_date === "CURRENT") {
        html += '<div class="value current">Current</div>';
        html += '<div class="sub">Your category has no backlog. Anyone with an approved I-140 can file I-485 immediately.</div>';
      } else if (countryData.final_action_date == null) {
        html += '<div class="value unavailable">Unavailable</div>';
        html += '<div class="sub">All visa numbers for this fiscal year are used up. No one can get approved. Resets October 1.</div>';
      } else {
        html += '<div class="value">' + esc(fmtDate(countryData.final_action_date)) + '</div>';
        html += '<div class="sub">People with priority dates before this date can file I-485 (the final green card application) and get approved.</div>';
      }
      html += '</div>';

      html += '<div class="bulletin-cell"><div class="label">Date for Filing <span style="font-weight:400;font-size:10px;color:var(--muted);">(per ' + esc(fmtMonth(rulebook.bulletin.as_of)) + ' bulletin)</span></div>';
      if (countryData.date_for_filing === "CURRENT") {
        html += '<div class="value current">Current</div>';
        html += '<div class="sub">Anyone can submit I-485. No wait for filing.</div>';
      } else if (countryData.date_for_filing == null) {
        html += '<div class="value" style="color:var(--muted);">Not published</div>';
        html += '<div class="sub">Not available this month.</div>';
      } else {
        html += '<div class="value">' + esc(fmtDate(countryData.date_for_filing)) + '</div>';
        var dffHonored = (countryData.final_action_date != null);
        if (dffHonored) {
          html += '<div class="sub">People with priority dates before this date may file I-485 if USCIS honors this chart this month.</div>';
        } else {
          html += '<div class="sub">Reference only. USCIS is not accepting I-485 filings under this chart this month because the Final Action Date is unavailable.</div>';
        }
      }
      html += '</div>';
      html += '</div>';
      html += '<div class="source-stamp-row">' + sourceStamp(countryData) + '</div>';
      html += '<p class="help" style="margin-top:6px;">Official source: ' +
        extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "travel.state.gov Visa Bulletin") + '</p>';
    }

    // (Queue-position timeline is now rendered in the answer-first lead above,
    // out of this collapsed section, so "how long" is visible without expanding.)

    html += '</div>';

    // Side-by-side scenario compare (only renders when A is a waiting projection)
    html += compareScenarioBlock(pd, cat, country);

    // -- PASTE-IN: newer bulletin (recomputes everything above) + consular waits --
    html += bulletinPasteBlock(cat, country);
    html += consularPasteBlock(cat);
    html += ivSchedulePasteBlock();

    // ---- category: How long you'll wait ----
    html += '</div></details>';
    html += '<details class="result-drop"><summary>How long you\'ll wait</summary><div class="result-drop-body">';

    // -- 3. WAIT BANDS --
    var bandKey = cat + " " + (country === "ROW" ? "" : country) + ", PD locked 2026";
    // Try both formats
    var bandData = rulebook.wait_estimates.bands[bandKey] ||
                   rulebook.wait_estimates.bands[cat + " " + country + ", PD locked 2026"];

    html += '<div class="result-block">';
    html += '<h3><span class="num">3</span>Realistic Wait Bands</h3>';
    if (bandData) {
      html += '<p class="help">For a priority date locked now. Ranges reflect the structural backlog. Legislative changes to country caps are the main thing that changes these dramatically.</p>';
      html += '<div class="wait-bands">';
      // Best
      html += '<div class="wait-band best"><div class="label">Best case</div>';
      html += '<div class="years">' + fmtBand(bandData.best_case_years) + '</div>';
      html += '<div class="years-sub">years</div></div>';
      // Typical
      html += '<div class="wait-band typical"><div class="label">Typical</div>';
      html += '<div class="years">' + fmtBand(bandData.typical_case_years) + '</div>';
      html += '<div class="years-sub">years</div></div>';
      // Worst
      html += '<div class="wait-band worst"><div class="label">Worst case</div>';
      html += '<div class="years">' + fmtBand(bandData.worst_case_years) + '</div>';
      html += '<div class="years-sub">years</div></div>';
      html += '</div>';
      if (bandData.worst_case_note) {
        html += '<p class="band-caveat"><strong>Worst-case note:</strong> ' + esc(bandData.worst_case_note) + '</p>';
      }
      if (bandData.changed_by) {
        html += '<p class="band-caveat"><strong>What could change this:</strong> ' + esc(bandData.changed_by) + '</p>';
      }
      if (bandData.verified === false && bandData.verification_note) {
        html += '<p class="band-caveat" style="color:var(--amber-accent);"><strong>Not fully verified:</strong> ' + esc(bandData.verification_note) + '</p>';
      }
    } else {
      html += '<div class="status-banner unknown"><div class="head">No wait-band estimate available</div>' +
        'We do not have a structural wait-band estimate for this category and country. Check tier-2 sources (Murthy, Fragomen, Green Card Clock) for their own models.</div>';
    }
    html += '</div>';

    // -- 4. TIMELINE UNLOCKS (AC21) --
    html += '<div class="result-block">';
    html += '<h3><span class="num">4</span>What Unlocks Along the Way</h3>';
    html += '<p class="help">Regardless of your priority date, these AC21 protections kick in as your case moves through PERM and I-140.</p>';
    html += '<ul class="timeline">';
    var provs = rulebook.ac21.provisions;
    var AC21_URL = "https://www.congress.gov/bill/106th-congress/house-bill/2870";
    ["106a", "104c", "106c"].forEach(function (key) {
      var p = provs[key];
      if (!p) return;
      html += '<li><strong>' + extLink(AC21_URL, p.name) + '</strong>';
      html += '<div class="trigger">Triggered by: ' + esc(p.trigger) + '</div>';
      var un = Array.isArray(p.unlocks) ? p.unlocks.join(". ") : p.unlocks;
      html += '<div class="unlocks">' + esc(un) + '</div>';
      if (p.practical_note) {
        html += '<div class="trigger" style="margin-top:4px;font-style:italic;">' + esc(p.practical_note) + '</div>';
      }
      html += '</li>';
    });
    html += '</ul>';
    if (rulebook.ac21.optimal_perm_timing) {
      html += '<p class="help" style="margin-top:8px;"><strong>Timing note.</strong> ' + esc(rulebook.ac21.optimal_perm_timing) + '</p>';
    }
    // Enrichment A: cap timing
    html += capTimingBlock();
    // Enrichment C: I-140 stage
    html += i140StageBlock();
    html += '</div>';

    // -- 5. PERM RESTART TRIGGERS --
    html += '<div class="result-block">';
    html += '<h3><span class="num">5</span>PERM Restart Triggers</h3>';
    html += '<div class="callout"><div class="head">Do not move jobs, locations, or entities without checking first.</div>';
    html += '<p style="margin:6px 0 6px;">These changes may reset your priority date. A title change by itself usually is not the deciding factor, and a salary change by itself usually is not either (unless it drops below the prevailing wage). What matters is whether the underlying job changes materially. These factors are considered together, so confirm with your attorney.</p>';
    html += '<ul>';
    rulebook.perm_restart_triggers.triggers.forEach(function (t) {
      html += '<li><strong>' + esc(t.name) + '.</strong>';
      if (t.example) html += ' Example: ' + esc(t.example.replace(/\.$/, "")) + '.';
      if (t.test) html += ' ' + esc(t.test);
      if (t.restart_condition) html += ' ' + esc(t.restart_condition);
      if (t.id === "location_change") {
        html += ' <a href="#location-matrix">See the internal move impact matrix below.</a>';
      }
      html += '</li>';
    });
    html += '</ul>';
    if (rulebook.perm_restart_triggers.danger_window) {
      html += '<p style="margin-top:8px;font-size:12.5px;"><strong>Danger window:</strong> ' + esc(rulebook.perm_restart_triggers.danger_window.when) + ' ' + esc(rulebook.perm_restart_triggers.danger_window.risk) + '</p>';
    }
    // Enrichment F: role-level restart
    html += restartRoleBlock();
    html += '</div>';
    html += '<details class="collapsible" style="margin-top:10px;"><summary>What is an MSA?</summary><div class="body">';
    html += 'The MSA (Metropolitan Statistical Area) is a US Census Bureau geographic definition. It is the legal test for whether a location change triggers PERM restart, NOT distance in miles and NOT state boundaries. Seattle and Bellevue are in the same MSA (lower risk on location grounds). Los Angeles and San Francisco are different MSAs, so a move between them is usually treated as a location change and often requires reassessment, even though both are in California. See ' +
      extLink("https://www.census.gov/programs-surveys/metro-micro/about/delineation-files.html", "Census Bureau delineation files") + ' for edge cases.';
    html += '</div></details>';
    html += '</div>';

    // -- 6. INTERNAL MOVE IMPACT MATRIX (always renders) --
    var nextNum = 6;
    html += impactMatrixSection(nextNum);
    nextNum++;

    // -- IF PERM STALLS / IS PAUSED --
    html += permStallBlock();

    // ---- category: Other paths ----
    html += '</div></details>';
    html += '<details class="result-drop"><summary>Other paths</summary><div class="result-drop-body">';

    // -- STRATEGIES --
    html += '<div class="result-block strategies" id="strategies-block">';
    html += '<h3><span class="num">' + nextNum + '</span>Strategies</h3>';
    nextNum++;
    html += '<p class="help">Alternate paths people in the queue consider. Click each to expand.</p>';
    var strategies = [
      { key: "eb2_niw", one: "Self-petition; useful mainly as portability insurance if you may change employers." },
      { key: "eb1b_outstanding_researcher", one: "Employer-sponsored; realistic only for published researchers." },
      { key: "eb3_downgrade", one: "File a second I-140 under EB-3 if that queue is ahead of EB-2." },
      { key: "cross_chargeability", name: "Cross-chargeability", one: "Charge to spouse's country of birth per INA §202(b) if their queue is shorter." }
    ];
    strategies.forEach(function (s) {
      var d = rulebook.strategies[s.key];
      if (!d) return;
      html += '<details class="collapsible"><summary><span class="name">' + esc(s.name || d.name || s.key) + '</span><span class="one-liner">: ' + esc(s.one) + '</span></summary><div class="body">';
      if (d.shape) html += '<p><strong>Shape.</strong> ' + esc(d.shape) + '</p>';
      if (d.priority_date) html += '<p><strong>Priority date.</strong> ' + esc(d.priority_date) + '</p>';
      if (d.value_proposition) html += '<p><strong>Value.</strong> ' + esc(d.value_proposition) + '</p>';
      if (d.typical_evidence_bar) html += '<p><strong>Evidence bar.</strong> ' + esc(d.typical_evidence_bar) + '</p>';
      if (d.typical_fit) html += '<p><strong>Typical fit.</strong> ' + esc(d.typical_fit) + '</p>';
      if (d.when_useful) html += '<p><strong>When useful.</strong> ' + esc(d.when_useful) + '</p>';
      if (d.risk) html += '<p><strong>Risk.</strong> ' + esc(d.risk) + '</p>';
      if (d.attorney_type) html += '<p><strong>Attorney.</strong> ' + esc(d.attorney_type) + '</p>';
      if (d.cost_range_usd) html += '<p><strong>Cost.</strong> $' + d.cost_range_usd[0].toLocaleString() + " to $" + d.cost_range_usd[1].toLocaleString() + ' (out of pocket).</p>';
      if (d.requirements && Array.isArray(d.requirements)) {
        html += '<p><strong>Requirements.</strong></p><ul style="margin:4px 0 0 18px;">';
        d.requirements.forEach(function (r) { html += '<li>' + esc(r) + '</li>'; });
        html += '</ul>';
      }
      // Enrichment E: NIW framing when applicable
      if (s.key === "eb2_niw") {
        html += niwFrameBlock();
      }
      if (d.cite) html += '<p style="font-size:11.5px;color:var(--muted);margin-top:8px;"><strong>Citation.</strong> ' + esc(d.cite) + '</p>';
      html += '</div></details>';
    });
    html += '</div>';

    // ---- category: How we estimate this ----
    html += '</div></details>';
    html += '<details class="result-drop"><summary>How we estimate this</summary><div class="result-drop-body">';

    // -- NOT-IN-SCOPE --
    html += '<div class="result-block">';
    html += '<h3><span class="num">' + nextNum + '</span>What This Tool Doesn\'t Do</h3>';
    html += '<p class="small-print">The rulebook that powers this tool explicitly leaves the following out of scope:</p>';
    html += '<div class="small-print"><ul>';
    rulebook.meta.not_in_scope.forEach(function (item) {
      html += '<li>' + esc(item) + '</li>';
    });
    html += '</ul></div>';
    html += '</div>';

    // ---- category: Resources & next steps ----
    html += '</div></details>';
    html += '<details class="result-drop"><summary>Resources &amp; next steps</summary><div class="result-drop-body">';

    // -- NEXT STEPS --
    html += nextStepsBlock();

    // -- EB-1 INFO (only for EB-1 users; it doesn't apply to EB-2/EB-3 and just
    //    added noise to their breakdown) --
    if (cat === "EB-1") {
      html += '<div class="result-block">';
      html += eb1InfoBlock();
      html += '</div>';
    }

    // -- F-1 OPT/STEM INFO (only for people actually on F-1/OPT) --
    if ((state.workVisa || []).indexOf("F-1") !== -1) {
      html += '<div class="result-block">';
      html += '<h3><span class="num" style="background:var(--warning-900);">i</span>F-1 OPT / STEM OPT Pathway</h3>';
      html += f1OptPanel();
      html += '</div>';
    }

    // -- RESOURCES --
    html += '<div class="result-block">';
    html += resourcesSection();
    html += '</div>';

    // -- COMMUNITY CHATTER (unverified snapshot, loaded async) --
    html += communitySnapshotPlaceholder();

    // -- WHERE TO GO NEXT (guide the next action so the result is not a dead end) --
    html += '<div class="result-block next-steps">';
    html += '<h3>Where to go next</h3>';
    html += '<div class="ns-grid">';
    html += '<a class="ns-card" href="tools.html">Read the current Visa Bulletin<span>See the live cutoff dates for your category and how they have moved over time.</span></a>';
    html += '<a class="ns-card" href="glossary.html">Look up a term<span>Plain-language definitions for PERM, priority date, and the rest of the jargon.</span></a>';
    html += '<a class="ns-card" href="resources.html">Official sources and legal help<span>Government pages and trusted guides for questions about your own case.</span></a>';
    html += '</div></div>';

    // Close the last dropdown category and the breakdown wrapper before the shared
    // footer, so the Start over / Print / sources footer stays visible.
    html += '</div></details>';
    html += '</div>';

    // -- FOOTER --
    html += '<div class="result-footer">';
    html += '<button class="reset-inline" type="button" id="resetInlineBtn">Start over</button>';
    html += printButtonHtml();
    html += '<div>Data last verified: <strong>' + esc(rulebook.meta.last_verified) + '</strong>.</div>';
    html += '<div style="margin-top:6px;">Primary sources: ';
    var srcParts = [];
    rulebook.meta.primary_sources.forEach(function (s) {
      srcParts.push(extLink(s.url, s.name));
    });
    html += srcParts.join(" · ");
    html += '</div>';
    html += '<div style="margin-top:10px;font-size:11.5px;">A rough, personal projection. Confirm your own case with a licensed immigration attorney.</div>';
    html += '</div>';

    resultContent.innerHTML = html;
    wireResultInteractions();
  }

  // Bind all post-render interactions. Called after every result render (EB, PRE,
  // and — via its own path — F-1) so it must be null-safe: querySelectors simply
  // find nothing when a given section isn't present.
  function wireResultInteractions() {
    // Acronym glossary tooltips for the freshly-rendered result (hero / hub /
    // breakdown). The site-wide pass runs once at load, before the result exists,
    // so we re-run it scoped to #result-content after each render. Each render
    // replaces the container's HTML, so this is idempotent (fresh nodes) and gets
    // its own first-occurrence scope independent of the questionnaire prose above.
    if (resultContent && window.GCN_glossify) window.GCN_glossify(resultContent);

    // Pre-PERM "explore the full timeline" toggle: reveals the dimmed later-stage columns.
    var exploreBtn = document.getElementById("imp-explore-toggle");
    if (exploreBtn) {
      exploreBtn.addEventListener("click", function () {
        var tbl = document.getElementById("imp-matrix-table");
        var cards = document.getElementById("imp-mobile-cards");
        var nowFocused = tbl && tbl.classList.contains("imp-focus-now");
        if (tbl) tbl.classList.toggle("imp-focus-now");
        if (cards) cards.classList.toggle("imp-focus-now");
        var expanded = !nowFocused; // after toggle: was focused -> now expanded
        exploreBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
        exploreBtn.innerHTML = expanded
          ? "Focus on where I am now (before PERM) &larr;"
          : "See how an internal move affects you at each later stage (once PERM starts) &rarr;";
      });
    }

    // Sort button handlers for the impact matrix
    var sortBtns = resultContent.querySelectorAll(".imp-sort-btn");
    sortBtns.forEach(function(btn) {
      btn.addEventListener("click", function() {
        sortBtns.forEach(function(b) { b.classList.remove("active"); });
        btn.classList.add("active");
        var mode = btn.getAttribute("data-sort");
        var here = currentStageColumn();
        var indices = IMPACT_ROWS.map(function(_, i) { return i; });

        if (mode === "risk-asc") {
          indices.sort(function(a, b) { return impRiskScore(IMPACT_ROWS[a]) - impRiskScore(IMPACT_ROWS[b]); });
        } else if (mode === "risk-desc") {
          indices.sort(function(a, b) { return impRiskScore(IMPACT_ROWS[b]) - impRiskScore(IMPACT_ROWS[a]); });
        } else if (mode === "alpha") {
          indices.sort(function(a, b) {
            var nameA = IMPACT_ROWS[a].scenario.replace(/<[^>]*>/g, "");
            var nameB = IMPACT_ROWS[b].scenario.replace(/<[^>]*>/g, "");
            return nameA.localeCompare(nameB);
          });
        } else if (mode === "relevance") {
          indices.sort(function(a, b) { return impColRisk(IMPACT_ROWS[a], here) - impColRisk(IMPACT_ROWS[b], here); });
        }

        // Re-order table rows
        var tbody = document.getElementById("imp-matrix-body");
        if (tbody) {
          indices.forEach(function(ri) {
            var tr = tbody.querySelector('tr[data-row-idx="' + ri + '"]');
            if (tr) tbody.appendChild(tr);
          });
        }
        // Re-order mobile cards
        var mobileWrap = document.getElementById("imp-mobile-cards");
        if (mobileWrap) {
          indices.forEach(function(ri) {
            var card = mobileWrap.querySelector('.imp-mobile-card[data-row-idx="' + ri + '"]');
            if (card) mobileWrap.appendChild(card);
          });
        }
      });
    });

    // Hub deep-links: the target now lives inside one of the labeled dropdown
    // categories, so open every <details> ancestor of the target (not a single
    // fixed one) before scrolling. External page links (no leading #) behave normally.
    var hubLinks = resultContent.querySelectorAll("a.gc-hub-link");
    hubLinks.forEach(function (a) {
      a.addEventListener("click", function (e) {
        var href = a.getAttribute("href") || "";
        if (href.charAt(0) !== "#") return;
        e.preventDefault();
        var target = document.getElementById(href.slice(1));
        if (target) {
          var node = target;
          while (node && node !== resultContent) {
            if (node.tagName && node.tagName.toLowerCase() === "details") node.open = true;
            node = node.parentNode;
          }
          if (target.scrollIntoView) {
            window.requestAnimationFrame(function () {
              target.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
            });
          }
        }
      });
    });

    var inlineBtn = document.getElementById("resetInlineBtn");
    if (inlineBtn) inlineBtn.addEventListener("click", resetAll);

    wireQueueProjector();
    wireCompare();

    // Wire the paste-in cards (bulletin override + consular estimate).
    wirePasteIns();
  }

  // Bind handlers for the paste-in cards. Re-run after every render because
  // renderResult() rebuilds the DOM. All parsing is local + deterministic.
  function wirePasteIns() {
    var cat = state.category, country = state.country;
    var tableKind = visaType(cat).table; // 'employment' | 'family' (undefined for niv)

    // Shared: render the parse preview + wire the "Apply these dates" confirm.
    // Used by BOTH the paste-text path and the drop-a-PDF path.
    function showBulletinPreview(res, prev, sourceNote) {
      prev.style.display = "block";
      if (!res.ok) {
        prev.innerHTML = '<div class="paste-error">' +
          esc(res.error === "empty"
            ? "Nothing to read yet."
            : (res.msg || "Couldn't read that. Copy the Employment-Based table from the bulletin, or drop the bulletin PDF, and try again.")) +
          '</div>';
        return;
      }
      var items = [];
      if (res.fadFound) items.push("Final Action Date: <strong>" + esc(labelForBulletinValue(res.fad)) + "</strong>");
      if (res.dffFound) items.push("Date for Filing: <strong>" + esc(labelForBulletinValue(res.dff)) + "</strong>");
      var ph = '<div class="paste-active-head">Here\'s what I read for ' + esc(cat) + ' ' + esc(countryLabel(country)) +
        (res.monthLabel ? ' (' + esc(res.monthLabel) + ' bulletin)' : '') + ':</div>';
      if (sourceNote) ph += '<p style="margin:6px 0 0;font-size:12px;color:var(--text-soft);">' + esc(sourceNote) + '</p>';
      ph += '<ul style="margin:8px 0 0 18px;font-size:13.5px;">' +
        items.map(function (l) { return '<li>' + l + '</li>'; }).join("") + '</ul>';
      // Echo the exact row(s) matched from the paste so a wrong read (e.g. an
      // EB-4/EB-5 set-aside sub-row, or wrapped columns) is caught by the user.
      var matched = [];
      if (res.faLine) matched.push(res.faLine);
      if (res.dffLine && res.dffLine !== res.faLine) matched.push(res.dffLine);
      if (matched.length) {
        ph += '<p style="margin:10px 0 2px;font-size:11.5px;color:var(--text-soft);">Read from this row in your paste. Check it is your <strong>' + esc(cat) + '</strong> row:</p>';
        ph += matched.map(function (m) {
          return '<pre style="margin:0 0 4px;padding:6px 9px;background:var(--neutral-150);border-radius:6px;font-size:11.5px;white-space:pre-wrap;word-break:break-word;">' + esc(m) + '</pre>';
        }).join("");
      }
      // Opt-in month-over-month diff (vs the last bulletin saved on this device), then save.
      var vbHtml = vbDiffHtml(cat, country, res);
      if (vbHtml) ph += vbHtml;
      vbMaybeSave(cat, country, res);
      if (standaloneToolsMode) {
        // Live tools page: no queue position to recompute, so this read IS the
        // result. Add a short plain-English gloss of what the two dates mean.
        ph += '<p style="margin:10px 0 0;font-size:12.5px;color:var(--text-soft);">' +
          '<strong>Final Action Date</strong> is the cutoff for your green card to be <em>approved</em>; ' +
          '<strong>Date for Filing</strong> is the (usually earlier) cutoff for <em>submitting</em> your application. ' +
          'Your priority date must be before the relevant cutoff. Confirm against the official bulletin above. Not legal advice.</p>';
        prev.innerHTML = ph;
        return;
      }
      ph += '<p style="margin:10px 0 0;font-size:12.5px;color:var(--text-soft);">If that matches the official page, apply it to recompute your position above.</p>';
      ph += '<button type="button" class="paste-btn" id="bp-confirm" style="margin-top:10px;">Apply these dates</button>';
      prev.innerHTML = ph;
      var conf = document.getElementById("bp-confirm");
      if (conf) {
        conf.addEventListener("click", function () {
          state.bulletinOverride = {
            cat: cat, country: country,
            fadFound: res.fadFound, fad: res.fad,
            dffFound: res.dffFound, dff: res.dff,
            monthLabel: res.monthLabel
          };
          renderResult();
          var anchor = document.getElementById("stepResult") || document.getElementById("step-result");
          if (anchor && anchor.scrollIntoView) anchor.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }
    }

    // Friendly message when the user pastes a LINK instead of the table/PDF.
    function showUrlMessage(prev, url) {
      prev.style.display = "block";
      var openLink = url
        ? ' ' + extLink(url, "Open this link") + ' in a new tab to download it.'
        : '';
      prev.innerHTML = '<div class="paste-error" style="font-weight:600;">That looks like a link.</div>' +
        '<p style="margin:8px 0 0;font-size:13px;color:var(--text);">This tool can\'t open links for you. The government site blocks automated access, so only a real browser tab can load it.' + openLink +
        ' Then either <strong>drop the PDF file</strong> above (Option A), or <strong>copy the two Employment-Based tables and paste the text</strong> (Option B).</p>';
    }

    var bpParse = document.getElementById("bp-parse");
    if (bpParse) {
      bpParse.addEventListener("click", function () {
        var ta = document.getElementById("bp-input");
        var prev = document.getElementById("bp-preview");
        if (!ta || !prev) return;
        var val = ta.value || "";
        if (looksLikeUrl(val)) { showUrlMessage(prev, extractFirstUrl(val)); return; }
        var res = parseVisaBulletin(val, cat, country, tableKind);
        showBulletinPreview(res, prev);
      });
    }

    // ---- Option A: drop / choose a PDF ----
    var drop = document.getElementById("bp-drop");
    var fileInput = document.getElementById("bp-file");
    var pdfStatus = document.getElementById("bp-pdf-status");
    function setPdfStatus(msg, isError) {
      if (!pdfStatus) return;
      pdfStatus.style.display = "block";
      pdfStatus.innerHTML = '<span' + (isError ? ' class="paste-error"' : '') + '>' + esc(msg) + '</span>';
    }
    function handlePdfFile(file) {
      var prev = document.getElementById("bp-preview");
      if (!file) return;
      var isPdf = (file.type === "application/pdf") || /\.pdf$/i.test(file.name || "");
      if (!isPdf) { setPdfStatus("That's not a PDF. Drop the bulletin PDF you downloaded, or use Option B below.", true); return; }
      setPdfStatus("Reading your PDF…");
      var reader = new FileReader();
      reader.onerror = function () { setPdfStatus("Couldn't read that file. Try again, or use Option B below.", true); };
      reader.onload = function () {
        extractPdfText(reader.result).then(function (text) {
          if (!text || !text.replace(/\s/g, "")) {
            setPdfStatus("This PDF has no readable text (it may be a scanned image). Use Option B: copy the tables and paste the text.", true);
            return;
          }
          var res = parseVisaBulletin(text, cat, country, tableKind);
          if (!res.ok) {
            setPdfStatus("Read the PDF, but couldn't find your " + cat + " row in it. Make sure it's the current Visa Bulletin, or use Option B.", true);
            if (prev) { prev.style.display = "none"; }
            return;
          }
          setPdfStatus("Read your PDF successfully.");
          if (prev) showBulletinPreview(res, prev, "From the PDF you dropped in (read in your browser).");
        }).catch(function (err) {
          var m = (err && err.message) || "";
          if (m === "pdfjs-load-failed" || m === "pdfjs-not-available") {
            setPdfStatus("Couldn't load the PDF reader (you may be offline or a CDN is blocked). Use Option B: copy the tables and paste the text instead.", true);
          } else {
            setPdfStatus("Couldn't parse that PDF. Use Option B: copy the tables and paste the text instead.", true);
          }
        });
      };
      try { reader.readAsArrayBuffer(file); }
      catch (e) { setPdfStatus("Couldn't read that file. Use Option B below.", true); }
    }
    if (drop && fileInput) {
      drop.addEventListener("click", function () { fileInput.click(); });
      drop.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
      });
      fileInput.addEventListener("change", function () {
        if (fileInput.files && fileInput.files[0]) handlePdfFile(fileInput.files[0]);
      });
      ["dragenter", "dragover"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); drop.classList.add("dragover"); });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); drop.classList.remove("dragover"); });
      });
      drop.addEventListener("drop", function (e) {
        var dt = e.dataTransfer;
        if (!dt) return;
        // If the user dragged selected TEXT or a link rather than a file:
        if ((!dt.files || !dt.files.length) && dt.getData) {
          var dropped = dt.getData("text/plain") || dt.getData("text/uri-list") || "";
          var prev = document.getElementById("bp-preview");
          if (dropped && prev) {
            if (looksLikeUrl(dropped)) { showUrlMessage(prev, extractFirstUrl(dropped)); return; }
            var res = parseVisaBulletin(dropped, cat, country, tableKind);
            showBulletinPreview(res, prev);
            return;
          }
        }
        if (dt.files && dt.files[0]) handlePdfFile(dt.files[0]);
      });
    }

    var bpClear = document.getElementById("bp-clear");
    if (bpClear) {
      bpClear.addEventListener("click", function () {
        state.bulletinOverride = null;
        renderResult();
      });
    }

    var vbCb = document.getElementById("vb-remember-cb");
    if (vbCb) vbCb.addEventListener("change", function () { vbSetRemember(vbCb.checked); });
    var vbClearBtn = document.getElementById("vb-remember-clear");
    if (vbClearBtn) vbClearBtn.addEventListener("click", function () {
      vbHistoryClear();
      vbClearBtn.textContent = "Cleared";
      window.setTimeout(function () { if (vbClearBtn) vbClearBtn.textContent = "Clear saved"; }, 1500);
    });

    var csParse = document.getElementById("cs-parse");
    if (csParse) {
      csParse.addEventListener("click", function () {
        var sel = document.getElementById("cs-consulate");
        var qtyEl = document.getElementById("cs-qty");
        var unitEl = document.getElementById("cs-unit");
        var out = document.getElementById("cs-out");
        if (!sel || !qtyEl || !unitEl || !out) return;
        out.style.display = "block";
        var qty = parseFloat(String(qtyEl.value).replace(/,/g, "").trim());
        if (isNaN(qty) || qty <= 0) {
          out.innerHTML = '<div class="paste-error">Enter a number (for example 45), then choose days, weeks, months, or years from the dropdown.</div>';
          return;
        }
        var unit = unitEl.value;
        var factor = unit === "years" ? 365 : unit === "months" ? 30 : unit === "weeks" ? 7 : 1;
        var days = Math.round(qty * factor);
        state.consular = { consulate: sel.value, days: days, qty: qty, unit: unit };
        out.innerHTML = consularOutputHtml(sel.value, days);
      });
    }

    var ivParse = document.getElementById("iv-parse");
    if (ivParse) {
      ivParse.addEventListener("click", function () {
        var sel = document.getElementById("iv-consulate");
        var inp = document.getElementById("iv-month");
        var upd = document.getElementById("iv-updated");
        var out = document.getElementById("iv-out");
        if (!sel || !inp || !out) return;
        var parsed = parseIvMonth(inp.value);
        out.style.display = "block";
        if (!parsed) {
          out.innerHTML = '<div class="paste-error">Enter the scheduling month like &ldquo;Jun-2026&rdquo;, &ldquo;June 2026&rdquo;, or &ldquo;06/2026&rdquo;.</div>';
          return;
        }
        state.ivSchedule = {
          consulate: sel.value,
          year: parsed.year, month: parsed.month, label: parsed.label,
          rawInput: inp.value,
          updated: (upd && upd.value.trim()) ? upd.value.trim() : null
        };
        out.innerHTML = ivScheduleOutputHtml(state.ivSchedule);
      });
    }

    // Load the same-origin community-chatter snapshot (hidden if absent/empty).
    // Runs on every render path (EB, PRE, F-1) since all call wirePasteIns().
    loadCommunitySnapshot();
  }

  function fmtBand(b) {
    if (b == null) return "?";
    if (Array.isArray(b)) {
      if (b.length === 2) return b[0] + "–" + b[1];
      return b.join("–");
    }
    return String(b);
  }

  // ============================================================
  // HUB PAGE: reusable disclaimer, process explainer, live-tools,
  // standalone resources, and sticky-nav active-highlight.
  // Additive — none of this touches the questionnaire or results.
  // ============================================================

  // ---- Reusable "not legal advice" disclaimer helper ----
  // One muted-italic note, used on every advice-giving section so the wording
  // stays consistent. kind:
  //   "general" -> not legal advice + verify official sources
  // One note, one wording. There is deliberately no employer-specific variant:
  // the tool does not know or describe any company's internal process, and the
  // general note already routes the reader to their own counsel.
  function adviceNote() {
    var general = '<strong>This is general information, not legal advice, and not official guidance.</strong> ' +
      'Timelines and rules change, so always confirm against official sources (' +
      '<a href="https://www.uscis.gov" target="_blank" rel="noopener">uscis.gov</a>, ' +
      '<a href="https://travel.state.gov" target="_blank" rel="noopener">travel.state.gov</a>, ' +
      '<a href="https://flag.dol.gov" target="_blank" rel="noopener">flag.dol.gov</a>) ' +
      'and check with your employer’s immigration counsel or a licensed immigration attorney before making any decisions.';
    return '<p class="advice-note">' + general + '</p>';
  }

  // ---- Process explainer: end-to-end EB green card flow ----
  // Builds the clickable/expandable stage flow in #process-flow. All durations
  // are read from the rulebook (no hardcoded duplicates).
  function renderProcessExplainer() {
    var flow = document.getElementById("process-flow");
    if (!flow) return;
    var perm = rulebook.perm || {};
    var i140 = rulebook.i140 || {};
    var i485 = rulebook.i485 || {};
    var pp = i140.premium_processing || {};

    var permDur = perm.total_duration_months ? fmtBand(perm.total_duration_months) + " months" : "~1–2 years";
    var i140Reg = (i140.regular_processing_months != null) ? "~" + i140.regular_processing_months + " months" : "several months";
    var i140Prem = pp.duration_business_days ? pp.duration_business_days + " business days with premium processing" : null;
    var i485Dur = i485.total_duration_months ? fmtBand(i485.total_duration_months) + " months" : "several months";

    var stages = [
      {
        title: "Maintain status while you wait",
        sub: "H-1B, L-1, O-1, or F-1: before and during the process",
        when: "Ongoing",
        body:
          '<p>Before the green card process starts you’re in the US on a nonimmigrant status (most often H-1B). Keeping that status valid is what lets you stay and work while everything below plays out.</p>' +
          '<p class="who"><strong>Who runs it:</strong> you and your employer, with your employer’s immigration counsel.</p>' +
          '<p class="gotcha">' + extLink("https://www.congress.gov/bill/106th-congress/house-bill/2870", "AC21") + ' lets H-1B extend past the 6-year cap once the green card process is far enough along: 1-year extensions once PERM has been pending 365+ days (§106(a)), or 3-year extensions after the I-140 is approved (§104(c)). Timing the start well is what keeps status from lapsing during a long wait.</p>'
      },
      {
        title: "PERM labor certification",
        sub: "Prevailing Wage Determination → Recruitment → ETA 9089 filed with DOL",
        when: permDur,
        body:
          '<p>Your employer proves no qualified US worker is available: it gets a Prevailing Wage Determination, runs a recruitment campaign, then files the ' + extLink("https://www.ecfr.gov/current/title-20/chapter-V/part-656", "ETA 9089") + ' with the Department of Labor.</p>' +
          '<p class="who"><strong>Who runs it:</strong> your employer and its immigration counsel. This is employer-driven, not something you file yourself.</p>' +
          '<p class="gotcha">The day DOL <em>receives</em> the ETA 9089 becomes your priority date, the single most important date in the whole process. A random audit can add roughly 9 more months.</p>'
      },
      {
        title: "I-140 immigrant petition",
        sub: "Employer petitions USCIS to classify you in an EB category",
        when: i140Reg + (i140Prem ? " (or " + i140Prem + ")" : ""),
        body:
          '<p>With PERM approved, your employer files the ' + extLink("https://www.uscis.gov/i-140", "I-140") + ' with USCIS to establish your EB-2 or EB-3 classification and lock your priority date to you.</p>' +
          '<p class="who"><strong>Who runs it:</strong> your employer files; USCIS adjudicates.</p>' +
          '<p class="gotcha">Approval unlocks the good stuff: your priority date becomes portable to a new employer, 3-year H-1B extensions (AC21 §104(c)), and H-4 EAD eligibility for a spouse.</p>'
      },
      {
        title: "Wait for your priority date to become current",
        sub: "The Visa Bulletin backlog: where most of the wait lives",
        when: "Months to many years",
        body:
          '<p>You can only move to the final step once your priority date is current on the ' + extLink("https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", "Visa Bulletin") + ' for your category and country of chargeability. For most countries this is short; for India and China EB-2/EB-3 it can be many years.</p>' +
          '<p class="who"><strong>Who runs it:</strong> nobody you can push. It’s driven by annual per-country visa caps set by law.</p>' +
          '<p class="gotcha">Dates move backward (retrogress) as well as forward, and a category can go &ldquo;unavailable&rdquo; late in a fiscal year. Your personalized position is in <a href="status.html">Check My Status</a>.</p>'
      },
      {
        title: "I-485 adjustment of status (or consular processing)",
        sub: "Final green card application, once a visa is available",
        when: i485Dur,
        body:
          '<p>When your date is current you file ' + extLink("https://www.uscis.gov/i-485", "Form I-485") + ' to adjust status (if you’re in the US), usually alongside a work permit (I-765) and travel document (I-131). If you’re abroad, you go through consular processing instead.</p>' +
          '<p class="who"><strong>Who runs it:</strong> you file; USCIS (or a US consulate) adjudicates, typically with biometrics and sometimes an interview.</p>' +
          '<p class="gotcha">You can only file this month if your priority date is current on whichever chart USCIS honors (Final Action Dates or Dates for Filing).</p>'
      },
      {
        title: "Green card issued",
        sub: "Lawful permanent residence",
        when: "The finish line",
        body:
          '<p>On approval you become a lawful permanent resident. After the required period as a permanent resident you may become eligible to apply for naturalization.</p>' +
          '<p class="who"><strong>Who runs it:</strong> USCIS issues the card.</p>'
      }
    ];

    var html = "";
    for (var i = 0; i < stages.length; i++) {
      var s = stages[i];
      var open = (i === 0);
      var bodyId = "process-stage-body-" + i;
      html += '<div class="process-stage' + (open ? " open" : "") + '" role="listitem">';
      html += '<button class="process-stage-btn" type="button" aria-expanded="' + (open ? "true" : "false") + '" aria-controls="' + bodyId + '">';
      html += '<span class="process-stage-idx">' + (i + 1) + '</span>';
      html += '<span class="process-stage-head"><span class="pst">' + esc(s.title) + '</span><span class="psd">' + s.sub + '</span></span>';
      html += '<span class="process-stage-when">' + esc(s.when) + '</span>';
      html += '<span class="process-stage-toggle" aria-hidden="true">' + (open ? "Hide" : "Show details") + '</span>';
      html += '<span class="process-stage-chev" aria-hidden="true">&rsaquo;</span>';
      html += '</button>';
      html += '<div class="process-stage-body" id="' + bodyId + '">' + s.body + '</div>';
      html += '</div>';
    }
    flow.innerHTML = html;

    // One advice note for the whole explainer (it gives timing/strategy guidance
    // placed right after the flow.
    flow.insertAdjacentHTML("afterend", adviceNote());

    // Accordion wiring — click / keyboard toggles each stage.
    var btns = flow.querySelectorAll(".process-stage-btn");
    for (var b = 0; b < btns.length; b++) {
      btns[b].addEventListener("click", function () {
        var stage = this.parentNode;
        var isOpen = stage.classList.toggle("open");
        this.setAttribute("aria-expanded", isOpen ? "true" : "false");
        var toggle = this.querySelector(".process-stage-toggle");
        if (toggle) { toggle.textContent = isOpen ? "Hide" : "Show details"; }
      });
    }
  }

  // ---- Live tools grid + standalone resources ----
  function populateHubStatics() {
    var res = document.getElementById("resources-standalone");
    if (res) { res.innerHTML = resourcesSection(false); }

    var tools = document.getElementById("tools-links");
    if (tools) {
      var links = [
        { name: "Visa Bulletin", url: "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html", desc: "The monthly cutoff dates that decide when you can file. Paste it into Check My Status to update this tool." },
        { name: "USCIS Processing Times", url: "https://egov.uscis.gov/processing-times/", desc: "Current processing times for I-140, I-485, and other forms, by service center." },
        { name: "USCIS Case Status", url: "https://egov.uscis.gov/casestatus/landing.do", desc: "Track a specific receipt number through adjudication." },
        { name: "DOL FLAG (PERM / PWD)", url: "https://flag.dol.gov/processingtimes", desc: "Live PERM and Prevailing Wage Determination processing queue." },
        { name: "Consular Visa Wait Times", url: "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/wait-times.html", desc: "Interview appointment backlog by consular post, for consular processing." }
      ];
      var th = "";
      for (var i = 0; i < links.length; i++) {
        var l = links[i];
        th += '<div class="resource-card"><h5>' + esc(l.name) + '</h5>';
        th += '<p>' + esc(l.desc) + '</p>';
        th += '<a href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(l.url.replace("https://", "").replace("http://", "")) + '</a>';
        th += '</div>';
      }
      tools.innerHTML = th;
    }

    var td = document.getElementById("tools-disclaimer");
    if (td) {
      td.innerHTML = 'These open the official government sites in a new tab. Bring the numbers back to the interactive parsers below: a paste-in Visa Bulletin reader, a consular wait-time estimate, and immigrant-visa interview scheduling. This tool never fetches these sites for you; you copy the numbers in yourself, and everything is read in your browser.';
    }
  }

  // ---- H-1B Process Checklist (tools.html only) ----
  // A checkable, progress-tracked walk through the H-1B journey. The single most
  // important control is the fork (change of status vs consular processing): it
  // gates whether the consular phase is shown and counted. Persists ONLY which
  // steps are ticked and the fork choice under gc_h1b_checklist — never any
  // personal data. Mirrors the gc_remember_bulletins opt-in localStorage pattern.
  // No-ops entirely on pages without the #h1b-checklist marker; with JS off the
  // static fallback markup in tools.html stays fully readable.
  function renderH1bChecklist() {
    var host = document.getElementById("h1b-checklist");
    if (!host) return;

    var KEY = "gc_h1b_checklist";

    // Official links. These open government pages in a new tab; the tool never
    // fetches them. The appointment/fee portal is COUNTRY-SPECIFIC and is never
    // hardcoded to one URL (see portalNote below).
    var DS160 = "https://ceac.state.gov/genniv/";
    var CEAC_STATUS = "https://ceac.state.gov/CEACStatTracker/Status.aspx";
    var IW = "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/interview-waiver-update.html";
    var H1B_OVERVIEW = "https://www.uscis.gov/working-in-the-united-states/temporary-workers/h-1b-specialty-occupations";
    var H1B_REG = "https://www.uscis.gov/working-in-the-united-states/temporary-workers/h-1b-specialty-occupations/h-1b-electronic-registration-process";
    var I129 = "https://www.uscis.gov/i-129";
    var I907 = "https://www.uscis.gov/i-907";
    var I94 = "https://i94.cbp.dhs.gov/";
    var CASE_STATUS = "https://egov.uscis.gov/casestatus/landing.do";
    var PROC_TIMES = "https://egov.uscis.gov/processing-times/";
    var FLAG = "https://flag.dol.gov/";
    var DOL_H1B = "https://www.dol.gov/agencies/eta/foreign-labor/programs/h-1b";
    // WAITTIME_URL is defined in the outer scope (global visa appointment waits).

    // Internal link to another tool tab on this page. The tab IIFE picks up the
    // hash change and activates the matching panel.
    function inLink(id, text) {
      return '<a href="#' + id + '">' + esc(text) + '</a>';
    }

    // The country-specific appointment/fee portal. Deliberately NOT one URL.
    var portalNote = "your country's official U.S. visa appointment website. This differs by country, so start from your U.S. embassy's website. Most countries use " +
      extLink("https://www.ustraveldocs.com/", "ustraveldocs.com/&lt;your country&gt;") +
      " and some use " + extLink("https://ais.usvisa-info.com/", "ais.usvisa-info.com") +
      " instead. Confirm which system your country uses rather than assuming.";

    var phase1 = [
      { id: "h1b-1", tag: "Employer &amp; counsel", title: "Registration and lottery",
        what: "For cap-subject roles, your employer electronically registers you in the annual H-1B registration (it typically opens in March). If registrations exceed the cap, USCIS runs a random lottery to pick who may file a petition. Cap-exempt employers (universities, non-profit or government research organizations) skip the lottery.",
        links: [extLink(H1B_REG, "USCIS H-1B electronic registration"), extLink(H1B_OVERVIEW, "USCIS H-1B specialty occupations overview")],
        note: "The registration window, fee, and selection odds change every year, so confirm them on the USCIS page. Selection has run around 30% in recent years, but do not treat any single year's rate as current." },
      { id: "h1b-lca", tag: "Employer &amp; counsel", title: "Labor Condition Application (LCA)",
        what: "Before the petition, your employer (usually through counsel) files a Labor Condition Application, Form ETA-9035 / ETA-9035E, with the U.S. Department of Labor through the FLAG system. In it, the employer attests to the wage and the worksite and agrees to labor-condition obligations. DOL certification of the LCA is required before the I-129 can be filed.",
        links: [extLink(FLAG, "DOL FLAG system (where the LCA is filed)"), extLink(DOL_H1B, "DOL H-1B program page")],
        note: "The LCA is not your H-1B petition. It is a separate Department of Labor step that comes first; the certified LCA is then filed as part of the I-129. Processing usually takes about a week." },
      { id: "h1b-2", tag: "Employer &amp; counsel", title: "Employer files Form I-129",
        what: "If you are selected (or the role is cap-exempt), your employer files the Form I-129 petition with USCIS, including the Labor Condition Application and supporting documents. The petition asks for either change of status (if you are already in the U.S.) or consular notification (if you will get a visa abroad), and that choice drives the fork below.",
        links: [extLink(I129, "Form I-129 (USCIS)")],
        note: "The I-129 “action requested” box (change of status vs consular notification) is what sets your path in Phase 2." },
      { id: "h1b-3", tag: "Employer &amp; counsel", title: "Optional premium processing",
        what: "Your employer may pay for premium processing (Form I-907) to get a faster USCIS decision on the I-129. It is optional and employer-paid.",
        links: [extLink(I907, "Form I-907 (USCIS)")],
        note: "The fee and the guaranteed timeframe change, so confirm them on the USCIS page." },
      { id: "h1b-4", tag: "Employer &amp; counsel", title: "Receive the I-797 approval notice",
        what: "When USCIS approves the petition it issues Form I-797, the approval notice. This is your proof the petition is approved and a required document for the consular steps. Keep a copy.",
        links: [extLink(CASE_STATUS, "USCIS case status (track the receipt number)")],
        note: "For cap-subject change-of-status cases, the approval also sets the date you gain H-1B status, typically October 1." }
    ];

    var phase3 = [
      { id: "cs-1", tag: "You", title: "Complete Form DS-160 online",
        what: "Fill out the DS-160 (Online Nonimmigrant Visa Application) for visa class H-1B. Answer every question, upload a compliant photo, and save the confirmation page with the barcode, which you must bring to the interview.",
        links: [extLink(DS160, "DS-160 (ceac.state.gov/genniv)")],
        note: "A separate DS-160 is generally required for each applicant, including H-4 dependents. The confirmation barcode number is used to book the appointment." },
      { id: "cs-2", tag: "You", title: "Pay the visa application (MRV) fee",
        what: "Pay the machine-readable visa (MRV) application fee for a petition-based work visa. You usually pay through your country's official U.S. visa appointment website (see the next step), which issues a receipt used to schedule the interview.",
        linksHtml: "Pay through " + portalNote,
        note: "The fee amount changes and is country- and currency-specific, so confirm the current amount on the official page and do not rely on any figure quoted anywhere here. Some petition-based applicants may also owe a separate issuance or reciprocity fee after approval, depending on nationality." },
      { id: "cs-3", tag: "You", title: "Create an account and schedule the visa appointment",
        what: "On your country's official U.S. visa appointment system, create a profile, enter your DS-160 confirmation number and fee receipt, and book the visa interview at your chosen U.S. embassy or consulate.",
        linksHtml: "Book through " + portalNote + " You can also " + extLink(WAITTIME_URL, "check the global visa appointment wait times") + " to see how far out slots are.",
        note: "The scheduling portal is country-specific, so do not assume one global site." },
      { id: "cs-4", tag: "You", title: "Schedule biometrics / OFC appointment (if separate)",
        what: "Many posts require a separate biometrics appointment (fingerprints and photo) at an Offsite Facilitation Center (OFC or VAC) shortly before the interview. The scheduling system usually books both together.",
        linksHtml: "Handled through " + portalNote,
        note: "Whether the OFC step is separate, same-day, or waived varies by post and by interview-waiver eligibility." },
      { id: "cs-5", tag: "You", title: "Check the appointment wait time",
        what: "See how long the appointment and stamping wait is at your consulate and get a rough sense of when you would interview.",
        linksHtml: extLink(WAITTIME_URL, "Global visa wait times") + " (read the Petition-Based (H, L, O, P, Q) column for H-1B). For a rough date estimate, use the " + inLink("tools-interactive", "Visa Stamping Wait estimator on the Visa Timeline tab") + " rather than a separate calculator here.",
        note: "This is a rough projection, not a booking." },
      { id: "cs-6", tag: "You", title: "Prepare your documents",
        what: "Gather the documents for the interview: a valid passport, the DS-160 confirmation page, the visa fee receipt, the appointment confirmation, a compliant photo, the I-797 approval notice, and your employment and petition documents (offer or support letter, LCA, pay and role evidence, and often a copy of the I-129 packet from your employer).",
        links: [extLink(H1B_OVERVIEW, "USCIS H-1B overview (what the petition contains)")],
        note: "The exact document list varies by consulate, so check your post's website. Dependents (H-4) bring marriage and birth certificates and their own DS-160s." },
      { id: "cs-7", tag: "You", title: "Attend the interview (or check interview-waiver eligibility)",
        what: "Attend the in-person visa interview at the consulate. First check whether you qualify for an interview waiver (“dropbox”), which can let you skip the in-person interview and submit your passport by courier instead, often much faster.",
        links: [extLink(IW, "Interview waiver information (travel.state.gov)")],
        note: "Interview-waiver policy changes often, so confirm the current eligibility on the official page. As of 2025 it generally required a prior visa in the same classification, still valid or expired within the last 12 months, but do not assume that is still in force." },
      { id: "cs-8", tag: "Government (State Dept)", title: "Passport returned with the visa",
        what: "If approved, the consulate keeps your passport, prints the visa, and returns it (courier pickup or delivery). If your case goes into administrative processing (a 221g hold), issuance can take extra, unpredictable time.",
        links: [extLink(CEAC_STATUS, "CEAC visa status check")],
        note: "Administrative processing timelines are not predictable, and the wait-time estimator does not cover 221g delays." },
      { id: "cs-9", tag: "Government (CBP), then you", title: "Enter the U.S. and check your I-94",
        what: "Travel to a U.S. port of entry. A visa lets you request entry; CBP decides whether to admit you. After entry, retrieve your electronic I-94 and confirm it shows class H-1B and the correct “admit until” date. This record, not the visa stamp, governs how long you may stay.",
        links: [extLink(I94, "CBP I-94 (retrieve your I-94)")],
        note: "You can generally enter up to 10 days before the petition start date. If the I-94 is wrong, correct it promptly through CBP deferred inspection or your employer's counsel." }
    ];

    var phase4 = [
      { id: "post-1", tag: "Employer &amp; counsel, and you", title: "Keep status valid and plan extensions",
        what: "H-1B is granted in up to 3-year increments, with a 6-year maximum on the base status. AC21 allows extensions past 6 years once a green-card process is far enough along.",
        linksHtml: "See the H-1B timeline on the " + inLink("tools-interactive", "Visa Timeline tab") + ".",
        note: "This is where the H-1B story hands off to the green-card content the rest of the site covers." },
      { id: "post-2", tag: "You", title: "Track any pending USCIS cases",
        what: "Keep an eye on receipts and processing estimates for any petitions or applications still in progress.",
        links: [extLink(CASE_STATUS, "USCIS case status"), extLink(PROC_TIMES, "USCIS processing times")],
        note: "" }
    ];

    // Transfer / extension / amendment mini-workflows (shown per scenario).
    var transferSteps = [
      { id: "tr-1", tag: "Employer &amp; counsel", title: "New employer files a new LCA",
        what: "A change of employer is a fresh H-1B petition by the new employer. It starts with a new Labor Condition Application (ETA-9035) for the new role and worksite, filed with DOL through FLAG.",
        links: [extLink(FLAG, "DOL FLAG system")],
        note: "There is generally no lottery for a transfer if you already hold H-1B and were counted against the cap before." },
      { id: "tr-2", tag: "Employer &amp; counsel", title: "New employer files Form I-129 (transfer)",
        what: "The new employer files an I-129 petition to move your H-1B to them, with the certified LCA and supporting documents. Premium processing (I-907) is optional here too.",
        links: [extLink(I129, "Form I-129 (USCIS)")],
        note: "" },
      { id: "tr-3", tag: "You, with counsel", title: "H-1B portability: you may start work on receipt",
        what: "Under H-1B portability, you can generally begin working for the new employer once USCIS receives the transfer petition, before it is approved. Keep the I-797C receipt notice as proof.",
        links: [extLink(CASE_STATUS, "USCIS case status")],
        note: "Whether to start on receipt or wait for approval is a personal risk decision; confirm the specifics with the new employer's immigration counsel." },
      { id: "tr-4", tag: "Employer &amp; counsel", title: "Receipt, then the decision (I-797)",
        what: "Track the receipt and wait for the approval notice (I-797). Approval confirms your H-1B with the new employer.",
        links: [extLink(CASE_STATUS, "USCIS case status"), extLink(PROC_TIMES, "USCIS processing times")],
        note: "" },
      { id: "tr-5", tag: "You", title: "Travel considerations",
        what: "If you travel internationally after transferring, your existing visa stamp may still name the old employer. Check whether you need a new stamp before you re-enter.",
        links: [extLink(WAITTIME_URL, "Global visa wait times")],
        note: "The visa stamp and the petition are different things; confirm your situation before international travel." }
    ];
    var extensionSteps = [
      { id: "ex-1", tag: "Employer &amp; counsel", title: "As expiration approaches, file a new LCA",
        what: "Extensions are usually filed a few months before your current H-1B expires (employers often start around 6 months out). It begins with a new LCA (ETA-9035) covering the extension period.",
        links: [extLink(FLAG, "DOL FLAG system")],
        note: "" },
      { id: "ex-2", tag: "Employer &amp; counsel", title: "Employer files the I-129 extension",
        what: "The employer files an I-129 to extend your H-1B. If it is filed before your current status expires, you can generally keep working while it is pending, commonly for up to 240 days.",
        links: [extLink(I129, "Form I-129 (USCIS)")],
        note: "The 240-day rule applies to timely-filed extensions with the same employer; confirm your specific situation with counsel." },
      { id: "ex-3", tag: "Employer &amp; counsel", title: "Receipt, then the decision (I-797)",
        what: "Track the receipt and the approval notice. AC21 allows extensions past the 6-year maximum once your green-card process is far enough along.",
        links: [extLink(CASE_STATUS, "USCIS case status")],
        note: "" }
    ];
    var amendmentSteps = [
      { id: "am-1", tag: "You and counsel", title: "Identify whether the change is material",
        what: "Some job changes may be a material change to your H-1B, most commonly a move to a worksite outside your metropolitan area, or a significant change in your duties, hours, or terms of employment.",
        links: [],
        note: "A title-only change, or a move within the same metropolitan area, usually does not require an amendment, but this is fact-specific." },
      { id: "am-2", tag: "Employer &amp; counsel", title: "Confirm before the change takes effect",
        what: "This kind of change may require an amended petition or immigration review before it takes effect. Confirm with your employer's immigration counsel rather than assuming either way.",
        links: [extLink(I129, "Form I-129 (USCIS)")],
        note: "This checklist flags potential immigration impact; it does not decide whether a specific change needs an amendment. That is a legal judgment for counsel." }
    ];

    // Forms at a glance (mini-explainers).
    var formsList = [
      { code: "ETA-9035 / ETA-9035E", what: "The Labor Condition Application, where the employer attests to the wage and worksite.", who: "Employer (usually via counsel).", self: "No.", agency: "U.S. Department of Labor", link: extLink(FLAG, "DOL FLAG") },
      { code: "I-129", what: "The petition that requests H-1B classification for you.", who: "Employer / petitioner.", self: "Generally no.", agency: "USCIS", link: extLink(I129, "Form I-129") },
      { code: "I-907", what: "The optional request for premium (faster) processing of the petition.", who: "Employer or the requester.", self: "Usually the employer.", agency: "USCIS", link: extLink(I907, "Form I-907") },
      { code: "I-797", what: "The receipt and approval notice USCIS issues; not a form you file. Keep the original.", who: "Issued by USCIS.", self: "Not filed by you; you receive it.", agency: "USCIS", link: extLink(CASE_STATUS, "USCIS case status") },
      { code: "DS-160", what: "The online nonimmigrant visa application used for consular stamping.", who: "You (the applicant).", self: "Yes.", agency: "U.S. Department of State", link: extLink(DS160, "DS-160") },
      { code: "I-94", what: "Your arrival record and admit-until date, issued at entry and retrieved online.", who: "Issued by CBP; you retrieve and verify it.", self: "You retrieve it.", agency: "U.S. Customs and Border Protection", link: extLink(I94, "CBP I-94") }
    ];

    // "Something changed" prompts (informational, hedged; no asserted consequences).
    var changedList = [
      "Changed employers", "Got a promotion", "Job duties changed materially",
      "Moving, or a new worksite", "Started working remotely", "International travel coming up",
      "Renewed your passport", "Got married", "Received an RFE (Request for Evidence)",
      "Your I-140 was approved", "Your employment ended"
    ];

    // Scenario selector options.
    var SCENARIOS = [
      { v: "firsttime", label: "First-time H-1B (cap / lottery)" },
      { v: "capexempt", label: "Cap-exempt H-1B" },
      { v: "transfer",  label: "Change of employer (transfer)" },
      { v: "extension", label: "Extension" },
      { v: "amendment", label: "Amendment / job change" },
      { v: "stamping",  label: "Consular stamping only" },
      { v: "onh1b",     label: "Already on H-1B" },
      { v: "notsure",   label: "Not sure / show everything" }
    ];
    var SCEN_VALUES = SCENARIOS.map(function (o) { return o.v; });

    var transferIds = transferSteps.map(function (s) { return s.id; });
    var extensionIds = extensionSteps.map(function (s) { return s.id; });
    var amendmentIds = amendmentSteps.map(function (s) { return s.id; });

    var phase1Ids = phase1.map(function (s) { return s.id; });
    var phase3Ids = phase3.map(function (s) { return s.id; });
    var phase4Ids = phase4.map(function (s) { return s.id; });

    function load() {
      try {
        var o = JSON.parse(localStorage.getItem(KEY) || "null");
        if (o && typeof o === "object") {
          return {
            scenario: SCEN_VALUES.indexOf(o.scenario) !== -1 ? o.scenario : null,
            fork: (o.fork === "cos" || o.fork === "consular") ? o.fork : null,
            done: Array.isArray(o.done) ? o.done.filter(function (x) { return typeof x === "string"; }) : []
          };
        }
      } catch (e) {}
      return { scenario: null, fork: null, done: [] };
    }
    function save(st) {
      try { localStorage.setItem(KEY, JSON.stringify({ scenario: st.scenario, fork: st.fork, done: st.done })); } catch (e) {}
    }

    var state = load();

    function isDone(id) { return state.done.indexOf(id) !== -1; }

    // Which sections/steps apply, given the chosen scenario. Default (no
    // scenario picked) shows the whole journey so the tool is useful immediately.
    function scenarioView() {
      var s = state.scenario;
      var showAll = (!s || s === "notsure" || s === "firsttime");
      return {
        s: s,
        workflow: (s === "transfer") ? "transfer" : (s === "extension") ? "extension" : (s === "amendment") ? "amendment" : null,
        showReg: showAll,                                  // registration/lottery step
        showPhase1Petition: showAll || s === "capexempt",  // LCA, I-129, premium, I-797
        showFork: showAll || s === "capexempt",
        showPhase3: showAll || s === "capexempt" || s === "stamping",
        forceConsular: (s === "stamping")                  // stamping-only: consular by definition
      };
    }

    // Denominator is honest: only the steps actually shown for the chosen
    // scenario count, and the fork unit counts only when the fork is shown.
    function activeStepIds() {
      var v = scenarioView();
      var ids = [];
      if (v.workflow === "transfer") ids = ids.concat(transferIds);
      else if (v.workflow === "extension") ids = ids.concat(extensionIds);
      else if (v.workflow === "amendment") ids = ids.concat(amendmentIds);
      else {
        phase1.forEach(function (st) {
          if (st.id === "h1b-1") { if (v.showReg) ids.push(st.id); }
          else if (v.showPhase1Petition) ids.push(st.id);
        });
        if (v.showPhase3 && (v.forceConsular || state.fork === "consular")) ids = ids.concat(phase3Ids);
      }
      ids = ids.concat(phase4Ids);
      return ids;
    }
    function counts() {
      var v = scenarioView();
      var ids = activeStepIds();
      var done = 0;
      ids.forEach(function (id) { if (isDone(id)) done++; });
      var total = ids.length;
      if (v.showFork) { total += 1; if (state.fork) done++; }   // fork is a counted unit only when it applies
      return { done: done, total: total };
    }

    function stepHtml(s) {
      var cbId = "h1b-cb-" + s.id;
      var h = '<li class="h1b-step' + (isDone(s.id) ? " is-done" : "") + '" data-step-id="' + esc(s.id) + '">';
      h += '<input type="checkbox" class="h1b-cb" id="' + cbId + '" data-step-id="' + esc(s.id) + '"' + (isDone(s.id) ? " checked" : "") + '>';
      h += '<div class="h1b-step-body">';
      h += '<label class="h1b-step-title" for="' + cbId + '">' + s.title;
      if (s.tag) h += ' <span class="h1b-tag">' + s.tag + '</span>';
      h += '</label>';
      h += '<p class="h1b-step-what">' + s.what + '</p>';
      var linksHtml = s.linksHtml || (s.links && s.links.length ? s.links.join(" &middot; ") : "");
      if (linksHtml) h += '<p class="h1b-step-links"><span class="h1b-step-lbl">Official pages:</span> ' + linksHtml + '</p>';
      if (s.note) h += '<p class="h1b-step-note">' + s.note + '</p>';
      h += '</div></li>';
      return h;
    }

    function stepsListHtml(steps) {
      return '<ol class="h1b-steps">' + steps.map(stepHtml).join("") + '</ol>';
    }

    // The I-94 is the record that actually governs how long you may stay.
    function i94CalloutHtml() {
      return '<div class="h1b-callout"><p class="h1b-callout-title">Check your I-94 after every U.S. entry.</p>' +
        '<p>Three dates are easy to confuse, and they are not the same:</p>' +
        '<ul class="h1b-callout-list">' +
        '<li>Your <strong>visa stamp</strong> expiration (in your passport) is mainly about when you may seek entry.</li>' +
        '<li>Your <strong>I-797</strong> validity is the petition\'s approved period.</li>' +
        '<li>Your <strong>I-94</strong> admit-until date is what actually governs how long you may stay.</li>' +
        '</ul>' +
        '<p>After each entry, retrieve your I-94 and confirm it shows class H-1B and the correct admit-until date. ' + extLink(I94, "Retrieve your I-94 (CBP)") + '</p></div>';
    }
    function formsSectionHtml() {
      var h = '<section class="h1b-phase h1b-forms"><h3 class="h1b-phase-title">Forms at a glance</h3>';
      h += '<p class="h1b-phase-lead">Quick reference for the forms in the H-1B journey. Expand any one for what it is and who files it.</p>';
      formsList.forEach(function (f) {
        h += '<details class="collapsible"><summary>Form ' + f.code + '</summary><div class="body">';
        h += '<p><strong>What is it?</strong> ' + f.what + '</p>';
        h += '<p><strong>Who files it?</strong> ' + f.who + '</p>';
        h += '<p><strong>Do I file it myself?</strong> ' + f.self + '</p>';
        h += '<p><strong>Agency:</strong> ' + f.agency + '</p>';
        h += '<p><strong>Official page:</strong> ' + f.link + '</p>';
        h += '</div></details>';
      });
      h += '</section>';
      return h;
    }
    function feesSectionHtml() {
      var gd = window.GCN_DATA || {};
      var data = gd.h1bFees;
      if (!data || !data.length) return "";
      var v = gd.h1bFeesVerified || {};
      var h = '<section class="h1b-phase h1b-fees"><h3 class="h1b-phase-title">Fees at a glance</h3>';
      h += '<p class="h1b-phase-lead">Government fees for the H-1B journey. Employer-side petition fees are paid by your employer; the consular visa fee is paid by you. Amounts reflect ' + esc(v.date || "the latest") + ' figures and several vary by employer size, so treat them as a guide and confirm each on the official page before you rely on it.</p>';
      h += '<div class="table-scroll"><table class="paths-table h1b-fee-table"><thead><tr>' +
        '<th scope="col">Fee</th><th scope="col">Amount</th><th scope="col">Who pays</th><th scope="col">When it applies</th><th scope="col">Official source</th>' +
        '</tr></thead><tbody>';
      data.forEach(function (f) {
        h += '<tr>' +
          '<td>' + esc(f.label) + '</td>' +
          '<td class="h1b-fee-amt">' + esc(f.amount) + '</td>' +
          '<td>' + esc(f.who) + '</td>' +
          '<td>' + esc(f.when) + '</td>' +
          '<td>' + extLink(f.url, f.urlText || "Official page") + '</td>' +
          '</tr>';
      });
      h += '</tbody></table></div>';
      if (gd.h1bFeesNote) { h += '<p class="h1b-fee-note">' + esc(gd.h1bFeesNote) + '</p>'; }
      h += '<p class="h1b-fee-stamp">Amounts reflect ' + esc(v.sourceName || "the official fee schedule") + ', last checked ' + esc(v.date || "") + '. Fees change; confirm the current amount on the ' + extLink(v.sourceUrl || "https://www.uscis.gov/g-1055", "official USCIS fee schedule") + ' before filing.</p>';
      h += '</section>';
      return h;
    }
    function changedSectionHtml() {
      var h = '<section class="h1b-phase h1b-changed"><h3 class="h1b-phase-title">Something changed?</h3>';
      h += '<p class="h1b-phase-lead">If any of these happen while you are on H-1B, they may affect your status or petition. This is a prompt to check, not a verdict; talk to your employer\'s immigration counsel about your situation.</p>';
      h += '<ul class="h1b-changed-list">';
      changedList.forEach(function (c) { h += '<li>' + esc(c) + '</li>'; });
      h += '</ul></section>';
      return h;
    }
    function forkFieldsetHtml() {
      var h = '<fieldset class="h1b-fork">';
      h += '<legend class="h1b-fork-legend">After the I-797 approval, you are on one of two paths. This is the most important choice in the checklist.</legend>';
      h += '<div class="h1b-fork-options">';
      h += '<label class="h1b-fork-opt' + (state.fork === "cos" ? " selected" : "") + '">';
      h += '<span class="h1b-fork-opt-head"><input type="radio" name="h1b-fork" value="cos"' + (state.fork === "cos" ? " checked" : "") + '> <span class="h1b-fork-opt-title">Change of Status (already in the U.S.)</span></span>';
      h += '<span class="h1b-fork-opt-desc">If you were already in the U.S. in another status (for example F-1/OPT, L-2, or H-4) and the employer filed the I-129 as a change of status, you gain H-1B status on the effective date of the approval, typically October 1 for cap-subject petitions. No DS-160, visa fee, consular appointment, or interview is required to start working. You would only need a visa stamp later if you travel internationally and need to re-enter.</span>';
      h += '</label>';
      h += '<label class="h1b-fork-opt' + (state.fork === "consular" ? " selected" : "") + '">';
      h += '<span class="h1b-fork-opt-head"><input type="radio" name="h1b-fork" value="consular"' + (state.fork === "consular" ? " checked" : "") + '> <span class="h1b-fork-opt-title">Consular Processing / Visa Stamping</span></span>';
      h += '<span class="h1b-fork-opt-desc">You are outside the U.S., or you choose to get the stamp. You need an actual visa stamp in your passport to enter the U.S. in H-1B, which means the full consular sequence below: DS-160, pay the visa fee, schedule the appointment (plus any biometrics), interview or interview waiver, passport returned with the visa, then enter the U.S.</span>';
      h += '</label>';
      h += '</div>';
      h += '<p class="h1b-fork-plain">In plain terms: change of status keeps you in the U.S. the whole time, while consular processing means the visa is issued abroad.</p>';
      h += '</fieldset>';
      return h;
    }
    function scenarioSelectorHtml() {
      var h = '<div class="h1b-scenario"><label class="h1b-scenario-label" for="h1b-scenario-sel">What are you doing?</label> ';
      h += '<select id="h1b-scenario-sel" class="h1b-scenario-sel"><option value=""' + (!state.scenario ? " selected" : "") + '>Show the whole H-1B journey</option>';
      SCENARIOS.forEach(function (o) {
        h += '<option value="' + o.v + '"' + (state.scenario === o.v ? " selected" : "") + '>' + esc(o.label) + '</option>';
      });
      h += '</select>';
      h += '<p class="h1b-scenario-hint">Pick your situation and the checklist hides the steps that do not apply. Your choice is saved on this device only.</p>';
      h += '</div>';
      return h;
    }

    function build() {
      var v = scenarioView();
      var c = counts();
      var pct = c.total ? Math.round((c.done / c.total) * 100) : 0;
      var h = '<div class="h1b-tool">';

      // Progress
      h += '<div class="h1b-progress" role="status" aria-live="polite">';
      h += '<div class="h1b-progress-head"><span class="h1b-progress-count">' + c.done + ' of ' + c.total + ' steps done</span>';
      h += '<span class="h1b-progress-pct">' + pct + '%</span></div>';
      h += '<div class="h1b-progress-track"><div class="h1b-progress-bar" style="width:' + pct + '%;"></div></div>';
      h += '</div>';

      // Scenario selector + "who handles this" legend
      h += scenarioSelectorHtml();
      h += '<p class="h1b-legend">Each step is tagged with <span class="h1b-tag">who handles it</span>: Employer, Counsel, You, or a Government agency.</p>';

      if (v.workflow) {
        var wfSteps = v.workflow === "transfer" ? transferSteps : (v.workflow === "extension" ? extensionSteps : amendmentSteps);
        var wfTitle = v.workflow === "transfer" ? "Change of employer (H-1B transfer)" : (v.workflow === "extension" ? "H-1B extension" : "H-1B amendment / job change");
        var wfLead = v.workflow === "transfer"
          ? "Moving your H-1B to a new employer is a fresh petition, but there is no lottery. Portability may let you start work once USCIS receives the petition."
          : (v.workflow === "extension"
            ? "Extensions run in up to 3-year increments (6-year base maximum, longer via AC21). Employers usually file early."
            : "Whether a change needs an amended petition is fact-specific. This flags what to check with counsel, not a conclusion. The same change can also affect the green-card side (PERM, I-140, priority date). Check that with the " + inLink("tools-jobchange", "Job or Location Change Checker") + " on this page.");
        h += '<section class="h1b-phase"><h3 class="h1b-phase-title">' + wfTitle + '</h3>';
        h += '<p class="h1b-phase-lead">' + wfLead + '</p>';
        h += stepsListHtml(wfSteps);
        h += '</section>';
        h += i94CalloutHtml();
        h += '<section class="h1b-phase"><h3 class="h1b-phase-title">Ongoing: staying in H-1B status</h3>';
        h += '<p class="h1b-phase-lead">These apply no matter how you got here.</p>';
        h += stepsListHtml(phase4);
        h += '</section>';
        h += changedSectionHtml();
        h += formsSectionHtml();
      } else {
        // Phase 1 (filtered by scenario)
        var p1 = phase1.filter(function (st) { return st.id === "h1b-1" ? v.showReg : v.showPhase1Petition; });
        if (p1.length) {
          h += '<section class="h1b-phase"><h3 class="h1b-phase-title">Phase 1: Employer and petition side</h3>';
          h += '<p class="h1b-phase-lead">These steps are driven by your employer and their immigration counsel. They are here so you can see the whole journey and know what to expect; you usually do not act on these yourself.</p>';
          h += stepsListHtml(p1);
          h += '</section>';
        }

        // Phase 2 fork
        if (v.showFork) {
          h += '<section class="h1b-phase">';
          h += '<h3 class="h1b-phase-title">Phase 2: Choose your path</h3>';
          h += forkFieldsetHtml();
          h += '</section>';
        }

        // Phase 3 consular
        if (v.showPhase3) {
          h += '<section class="h1b-phase">';
          h += '<h3 class="h1b-phase-title">Phase 3: Consular stamping</h3>';
          if (v.forceConsular) {
            h += '<p class="h1b-phase-lead">You already have an approved petition and just need the visa stamped. These are your checkable steps.</p>';
            h += stepsListHtml(phase3);
          } else if (state.fork === "consular") {
            h += '<p class="h1b-phase-lead">These are your detailed, checkable steps to get the visa stamped and enter the U.S.</p>';
            h += stepsListHtml(phase3);
          } else if (state.fork === "cos") {
            h += '<div class="h1b-note-block">Not needed now. You already have H-1B status as of the approval\'s effective date. You would only do the stamping steps when you travel internationally and need a visa to re-enter, so they are not counted in your progress here.</div>';
            h += '<details class="h1b-future"><summary>Show the stamping steps anyway (for future travel)</summary>';
            h += stepsListHtml(phase3);
            h += '</details>';
          } else {
            h += '<div class="h1b-note-block h1b-muted">Pick your path above to see your next steps.</div>';
          }
          h += '</section>';
        }

        h += i94CalloutHtml();

        // Phase 4
        h += '<section class="h1b-phase">';
        h += '<h3 class="h1b-phase-title">Phase 4: After you are in H-1B status</h3>';
        h += '<p class="h1b-phase-lead">Both paths converge here.</p>';
        h += stepsListHtml(phase4);
        h += '</section>';

        h += changedSectionHtml();
        h += formsSectionHtml();
      }

      // Fees at a glance — verified-dated table from window.GCN_DATA.h1bFees.
      // Always shown (fees are relevant to every scenario), degrades to nothing
      // if immigration-data.js is not loaded on the page.
      h += feesSectionHtml();

      // Footer: clear + privacy note + disclaimer
      h += '<div class="h1b-footer">';
      h += '<button type="button" class="h1b-clear" id="h1b-clear">Clear my saved progress</button>';
      h += '<p class="h1b-privacy">Saved only in this browser, never sent anywhere. Only which boxes you have ticked and which path you picked, never any personal detail.</p>';
      h += '</div>';
      h += '<p class="paste-disclaimer">This is a plain-English educational checklist, not legal advice and not a substitute for your employer\'s immigration counsel. Fees, timeframes, eligibility rules, and page locations change often; confirm every detail on the official government page before you rely on it. Verify with official sources and a licensed immigration attorney.</p>';

      h += '</div>';
      return h;
    }

    function updateProgress() {
      var c = counts();
      var pct = c.total ? Math.round((c.done / c.total) * 100) : 0;
      var cnt = host.querySelector(".h1b-progress-count");
      var pctEl = host.querySelector(".h1b-progress-pct");
      var bar = host.querySelector(".h1b-progress-bar");
      if (cnt) cnt.textContent = c.done + " of " + c.total + " steps done";
      if (pctEl) pctEl.textContent = pct + "%";
      if (bar) bar.style.width = pct + "%";
    }

    function wire() {
      // Checkbox toggles: update in place (no full re-render) so focus/scroll hold.
      [].slice.call(host.querySelectorAll(".h1b-cb")).forEach(function (cb) {
        cb.addEventListener("change", function () {
          var id = cb.getAttribute("data-step-id");
          var i = state.done.indexOf(id);
          if (cb.checked && i === -1) state.done.push(id);
          else if (!cb.checked && i !== -1) state.done.splice(i, 1);
          var row = cb.closest ? cb.closest(".h1b-step") : null;
          if (row) row.classList.toggle("is-done", cb.checked);
          save(state);
          updateProgress();
        });
      });
      // Scenario choice: changes which sections show, so re-render.
      var scenSel = host.querySelector("#h1b-scenario-sel");
      if (scenSel) scenSel.addEventListener("change", function () {
        var val = scenSel.value;
        state.scenario = (SCEN_VALUES.indexOf(val) !== -1) ? val : null;
        save(state);
        draw();
      });
      // Fork choice: gating changes, so re-render.
      [].slice.call(host.querySelectorAll('input[name="h1b-fork"]')).forEach(function (r) {
        r.addEventListener("change", function () {
          if (r.checked) { state.fork = r.value; save(state); draw(); }
        });
      });
      var clearBtn = host.querySelector("#h1b-clear");
      if (clearBtn) clearBtn.addEventListener("click", function () {
        if (!window.confirm("Clear your saved H-1B checklist progress and choices on this device? This cannot be undone.")) return;
        try { localStorage.removeItem(KEY); } catch (e) {}
        state = { scenario: null, fork: null, done: [] };
        draw();
      });
    }

    function draw() {
      host.innerHTML = build();
      wire();
    }

    draw();
  }

  // ---- Standalone Live-tools parsers (tools.html only) ----
  // Reuses the exact same card builders + wiring as the questionnaire result,
  // driven by an on-page category+country picker instead of questionnaire state.
  // No-ops entirely on pages without the #tools-standalone marker.
  function initStandaloneTools() {
    var picker = document.getElementById("tools-standalone");
    var cards = document.getElementById("tools-cards");
    if (!picker || !cards) return;
    standaloneToolsMode = true;

    var catSel = document.getElementById("ts-category");
    var countrySel = document.getElementById("ts-country");

    function optionHas(sel, val) {
      return sel && Array.prototype.some.call(sel.querySelectorAll("option"), function (o) { return o.value === val; });
    }
    // Restore a shared scenario from the URL hash — category & country ONLY
    // (never a priority date). The hash is never sent to any server.
    (function restoreFromHash() {
      var h = (location.hash || "").replace(/^#/, "");
      if (!h) return;
      var p = {};
      h.split("&").forEach(function (kv) { var a = kv.split("="); if (a[0]) p[decodeURIComponent(a[0])] = decodeURIComponent(a[1] || ""); });
      if (p.cat && VISA_TYPES[p.cat] && optionHas(catSel, p.cat)) catSel.value = p.cat;
      if (p.country && optionHas(countrySel, p.country)) countrySel.value = p.country;
    })();

    function scenarioHash() {
      return "#cat=" + encodeURIComponent(catSel ? catSel.value : "") +
             "&country=" + encodeURIComponent(countrySel ? countrySel.value : "");
    }
    function updateHash() {
      var h = scenarioHash();
      if (history.replaceState) { try { history.replaceState(null, "", h); } catch (e) { location.hash = h; } }
      else location.hash = h;
    }

    function renderCards() {
      // Point shared state at the picker's choices; the questionnaire isn't
      // used on this page, so mutating these is harmless here.
      state.category = (catSel && catSel.value) || "EB-2";
      state.country = (countrySel && countrySel.value) || "India";
      // Switching category/country invalidates any prior parse — clear it.
      state.bulletinOverride = null;
      var vt = visaType(state.category);
      // Context card first (frames the readers, or IS the timeline for work visas).
      var h = visaContextBlock(state.category, state.country);
      if (vt.kind === "niv") {
        // Work visas: only the consular stamping estimator applies. No Visa
        // Bulletin (they're not in it) and no immigrant-visa interview card.
        h += consularPasteBlock(state.category);
      } else {
        // Green-card categories: bulletin reader + both wait estimators.
        h += bulletinPasteBlock(state.category, state.country);
        h += consularPasteBlock(state.category);
        h += ivSchedulePasteBlock();
      }
      cards.innerHTML = h;
      wirePasteIns();
    }

    if (catSel) catSel.addEventListener("change", function () { updateHash(); renderCards(); });
    if (countrySel) countrySel.addEventListener("change", function () { updateHash(); renderCards(); });

    // "Copy link to this view" — a shareable URL that reopens this exact
    // category + country. No personal data is ever encoded in it.
    var share = document.createElement("div");
    share.className = "ts-share";
    share.innerHTML = '<button type="button" id="ts-share-btn" class="ts-share-btn">Copy link to this view</button>' +
      '<span class="ts-share-note" id="ts-share-note" role="status" aria-live="polite"></span>';
    picker.parentNode.insertBefore(share, cards);
    var shareBtn = document.getElementById("ts-share-btn");
    if (shareBtn) shareBtn.addEventListener("click", function () {
      var url = location.origin + location.pathname + scenarioHash();
      var note = document.getElementById("ts-share-note");
      function shown(msg) { if (note) note.textContent = msg; }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(
          function () { shown("Copied. The link holds only the category and country, nothing about you."); },
          function () { shown(url); }
        );
      } else { shown(url); }
    });

    updateHash();
    renderCards();
  }

  // Standalone queue projector + scenario compare for the Live Tools page.
  // Asks for category / country / priority date directly (no questionnaire) and
  // renders the same draggable projector and A/B compare used in Check My Status.
  // No-ops on pages without the #projector-standalone marker.
  function initStandaloneProjector() {
    var wrap = document.getElementById("projector-standalone");
    var out = document.getElementById("projector-standalone-out");
    if (!wrap || !out) return;
    var catSel = document.getElementById("pj-category");
    var countrySel = document.getElementById("pj-country");
    var pdInput = document.getElementById("pj-pd");
    function render() {
      var cat = catSel ? catSel.value : "EB-2";
      var country = countrySel ? countrySel.value : "India";
      var pd = pdInput ? pdInput.value : "";
      if (!pd) {
        // Surface the methodology up front so it is discoverable without first
        // entering a priority date; the populated result also includes it, and
        // the two states are mutually exclusive so it never doubles up.
        out.innerHTML = '<p class="help">Enter your priority date above to see your queue position, a projected timeline, and a side-by-side scenario comparison. Nothing you type is saved.</p>' + qpMethodologyHtml();
        return;
      }
      var cd = effectiveCountryData(cat, country);
      if (!cd) {
        out.innerHTML = '<div class="tl-note">The built-in bulletin snapshot has no cutoff for ' + esc(cat) + ' ' + esc(countryLabel(country)) + '. It covers EB-1, EB-2, and EB-3 (and EB-1 has no Rest-of-World cell). Pick a covered pairing to project.</div>';
        return;
      }
      var tl = queueTimelineBlock(pd, cd, cat, country);
      if (!tl) {
        out.innerHTML = '<div class="qp-current">For ' + esc(cat) + ' ' + esc(countryLabel(country)) + ', the cutoff is current (or your priority date is already past it), so there is no Visa Bulletin wait. Once your I-140 is approved you can file I-485; the green card is then mostly processing time, on the order of a year.</div>';
        return;
      }
      out.innerHTML = tl + compareScenarioBlock(pd, cat, country);
      wireQueueProjector();
      wireCompare();
    }
    if (catSel) catSel.addEventListener("change", function () {
      // Country coverage is per-category (EB-1 has no Rest-of-World cell); rebuild.
      var valid = cmpCountriesFor(catSel.value);
      var keep = (countrySel && valid.indexOf(countrySel.value) !== -1) ? countrySel.value : valid[0];
      if (countrySel) countrySel.innerHTML = cmpCountryOptions(catSel.value, keep);
      render();
    });
    if (countrySel) countrySel.addEventListener("change", render);
    if (pdInput) { pdInput.addEventListener("change", render); pdInput.addEventListener("input", render); }
    render();
  }

  // ---- Job / Location Change Checker (Live Tools page) ----------------------
  // A focused, standalone read of the same IMPACT_ROWS x IMPACT_COLS matrix used
  // in Check My Status: pick ONE change and ONE stage and see that one cell's
  // risk band + grounded explanation + questions for counsel, instead of the
  // whole grid. Reuses the shared matrix so it can never drift. It never returns
  // a legal verdict. No-ops on pages without the #jobchange-checker marker.
  function jcBand(cls) {
    if (cls === "safe") return "Lower likelihood of impact";
    if (cls === "danger") return "Higher impact: discuss with counsel before proceeding";
    return "Likely needs a filing: review with counsel";
  }
  function jcQuestionsHtml(row, ci) {
    var s = (row.scenario || "").toLowerCase();
    var qs = [
      "Does this change require a brand-new PERM, or can my current PERM or petition be amended instead?",
      "Is my priority date preserved through this change, and if so, how (for example AC21 §104(c) porting once a new I-140 is approved)?",
      "Do I need an I-129 amendment, and if so, must it be filed before I make the move?",
      "How would this change affect my overall green card timeline?"
    ];
    if (/location|msa|state/.test(s)) {
      qs.push("Is my new worksite in the same MSA (area of intended employment) as my certified PERM, or a different one?");
      qs.push("Does Matter of Simeio require an amended petition with a new LCA filed before I move to the new worksite?");
    }
    if (/role|promotion|family|manager|level/.test(s)) {
      qs.push("Is my new role the “same or similar” SOC code, which matters for AC21 portability?");
    }
    if (/entity|employer/.test(s)) {
      qs.push("Is the new entity a different legal employer that needs its own PERM, I-140, and H-1B petition?");
    }
    if (ci === 4) {
      qs.push("Has my I-485 been pending 180 days or more, so AC21 portability (Supplement J / Form I-485J) may cover this move?");
    }
    var h = '<div class="jc-questions"><h3>Questions to ask your immigration attorney</h3><ul>';
    qs.forEach(function (q) { h += '<li>' + esc(q) + '</li>'; });
    h += '</ul></div>';
    return h;
  }
  function renderJobChangeChecker() {
    var host = document.getElementById("jobchange-checker");
    if (!host || typeof IMPACT_ROWS === "undefined") return;
    var changeOpts = "", stageOpts = "";
    // row.scenario / col.title are trusted authored strings (may contain entities
    // like &rarr;); no user input is ever interpolated here.
    IMPACT_ROWS.forEach(function (r, i) { changeOpts += '<option value="' + i + '">' + r.scenario + (r.note ? ' ' + r.note : '') + '</option>'; });
    IMPACT_COLS.forEach(function (c, i) { stageOpts += '<option value="' + i + '">' + esc(c.title) + (c.sub ? ' ' + esc(c.sub) : '') + '</option>'; });
    var h = '<div class="jobchange-tool">';
    h += '<div class="jobchange-picker" role="group" aria-label="What is changing and where you are in the process">';
    h += '<div class="jc-field"><label for="jc-change">What are you changing?</label>';
    h += '<select id="jc-change"><option value="">Select a change…</option>' + changeOpts + '</select></div>';
    h += '<div class="jc-field"><label for="jc-stage">Where are you in the green card process?</label>';
    h += '<select id="jc-stage"><option value="">Select your stage…</option>' + stageOpts + '</select></div>';
    h += '</div>';
    h += '<div id="jobchange-out" class="jobchange-out" aria-live="polite"></div>';
    h += '</div>';
    host.innerHTML = h;
    var changeSel = document.getElementById("jc-change");
    var stageSel = document.getElementById("jc-stage");
    var out = document.getElementById("jobchange-out");
    function render() {
      var ri = changeSel.value, ci = stageSel.value;
      if (ri === "" || ci === "") {
        out.innerHTML = '<p class="help">Pick both a change and your stage to see the likely impact and the questions to raise with your immigration attorney. Nothing you pick is saved.</p>';
        return;
      }
      var row = IMPACT_ROWS[+ri], col = IMPACT_COLS[+ci], cell = row.cells[+ci];
      var oh = '<div class="jc-result jc-' + cell.cls + '">';
      oh += '<div class="jc-band">' + esc(jcBand(cell.cls)) + '</div>';
      oh += '<p class="jc-context"><strong>' + row.scenario + '</strong> &middot; ' + esc(col.title) + ' ' + esc(col.sub || "") + '</p>';
      oh += '<p class="jc-action"><strong>' + esc(cell.label) + '</strong></p>';
      oh += '<div class="jc-body">' + cell.body + '</div>';
      oh += jcQuestionsHtml(row, +ci);
      oh += '<p class="jc-disclaimer">This is a prompt to check, not a determination that a move is safe or unsafe. Whether it actually triggers a new filing or affects your priority date is a fact-specific legal judgment. Confirm with a licensed immigration attorney before you act. Not legal advice.</p>';
      oh += '</div>';
      out.innerHTML = oh;
    }
    changeSel.addEventListener("change", render);
    stageSel.addEventListener("change", render);
    render();
  }

  // Smooth-scroll the "jump to a tool" index cards to their section.
  function wireToolIndex() {
    var links = document.querySelectorAll(".tool-index a[href^='#']");
    Array.prototype.forEach.call(links, function (a) {
      a.addEventListener("click", function (e) {
        var id = (a.getAttribute("href") || "").slice(1);
        var t = id && document.getElementById(id);
        if (!t) return;
        e.preventDefault();
        t.scrollIntoView({ behavior: "smooth", block: "start" });
        if (window.history && window.history.replaceState) { try { window.history.replaceState(null, "", "#" + id); } catch (err) {} }
      });
    });
  }

  /* ==================== HISTORY & TRENDS (tools.html) ====================
     Renders three hand-rolled SVG views from vb_history.json (Oct 2015 -> Aug
     2026): a cutoff-over-time line chart (FAD solid, DFF dashed), a
     movement-velocity bar chart (month-over-month FAD change in days), and an
     optional "your priority date vs the cutoff" overlay on the line chart.
     Everything is historical/descriptive, not a prediction. No-ops when its
     root element is absent (every other page). */

  var HIST_MS_PER_DAY = 86400000;
  var HIST_MS_PER_YEAR = 365.25 * HIST_MS_PER_DAY;
  var HIST_CACHE = null;          // parsed vb_history.json (fetched once)
  var HIST_FETCH_STATE = "idle";  // idle | loading | ready | failed
  var HIST_EB_CATS = ["EB-1", "EB-2", "EB-3", "EB-4", "EB-5"]; // heatmap rows

  // Classify a single vb_history value into a chartable kind.
  // ISO date -> {t:'iso', ms}; "CURRENT" -> {t:'current'}; "U" or null -> {t:'gap'}.
  function histVal(v) {
    if (v == null) return { t: "gap", reason: "none" };
    if (v === "CURRENT") return { t: "current" };
    if (v === "U") return { t: "gap", reason: "unavailable" };
    var ms = parseIsoToMs(v);
    if (ms == null) return { t: "gap", reason: "none" };
    return { t: "iso", ms: ms };
  }

  function histParseMonth(m) {
    var p = String(m || "").split("-");
    return { y: parseInt(p[0], 10), m: parseInt(p[1], 10) };
  }

  // Short "Mon 'YY"-ish year label for the cutoff (y) axis.
  function histYearLabel(ms) {
    var d = new Date(ms);
    return String(d.getUTCFullYear());
  }

  // Build the cutoff-over-time line chart (+ optional priority-date overlay).
  function histLineChart(series, cat, country, pdStr) {
    var W = 760, H = 400, padL = 60, padR = 16, padT = 18, padB = 46;
    var n = series.length;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var curBand = 28;                 // reserved top strip for "CURRENT" markers
    var dataTop = padT + curBand, dataH = plotH - curBand;

    // Collect every plottable cutoff (ms) to size the y-domain.
    var msVals = [], i, f, kind, series2;
    for (i = 0; i < n; i++) {
      kind = histVal(series[i].fad); if (kind.t === "iso") msVals.push(kind.ms);
      kind = histVal(series[i].dff); if (kind.t === "iso") msVals.push(kind.ms);
    }
    var pdMs = pdStr ? parseIsoToMs(pdStr) : null;
    if (pdMs != null) msVals.push(pdMs);

    if (!msVals.length) {
      return '<div class="tl-note">The historical bulletin data for ' + esc(cat) + " " +
        esc(countryLabel(country)) + ' has no dated cutoffs to chart (every month is Current or Unavailable).</div>';
    }

    var yMin = Math.min.apply(null, msVals), yMax = Math.max.apply(null, msVals);
    if (yMin === yMax) { yMin -= HIST_MS_PER_YEAR; yMax += HIST_MS_PER_YEAR; }
    var padY = (yMax - yMin) * 0.05; yMin -= padY; yMax += padY;

    function X(idx) { return padL + (n === 1 ? plotW / 2 : (idx / (n - 1)) * plotW); }
    function Y(ms) { return dataTop + dataH - ((ms - yMin) / (yMax - yMin)) * dataH; }
    var curY = padT + curBand / 2;

    var svg = [];
    svg.push('<svg class="hist-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Cutoff date over time for ' + esc(cat) + " " + esc(countryLabel(country)) + '">');

    // --- y gridlines + year labels (one per calendar year in the domain) ---
    var y0 = new Date(yMin).getUTCFullYear(), y1 = new Date(yMax).getUTCFullYear();
    var yStep = Math.max(1, Math.ceil((y1 - y0 + 1) / 7));
    for (var yr = y0; yr <= y1; yr += yStep) {
      var yms = Date.UTC(yr, 0, 1);
      if (yms < yMin || yms > yMax) continue;
      var gy = Y(yms).toFixed(1);
      svg.push('<line class="hist-grid" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>');
      svg.push('<text class="hist-axlabel" x="' + (padL - 8) + '" y="' + gy + '" text-anchor="end" dominant-baseline="middle">' + yr + "</text>");
    }
    // "CURRENT" band divider + label
    svg.push('<line class="hist-grid hist-grid-cur" x1="' + padL + '" y1="' + dataTop + '" x2="' + (W - padR) + '" y2="' + dataTop + '"/>');
    svg.push('<text class="hist-axlabel hist-curlabel" x="' + (padL - 8) + '" y="' + curY + '" text-anchor="end" dominant-baseline="middle">Current</text>');

    // --- x axis baseline + year ticks (January of each year, plus ends) ---
    var axisY = padT + plotH;
    svg.push('<line class="hist-axis" x1="' + padL + '" y1="' + axisY + '" x2="' + (W - padR) + '" y2="' + axisY + '"/>');
    for (i = 0; i < n; i++) {
      var mm = histParseMonth(series[i].month);
      // Label each January only. Forcing labels at the first/last data point
      // collides with the adjacent January tick (e.g. Oct 2015 vs Jan 2016, and
      // Aug 2026 duplicating Jan 2026), so we drop the endpoint labels.
      var isTick = (mm.m === 1);
      if (!isTick) continue;
      var tx = X(i).toFixed(1);
      svg.push('<line class="hist-tick" x1="' + tx + '" y1="' + axisY + '" x2="' + tx + '" y2="' + (axisY + 5) + '"/>');
      svg.push('<text class="hist-axlabel" x="' + tx + '" y="' + (axisY + 18) + '" text-anchor="middle">' + mm.y + "</text>");
    }
    // axis titles
    svg.push('<text class="hist-axtitle" x="' + (padL + plotW / 2) + '" y="' + (H - 6) + '" text-anchor="middle">Bulletin month (Oct 2015 &rarr; Aug 2026)</text>');
    svg.push('<text class="hist-axtitle" transform="translate(14 ' + (padT + plotH / 2) + ') rotate(-90)" text-anchor="middle">Cutoff date (year)</text>');

    // --- priority-date overlay (drawn under the series) ---
    var pdCrossIdx = -1, pdNote = "";
    if (pdMs != null) {
      var pdY = Y(Math.max(yMin, Math.min(yMax, pdMs))).toFixed(1);
      svg.push('<line class="hist-pd-line" x1="' + padL + '" y1="' + pdY + '" x2="' + (W - padR) + '" y2="' + pdY + '"/>');
      svg.push('<text class="hist-pd-label" x="' + (padL + 6) + '" y="' + (parseFloat(pdY) - 5) + '">Your PD: ' + esc(fmtDate(pdStr) || pdStr) + "</text>");
      // First month the FAD reached/passed the PD (went current for that PD).
      for (i = 0; i < n; i++) {
        var fv = histVal(series[i].fad);
        if (fv.t === "current" || (fv.t === "iso" && fv.ms >= pdMs)) { pdCrossIdx = i; break; }
      }
      if (pdCrossIdx >= 0) {
        var cx = X(pdCrossIdx).toFixed(1);
        svg.push('<line class="hist-mark-line" x1="' + cx + '" y1="' + padT + '" x2="' + cx + '" y2="' + axisY + '"/>');
        svg.push('<circle class="hist-mark-dot" cx="' + cx + '" cy="' + pdY + '" r="4.5"/>');
        pdNote = 'Historically, the Final Action Date first reached your priority date in <strong>' +
          esc(fmtMonth(series[pdCrossIdx].month)) + "</strong>. (Descriptive only: a date going current in the past does not predict yours.)";
      } else {
        pdNote = "In this history (Oct 2015 &ndash; Aug 2026) the Final Action Date <strong>never reached your priority date</strong>. For a backlogged category the gap can widen rather than close. This is not a prediction; verify against the official Visa Bulletin.";
      }
    }

    // --- draw one series as broken line segments + CURRENT markers ---
    function drawSeries(field, cls, markCls) {
      var seg = [], parts = [], markers = [];
      function flush() {
        if (seg.length >= 2) parts.push('<polyline class="' + cls + '" points="' + seg.join(" ") + '"/>');
        else if (seg.length === 1) { var p = seg[0].split(","); markers.push('<circle class="' + markCls + ' hist-pt" cx="' + p[0] + '" cy="' + p[1] + '" r="2.4"/>'); }
        seg = [];
      }
      for (var j = 0; j < n; j++) {
        var kind = histVal(series[j][field]);
        if (kind.t === "iso") { seg.push(X(j).toFixed(1) + "," + Y(kind.ms).toFixed(1)); }
        else if (kind.t === "current") { flush(); markers.push('<path class="' + markCls + ' hist-curmark" d="' + histDiamond(X(j), curY, 4.5) + '"/>'); }
        else { flush(); }
      }
      flush();
      return parts.join("") + markers.join("");
    }
    // DFF dashed underneath, FAD solid on top.
    svg.push(drawSeries("dff", "hist-line hist-dff", "hist-dot-dff"));
    svg.push(drawSeries("fad", "hist-line hist-fad", "hist-dot-fad"));

    svg.push("</svg>");

    var legend =
      '<div class="hist-legend" aria-hidden="true">' +
      '<span class="hist-leg"><span class="hist-leg-line hist-leg-fad"></span>Final Action Date</span>' +
      '<span class="hist-leg"><span class="hist-leg-line hist-leg-dff"></span>Dates for Filing</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-cur"></span>Current (top band)</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-gap"></span>Unavailable / no chart (line breaks)</span>' +
      (pdMs != null ? '<span class="hist-leg"><span class="hist-leg-line hist-leg-pd"></span>Your priority date</span>' : "") +
      "</div>";

    var pdBlock = pdNote ? '<p class="hist-pdnote">' + pdNote + "</p>" : "";

    return '<figure class="hist-figure">' +
      '<figcaption class="hist-cap">Cutoff date over time: ' + esc(cat) + " " + esc(countryLabel(country)) +
      '<span class="hist-cap-sub">Running to stand still: the calendar advances every month, but for a backlogged category the cutoff barely moves.</span></figcaption>' +
      legend + svg.join("") + pdBlock + "</figure>";
  }

  // Small diamond path centered at (cx,cy) — the "CURRENT" marker.
  function histDiamond(cx, cy, r) {
    return "M " + cx.toFixed(1) + " " + (cy - r).toFixed(1) +
      " L " + (cx + r).toFixed(1) + " " + cy.toFixed(1) +
      " L " + cx.toFixed(1) + " " + (cy + r).toFixed(1) +
      " L " + (cx - r).toFixed(1) + " " + cy.toFixed(1) + " Z";
  }

  // Build the movement-velocity bar chart: month-over-month FAD change in days.
  function histVelocityChart(series) {
    var W = 760, H = 250, padL = 60, padR = 16, padT = 20, padB = 46;
    var n = series.length;
    var plotW = W - padL - padR, plotH = H - padT - padB;

    // Deltas only where BOTH this month and the previous are dated (skip U/CURRENT/null).
    var deltas = [], i, maxAbs = 0;
    for (i = 1; i < n; i++) {
      var a = histVal(series[i - 1].fad), b = histVal(series[i].fad);
      if (a.t === "iso" && b.t === "iso") {
        var days = Math.round((b.ms - a.ms) / HIST_MS_PER_DAY);
        deltas.push({ i: i, days: days, month: series[i].month });
        if (Math.abs(days) > maxAbs) maxAbs = Math.abs(days);
      }
    }
    if (!deltas.length) {
      return '<div class="tl-note">Not enough consecutive dated months to chart month-over-month movement for this category.</div>';
    }
    if (maxAbs === 0) maxAbs = 1;

    function X(idx) { return padL + (n === 1 ? plotW / 2 : (idx / (n - 1)) * plotW); }
    var zeroY = padT + plotH / 2;
    function barY(days) { return zeroY - (days / maxAbs) * (plotH / 2); }
    var barW = Math.max(2, (plotW / n) * 0.7);
    var FLAT = 5; // |days| <= 5 counts as a stall (muted)

    var svg = [];
    svg.push('<svg class="hist-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Month-over-month Final Action Date movement in days">');

    // y reference lines: +maxAbs, 0 (baseline), -maxAbs
    svg.push('<line class="hist-grid" x1="' + padL + '" y1="' + padT + '" x2="' + (W - padR) + '" y2="' + padT + '"/>');
    svg.push('<text class="hist-axlabel" x="' + (padL - 8) + '" y="' + padT + '" text-anchor="end" dominant-baseline="middle">+' + maxAbs + "d</text>");
    svg.push('<line class="hist-axis hist-zero" x1="' + padL + '" y1="' + zeroY + '" x2="' + (W - padR) + '" y2="' + zeroY + '"/>');
    svg.push('<text class="hist-axlabel" x="' + (padL - 8) + '" y="' + zeroY + '" text-anchor="end" dominant-baseline="middle">0</text>');
    svg.push('<line class="hist-grid" x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (W - padR) + '" y2="' + (padT + plotH) + '"/>');
    svg.push('<text class="hist-axlabel" x="' + (padL - 8) + '" y="' + (padT + plotH) + '" text-anchor="end" dominant-baseline="middle">&minus;' + maxAbs + "d</text>");

    // bars
    for (i = 0; i < deltas.length; i++) {
      var d = deltas[i], bx = (X(d.i) - barW / 2).toFixed(1);
      var yTop, hgt;
      if (d.days >= 0) { yTop = barY(d.days); hgt = zeroY - yTop; }
      else { yTop = zeroY; hgt = barY(d.days) - zeroY; }
      var cls = Math.abs(d.days) <= FLAT ? "hist-bar-flat" : (d.days > 0 ? "hist-bar-pos" : "hist-bar-neg");
      var title = fmtMonth(d.month) + ": " + (d.days > 0 ? "+" : "") + d.days + " days" +
        (d.days < -FLAT ? " (retrogression)" : (d.days > FLAT ? " (advance)" : " (stall)"));
      svg.push('<rect class="hist-bar ' + cls + '" x="' + bx + '" y="' + Math.min(yTop, zeroY).toFixed(1) +
        '" width="' + barW.toFixed(1) + '" height="' + Math.max(0.5, Math.abs(hgt)).toFixed(1) + '"><title>' + esc(title) + "</title></rect>");
    }

    // x year ticks (reuse January markers)
    var axisY = padT + plotH;
    for (i = 0; i < n; i++) {
      var mm = histParseMonth(series[i].month);
      if (mm.m !== 1) continue;
      var tx = X(i).toFixed(1);
      svg.push('<text class="hist-axlabel" x="' + tx + '" y="' + (axisY + 18) + '" text-anchor="middle">' + mm.y + "</text>");
    }
    svg.push('<text class="hist-axtitle" transform="translate(14 ' + (padT + plotH / 2) + ') rotate(-90)" text-anchor="middle">FAD change (days)</text>');
    svg.push("</svg>");

    var legend =
      '<div class="hist-legend" aria-hidden="true">' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-pos"></span>Advance</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-neg"></span>Retrogression</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-flat"></span>Stall (&plusmn;5 days)</span>' +
      "</div>";

    return '<figure class="hist-figure">' +
      '<figcaption class="hist-cap">Movement velocity: how many days the Final Action Date moved each month' +
      '<span class="hist-cap-sub">Positive bars advance the cutoff; negative bars are retrogressions. Large positive bars around October are largely the fiscal-year quota reset, not a trend.</span></figcaption>' +
      legend + svg.join("") + "</figure>";
  }

  // Classify one heatmap cell by this month's month-over-month FAD velocity.
  // CURRENT and Unavailable/null are their own states; a dated month with no
  // dated prior month can't be compared (no-data). FLAT = +/-5 days is a stall.
  function histCellState(prevFad, curFad) {
    var cur = histVal(curFad);
    if (cur.t === "current") return { cls: "hist-hm-current", label: "Current" };
    if (cur.t === "gap") return { cls: "hist-hm-unavail", label: cur.reason === "unavailable" ? "Unavailable" : "no data" };
    var prev = histVal(prevFad);
    if (prev.t !== "iso") return { cls: "hist-hm-nodata", label: (fmtDate(curFad) || curFad) + " (no prior month to compare)" };
    var days = Math.round((cur.ms - prev.ms) / HIST_MS_PER_DAY);
    var FLAT = 5;
    if (days > FLAT) return { cls: "hist-hm-adv", label: "advanced " + days + " days" };
    if (days < -FLAT) return { cls: "hist-hm-retro", label: "retrogressed " + Math.abs(days) + " days" };
    return { cls: "hist-hm-stall", label: "held steady (" + (days > 0 ? "+" : "") + days + " days)" };
  }

  // Build the whole-country retrogression heatmap: rows = the 5 EB categories
  // for the selected country, columns = the 119 bulletin months, each cell an
  // SVG rect colored by that month's month-over-month FAD velocity. Historical
  // and descriptive, not a prediction. selCat (if present) outlines its row.
  function histRetroHeatmap(country, selCat) {
    var rows = [], monthsRef = null, i, j;
    for (i = 0; i < HIST_EB_CATS.length; i++) {
      var s = HIST_CACHE[HIST_EB_CATS[i] + "|" + country];
      if (s && s.length) {
        rows.push({ cat: HIST_EB_CATS[i], series: s });
        if (!monthsRef || s.length > monthsRef.length) monthsRef = s;
      }
    }
    if (!rows.length) {
      return '<div class="tl-note">No historical bulletin data to build a retrogression heatmap for ' + esc(countryLabel(country)) + ".</div>";
    }
    var nCols = monthsRef.length;

    var W = 760, padL = 56, padR = 14, padT = 18, padB = 30;
    var cellH = 24, rowGap = 3;
    var plotW = W - padL - padR;
    var cellW = plotW / nCols;
    var gridH = rows.length * cellH + (rows.length - 1) * rowGap;
    var H = padT + gridH + padB;

    function rowY(r) { return padT + r * (cellH + rowGap); }
    function colX(c) { return padL + c * cellW; }

    var svg = [];
    svg.push('<svg class="hist-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Retrogression heatmap for ' + esc(countryLabel(country)) + ', all employment-based categories">');

    var selIdx = -1;
    for (i = 0; i < rows.length; i++) {
      var s2 = rows[i].series, ry = rowY(i);
      if (rows[i].cat === selCat) selIdx = i;
      svg.push('<text class="hist-axlabel hist-hm-rowlabel' + (rows[i].cat === selCat ? " hist-hm-rowsel" : "") + '" x="' + (padL - 8) + '" y="' + (ry + cellH / 2) + '" text-anchor="end" dominant-baseline="middle">' + esc(rows[i].cat) + "</text>");
      for (j = 0; j < s2.length; j++) {
        var st = histCellState(j > 0 ? s2[j - 1].fad : null, s2[j].fad);
        var title = rows[i].cat + ", " + fmtMonth(s2[j].month) + ": " + st.label;
        // data-* carries the parts the readout needs so it does not have to parse
        // the title string back apart. tabindex makes each cell reachable by
        // keyboard: the native <title> tooltip never appears for keyboard or
        // touch users, which is most of the audience on a phone.
        svg.push('<rect class="hist-hm-cell ' + st.cls + '" x="' + colX(j).toFixed(2) + '" y="' + ry.toFixed(1) +
          '" width="' + cellW.toFixed(2) + '" height="' + cellH + '"' +
          ' tabindex="0" role="img" data-hm-cat="' + esc(rows[i].cat) + '"' +
          ' data-hm-month="' + esc(fmtMonth(s2[j].month)) + '"' +
          ' data-hm-state="' + esc(st.label) + '"' +
          ' data-hm-cls="' + st.cls + '"' +
          ' aria-label="' + esc(title) + '"><title>' + esc(title) + "</title></rect>");
      }
    }
    // Outline the picked category's row so the heatmap ties to the pickers.
    if (selIdx >= 0) {
      svg.push('<rect class="hist-hm-selbox" x="' + padL + '" y="' + rowY(selIdx).toFixed(1) + '" width="' + plotW.toFixed(1) + '" height="' + cellH + '"/>');
    }

    // x-axis year ticks (January of each year, plus the ends).
    var axisY = padT + gridH;
    for (j = 0; j < monthsRef.length; j++) {
      var mm = histParseMonth(monthsRef[j].month);
      if (mm.m !== 1) continue;
      var tx = (colX(j) + cellW / 2).toFixed(1);
      svg.push('<text class="hist-axlabel" x="' + tx + '" y="' + (axisY + 16) + '" text-anchor="middle">' + mm.y + "</text>");
    }
    svg.push("</svg>");

    var legend =
      '<div class="hist-legend" aria-hidden="true">' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-adv"></span>Advance</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-retro"></span>Retrogression</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-stall"></span>Stall (&plusmn;5 days)</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-curcell"></span>Current</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-unavail"></span>Unavailable / no data</span>' +
      "</div>";

    var defs =
      '<ul class="hist-hm-defs">' +
      '<li class="d-adv"><b>Advance</b> \u2014 the cutoff date moved forward, so the queue let more people through. More than 5 days of forward movement.</li>' +
      '<li class="d-retro"><b>Retrogression</b> \u2014 the cutoff moved BACKWARD, so people who were eligible last month no longer are. Demand for that month exceeded the visas available, and the date is pulled back to slow it down.</li>' +
      '<li class="d-stall"><b>Stall</b> \u2014 the cutoff barely moved, within 5 days either way. Effectively a month of no progress.</li>' +
      '<li class="d-current"><b>Current</b> \u2014 no backlog at all for that category and country. Anyone with an approved petition can move ahead regardless of their priority date. This is the best state, not merely an up-to-date one.</li>' +
      '<li class="d-unavail"><b>Unavailable</b> \u2014 no cutoff was published, shown as &ldquo;U&rdquo; on the bulletin. Nobody in that category can be approved that month, usually because the annual supply for the fiscal year is gone. Also covers months with no published figure.</li>' +
      "</ul>";
    var readout =
      '<div class="hist-hm-readout is-empty" data-hm-readout aria-live="polite">' +
      '<span>Point at or tab to any month to read what happened.</span></div>';

    return '<figure class="hist-figure">' +
      '<figcaption class="hist-cap">Retrogression heatmap: ' + esc(countryLabel(country)) + ', all employment categories' +
      '<span class="hist-cap-sub">Each cell is one month&rsquo;s Final Action Date movement for that category, oldest on the left. The first month of each row has no prior month to compare against. Historical and descriptive: not a prediction.</span></figcaption>' +
      legend + defs + readout + svg.join("") + "</figure>";
  }

  // Build the EB-2 vs EB-3 crossover chart for the selected country: both FAD
  // lines overlaid (x = month, y = cutoff date), with the months where EB-3 is
  // AHEAD of EB-2 shaded (the classic "downgrade window" signal). Always
  // compares EB-2 and EB-3 regardless of the category picker.
  function histCrossoverChart(country) {
    var s2 = HIST_CACHE["EB-2|" + country], s3 = HIST_CACHE["EB-3|" + country];
    if (!s2 || !s2.length || !s3 || !s3.length) {
      return '<div class="tl-note">No EB-2 / EB-3 history available for ' + esc(countryLabel(country)) + " to compare.</div>";
    }
    var n = Math.min(s2.length, s3.length);
    var W = 760, H = 300, padL = 60, padR = 16, padT = 18, padB = 44;
    var plotW = W - padL - padR, plotH = H - padT - padB;

    // y-domain from every dated FAD value across both series.
    var msVals = [], i, a, b;
    for (i = 0; i < n; i++) {
      a = histVal(s2[i].fad); if (a.t === "iso") msVals.push(a.ms);
      b = histVal(s3[i].fad); if (b.t === "iso") msVals.push(b.ms);
    }
    if (!msVals.length) {
      return '<div class="tl-note">EB-2 and EB-3 for ' + esc(countryLabel(country)) + ' have no dated cutoffs to chart (every month is Current or Unavailable).</div>';
    }
    var yMin = Math.min.apply(null, msVals), yMax = Math.max.apply(null, msVals);
    if (yMin === yMax) { yMin -= HIST_MS_PER_YEAR; yMax += HIST_MS_PER_YEAR; }
    var padY = (yMax - yMin) * 0.05; yMin -= padY; yMax += padY;

    function X(idx) { return padL + (n === 1 ? plotW / 2 : (idx / (n - 1)) * plotW); }
    function Y(ms) { return padT + plotH - ((ms - yMin) / (yMax - yMin)) * plotH; }

    var svg = [];
    svg.push('<svg class="hist-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="EB-2 versus EB-3 Final Action Date crossover for ' + esc(countryLabel(country)) + '">');

    // y gridlines + year labels
    var y0 = new Date(yMin).getUTCFullYear(), y1 = new Date(yMax).getUTCFullYear();
    var yStep = Math.max(1, Math.ceil((y1 - y0 + 1) / 7));
    for (var yr = y0; yr <= y1; yr += yStep) {
      var yms = Date.UTC(yr, 0, 1);
      if (yms < yMin || yms > yMax) continue;
      var gy = Y(yms).toFixed(1);
      svg.push('<line class="hist-grid" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>');
      svg.push('<text class="hist-axlabel" x="' + (padL - 8) + '" y="' + gy + '" text-anchor="end" dominant-baseline="middle">' + yr + "</text>");
    }

    // --- shaded "EB-3 ahead of EB-2" regions (drawn first, under the lines) ---
    var axisY = padT + plotH;
    var runStart = -1, anyAhead = false;
    function flushBand(endIdx) {
      if (runStart < 0) return;
      var x1 = X(Math.max(0, runStart - 0.5)), x2 = X(Math.min(n - 1, endIdx + 0.5));
      svg.push('<rect class="hist-x-band" x="' + x1.toFixed(1) + '" y="' + padT + '" width="' + Math.max(0, x2 - x1).toFixed(1) + '" height="' + plotH + '"/>');
      runStart = -1;
    }
    for (i = 0; i < n; i++) {
      a = histVal(s2[i].fad); b = histVal(s3[i].fad);
      if (a.t === "iso" && b.t === "iso" && b.ms > a.ms) { anyAhead = true; if (runStart < 0) runStart = i; }
      else { flushBand(i - 1); }
    }
    flushBand(n - 1);

    // x axis baseline + year ticks
    svg.push('<line class="hist-axis" x1="' + padL + '" y1="' + axisY + '" x2="' + (W - padR) + '" y2="' + axisY + '"/>');
    for (i = 0; i < n; i++) {
      var mm = histParseMonth(s2[i].month);
      if (mm.m !== 1) continue;
      var tx = X(i).toFixed(1);
      svg.push('<line class="hist-tick" x1="' + tx + '" y1="' + axisY + '" x2="' + tx + '" y2="' + (axisY + 5) + '"/>');
      svg.push('<text class="hist-axlabel" x="' + tx + '" y="' + (axisY + 18) + '" text-anchor="middle">' + mm.y + "</text>");
    }
    svg.push('<text class="hist-axtitle" x="' + (padL + plotW / 2) + '" y="' + (H - 6) + '" text-anchor="middle">Bulletin month (Oct 2015 &rarr; Aug 2026)</text>');
    svg.push('<text class="hist-axtitle" transform="translate(14 ' + (padT + plotH / 2) + ') rotate(-90)" text-anchor="middle">Cutoff date (year)</text>');

    // --- broken FAD line per series (skip Current / Unavailable / null) ---
    function drawFad(series, cls, dotCls) {
      var seg = [], parts = [], markers = [];
      function flush() {
        if (seg.length >= 2) parts.push('<polyline class="' + cls + '" points="' + seg.join(" ") + '"/>');
        else if (seg.length === 1) { var p = seg[0].split(","); markers.push('<circle class="' + dotCls + ' hist-pt" cx="' + p[0] + '" cy="' + p[1] + '" r="2.4"/>'); }
        seg = [];
      }
      for (var k = 0; k < n; k++) {
        var v = histVal(series[k].fad);
        if (v.t === "iso") seg.push(X(k).toFixed(1) + "," + Y(v.ms).toFixed(1));
        else flush();
      }
      flush();
      return parts.join("") + markers.join("");
    }
    svg.push(drawFad(s2, "hist-line hist-eb2", "hist-dot-eb2"));
    svg.push(drawFad(s3, "hist-line hist-eb3", "hist-dot-eb3"));
    svg.push("</svg>");

    var legend =
      '<div class="hist-legend" aria-hidden="true">' +
      '<span class="hist-leg"><span class="hist-leg-line hist-leg-eb2"></span>EB-2 Final Action Date</span>' +
      '<span class="hist-leg"><span class="hist-leg-line hist-leg-eb3"></span>EB-3 Final Action Date</span>' +
      '<span class="hist-leg"><span class="hist-leg-swatch hist-leg-xband"></span>EB-3 ahead of EB-2</span>' +
      "</div>";

    var aheadNote = anyAhead
      ? "Shaded months are when the EB-3 cutoff sat <strong>ahead of EB-2</strong> for " + esc(countryLabel(country)) + ", the classic &ldquo;downgrade window&rdquo; signal."
      : "In this history (Oct 2015 &ndash; Aug 2026), EB-3 was <strong>never ahead of EB-2</strong> for " + esc(countryLabel(country)) + " in a month where both had dated cutoffs.";

    return '<figure class="hist-figure">' +
      '<figcaption class="hist-cap">EB-2 vs EB-3 crossover: ' + esc(countryLabel(country)) +
      '<span class="hist-cap-sub">' + aheadNote +
      " When EB-3 leads EB-2, some applicants explore &ldquo;downgrading&rdquo; an EB-2 case to EB-3 to file sooner. It is fact-specific, can reverse from month to month, and is <strong>not legal advice</strong>. Discuss any downgrade with an immigration attorney. This figure always compares EB-2 and EB-3, so it ignores the category picker; it is historical and descriptive, not a prediction.</span></figcaption>" +
      legend + svg.join("") + "</figure>";
  }

  // Standalone History & Trends section on tools.html. No-op elsewhere.
  function initHistoryTrends() {
    var root = document.getElementById("history-standalone");
    var out = document.getElementById("history-standalone-out");
    if (!root || !out) return;
    var catSel = document.getElementById("hist-category");
    var countrySel = document.getElementById("hist-country");
    var pdInput = document.getElementById("hist-pd");

    var CAVEAT = '<p class="hist-caveat">Historical and descriptive: <strong>not a prediction.</strong> ' +
      "Cutoff movement is not the same as your personal wait time, and past movement (including retrogressions and big October resets) does not forecast the future. " +
      "Always verify against the official " +
      '<a href="https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html" target="_blank" rel="noopener noreferrer">Visa Bulletin</a>. This is not legal advice.</p>';

    function render() {
      if (HIST_FETCH_STATE === "failed") {
        out.innerHTML = '<div class="tl-note">Could not load the historical Visa Bulletin data (vb_history.json). The other tools on this page still work. Try reloading to see history.</div>';
        return;
      }
      if (HIST_FETCH_STATE !== "ready" || !HIST_CACHE) {
        out.innerHTML = '<p class="help">Loading historical Visa Bulletin data&hellip;</p>';
        return;
      }
      var cat = catSel ? catSel.value : "EB-2";
      var country = countrySel ? countrySel.value : "India";
      var pd = pdInput ? pdInput.value : "";
      var series = HIST_CACHE[cat + "|" + country];
      if (!series || !series.length) {
        out.innerHTML = '<div class="tl-note">No historical bulletin data for ' + esc(cat) + " " + esc(countryLabel(country)) + ".</div>";
        return;
      }
      out.innerHTML = histLineChart(series, cat, country, pd) + histVelocityChart(series) +
        histRetroHeatmap(country, cat) + histCrossoverChart(country) + CAVEAT;
    }

    // Live readout for the heatmap. ONE delegated listener on the container, bound
    // once, rather than a handler per cell: a 5x119 grid is 595 cells and rebuilds
    // on every picker change, so per-cell listeners would leak on each re-render.
    // Delegation also survives the innerHTML replacement above for free.
    function hmDescribe(t) {
      var ro = out.querySelector("[data-hm-readout]");
      if (!ro) return;
      if (!t || !t.getAttribute || !t.getAttribute("data-hm-cat")) return;
      var cls = t.getAttribute("data-hm-cls") || "";
      // Map the cell class to the matching swatch colour so the readout's dot
      // always agrees with the cell you are pointing at.
      var key = cls.indexOf("hm-adv") > -1 ? "--hm-adv"
              : cls.indexOf("hm-retro") > -1 ? "--hm-retro"
              : cls.indexOf("hm-current") > -1 ? "--hm-current"
              : cls.indexOf("hm-unavail") > -1 ? "--hm-unavail"
              : "--hm-stall";
      ro.classList.remove("is-empty");
      ro.innerHTML = '<span class="hm-ro-dot" style="background: var(' + key + ')"></span>' +
        '<span><span class="hm-ro-cat">' + esc(t.getAttribute("data-hm-cat")) + "</span> \u00b7 " +
        esc(t.getAttribute("data-hm-month")) + ": " +
        '<span class="hm-ro-state">' + esc(t.getAttribute("data-hm-state")) + "</span></span>";
    }
    function hmReset() {
      var ro = out.querySelector("[data-hm-readout]");
      if (!ro) return;
      ro.classList.add("is-empty");
      ro.innerHTML = "<span>Point at or tab to any month to read what happened.</span>";
    }
    out.addEventListener("mouseover", function (e) { hmDescribe(e.target); });
    out.addEventListener("focusin", function (e) { hmDescribe(e.target); });
    // Touch: there is no hover, so a tap has to fill the readout.
    out.addEventListener("click", function (e) { hmDescribe(e.target); });
    out.addEventListener("mouseleave", function (e) {
      if (e.target === out) hmReset();
    });

    if (catSel) catSel.addEventListener("change", render);
    if (countrySel) countrySel.addEventListener("change", render);
    if (pdInput) { pdInput.addEventListener("change", render); pdInput.addEventListener("input", render); }

    render(); // shows the loading state immediately
    if (HIST_FETCH_STATE === "ready") return;
    if (HIST_FETCH_STATE === "loading") return;
    HIST_FETCH_STATE = "loading";
    try {
      fetch("vb_history.json").then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (json) {
        HIST_CACHE = json; HIST_FETCH_STATE = "ready"; render();
      })["catch"](function () {
        HIST_FETCH_STATE = "failed"; render();
      });
    } catch (e) {
      HIST_FETCH_STATE = "failed"; render();
    }
  }

  /* ==================== PERM PROCESSING TIME (tools.html) ====================
     Renders two hand-rolled SVG views from the committed perm_history.json (14
     fiscal-quarter records, FY2023 Q1 -> FY2026 Q2): a median-processing-time
     line/area chart (with a months hint) and a decision-volume bar chart
     (certified, with denied+withdrawn stacked). FY2024Q4 is a known DOL
     form-transition undercount and is flagged (hollow marker/bar) and kept out
     of the volume y-scale. Historical/descriptive, not a prediction. No-ops when
     its root element is absent (every other page). */

  var PERM_CACHE = null;          // parsed perm_history.json (fetched once)
  var PERM_FETCH_STATE = "idle";  // idle | loading | ready | failed

  var PERM_CAVEAT = '<p class="perm-caveat">PERM (the ETA-9089 labor certification) is the <strong>first</strong> stage of an employment green card. It comes <strong>before</strong> the I-140 petition and the priority-date wait in the Visa Bulletin, so this is <em>not</em> the green-card wait itself. &ldquo;Median&rdquo; here is the DOL decision date minus the case-received date for certified cases, an approximation of adjudication time. Per-country PERM times are nearly identical: where reported (FY2023&ndash;FY2024) the India, China, and Rest-of-World medians differ by only a few days, because DOL adjudicates roughly first-in, first-out and nationality-independent. Source: DOL OFLC disclosure data. Historical and descriptive: <strong>not a prediction, not legal advice.</strong></p>';

  // Thousands separator for whole-number counts.
  function permNum(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  // "FY2023Q1" -> "FY23 Q1" (compact axis label).
  function permQuarterLabel(q) {
    var m = /^FY(\d{4})Q(\d)$/.exec(String(q || ""));
    return m ? "FY" + m[1].slice(2) + " Q" + m[2] : String(q || "");
  }

  // Flag partial/undercount quarters: certified far below the neighbouring
  // quarters (catches the FY2024Q4 DOL form-transition undercount without
  // hard-coding it). Returns a boolean[] aligned to records.
  function permPartialFlags(records) {
    var n = records.length, flags = [], i;
    for (i = 0; i < n; i++) {
      var neigh = [];
      if (i > 0) neigh.push(records[i - 1].certified);
      if (i < n - 1) neigh.push(records[i + 1].certified);
      var avg = records[i].certified;
      if (neigh.length) {
        var s = 0, k;
        for (k = 0; k < neigh.length; k++) { s += neigh[k]; }
        avg = s / neigh.length;
      }
      // A severe undercount (<30% of neighbouring quarters) marks a partial
      // quarter. FY2024Q4 sits at ~7% of its neighbours; genuine low quarters
      // (e.g. FY2026Q1 at ~40%) stay unflagged.
      flags[i] = records[i].certified < 0.3 * avg;
    }
    return flags;
  }

  // Median processing-time line/area chart by fiscal quarter.
  function permMedianChart(records) {
    var W = 760, H = 340, padL = 52, padR = 54, padT = 22, padB = 66;
    var n = records.length;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var flags = permPartialFlags(records);

    var maxMed = 0, i;
    for (i = 0; i < n; i++) { if (records[i].median_days > maxMed) maxMed = records[i].median_days; }
    var STEP = 90;
    var yMax = Math.ceil((maxMed * 1.05) / STEP) * STEP;
    if (yMax < STEP) yMax = STEP;

    function X(idx) { return padL + (n === 1 ? plotW / 2 : (idx / (n - 1)) * plotW); }
    function Y(v) { return padT + plotH - (v / yMax) * plotH; }
    var baseY = padT + plotH;

    var svg = [];
    svg.push('<svg class="perm-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Median PERM processing time in days by fiscal quarter, FY2023 Q1 to FY2026 Q2">');

    // gridlines + dual labels (days on the left, months on the right)
    for (var g = 0; g <= yMax; g += STEP) {
      var gy = Y(g).toFixed(1);
      svg.push('<line class="perm-grid" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>');
      svg.push('<text class="perm-axlabel" x="' + (padL - 8) + '" y="' + gy + '" text-anchor="end" dominant-baseline="middle">' + g + "</text>");
      svg.push('<text class="perm-axlabel perm-axlabel-mo" x="' + (W - padR + 8) + '" y="' + gy + '" text-anchor="start" dominant-baseline="middle">' + Math.round(g / 30) + " mo</text>");
    }
    svg.push('<line class="perm-axis" x1="' + padL + '" y1="' + baseY.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + baseY.toFixed(1) + '"/>');

    // area under the median line
    var areaPts = [X(0).toFixed(1) + "," + baseY.toFixed(1)];
    for (i = 0; i < n; i++) { areaPts.push(X(i).toFixed(1) + "," + Y(records[i].median_days).toFixed(1)); }
    areaPts.push(X(n - 1).toFixed(1) + "," + baseY.toFixed(1));
    svg.push('<polygon class="perm-area" points="' + areaPts.join(" ") + '"/>');

    // line segments (dashed where a partial quarter is an endpoint)
    for (i = 1; i < n; i++) {
      var dashed = flags[i - 1] || flags[i];
      svg.push('<line class="perm-line' + (dashed ? " perm-line-flag" : "") + '" x1="' + X(i - 1).toFixed(1) + '" y1="' + Y(records[i - 1].median_days).toFixed(1) +
        '" x2="' + X(i).toFixed(1) + '" y2="' + Y(records[i].median_days).toFixed(1) + '"/>');
    }

    // x labels (rotated) + point markers with tooltips
    for (i = 0; i < n; i++) {
      var px = X(i), py = Y(records[i].median_days);
      var lbl = permQuarterLabel(records[i].quarter);
      svg.push('<text class="perm-xlabel" x="' + px.toFixed(1) + '" y="' + (baseY + 14) + '" text-anchor="end" transform="rotate(-40 ' + px.toFixed(1) + " " + (baseY + 14) + ')">' + esc(lbl) + "</text>");
      var mo = (records[i].median_days / 30).toFixed(1);
      var tip = records[i].quarter + ": " + records[i].median_days + " days (~" + mo + " mo) median" + (flags[i] ? " (partial quarter, treat with caution)" : "");
      if (flags[i]) {
        svg.push('<circle class="perm-pt-flag" cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="4.2"><title>' + esc(tip) + "</title></circle>");
      } else {
        svg.push('<circle class="perm-pt" cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="3.4"><title>' + esc(tip) + "</title></circle>");
      }
    }

    // months hint near the last point
    var lastX = X(n - 1), lastY = Y(records[n - 1].median_days);
    var lastMo = (records[n - 1].median_days / 30).toFixed(1);
    svg.push('<text class="perm-annot" x="' + (lastX - 6).toFixed(1) + '" y="' + (lastY - 9).toFixed(1) + '" text-anchor="end">' + records[n - 1].median_days + " days (~" + lastMo + " mo)</text>");

    // axis titles
    svg.push('<text class="perm-axtitle" x="' + (padL + plotW / 2) + '" y="' + (H - 4) + '" text-anchor="middle">Fiscal quarter (FY2023 Q1 &rarr; FY2026 Q2)</text>');
    svg.push('<text class="perm-axtitle" transform="translate(12 ' + (padT + plotH / 2) + ') rotate(-90)" text-anchor="middle">Median days to decision</text>');
    svg.push("</svg>");

    var legend =
      '<div class="perm-legend" aria-hidden="true">' +
      '<span class="perm-leg"><span class="perm-leg-line perm-leg-median"></span>Median days (certified cases)</span>' +
      '<span class="perm-leg"><span class="perm-leg-dot-flag"></span>Partial quarter (flagged)</span>' +
      "</div>";

    return '<figure class="perm-figure">' +
      '<figcaption class="perm-cap">Median PERM processing time by quarter' +
      '<span class="perm-cap-sub">Days from DOL receiving the case to a decision, over certified cases. The median has climbed from about 8.5 months (259 days) to about 16.8 months (503 days).</span></figcaption>' +
      legend + svg.join("") +
      '<p class="perm-foot">FY2024Q4 is partial (DOL form transition); treat with caution.</p>' +
      "</figure>";
  }

  // Decision-volume bar chart: certified (primary) with denied+withdrawn stacked.
  function permVolumeChart(records) {
    var W = 760, H = 300, padL = 52, padR = 16, padT = 20, padB = 66;
    var n = records.length;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var flags = permPartialFlags(records);

    // Size the scale from the non-partial quarters so FY2024Q4 can't distort it.
    var maxTot = 0, i;
    for (i = 0; i < n; i++) {
      if (flags[i]) continue;
      var t = records[i].certified + records[i].denied + records[i].withdrawn;
      if (t > maxTot) maxTot = t;
    }
    if (maxTot <= 0) maxTot = 1;
    var STEP = 10000;
    var yMax = Math.ceil((maxTot * 1.05) / STEP) * STEP;

    function X(idx) { return padL + (n === 1 ? plotW / 2 : (idx / (n - 1)) * plotW); }
    var baseY = padT + plotH;
    function barTop(v) { return baseY - (v / yMax) * plotH; }
    var barW = Math.max(6, (plotW / n) * 0.62);

    var svg = [];
    svg.push('<svg class="perm-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="PERM decision volume by fiscal quarter: certified, denied and withdrawn cases">');

    for (var g = 0; g <= yMax; g += STEP) {
      var gy = barTop(g).toFixed(1);
      svg.push('<line class="perm-grid" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>');
      svg.push('<text class="perm-axlabel" x="' + (padL - 8) + '" y="' + gy + '" text-anchor="end" dominant-baseline="middle">' + (g / 1000) + "k</text>");
    }
    svg.push('<line class="perm-axis" x1="' + padL + '" y1="' + baseY.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + baseY.toFixed(1) + '"/>');

    for (i = 0; i < n; i++) {
      var cx = X(i), bx = (cx - barW / 2);
      var cert = records[i].certified, other = records[i].denied + records[i].withdrawn;
      var certTop = barTop(cert), stackTop = barTop(cert + other);
      var lbl = permQuarterLabel(records[i].quarter);
      var tip = records[i].quarter + ": " + permNum(cert) + " certified, " + permNum(records[i].denied) + " denied, " + permNum(records[i].withdrawn) + " withdrawn" + (flags[i] ? " (partial, DOL form transition)" : "");
      svg.push('<g class="perm-barg"><title>' + esc(tip) + "</title>");
      if (flags[i]) {
        svg.push('<rect class="perm-bar-flag" x="' + bx.toFixed(1) + '" y="' + stackTop.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(0.5, baseY - stackTop).toFixed(1) + '"/>');
      } else {
        svg.push('<rect class="perm-bar-cert" x="' + bx.toFixed(1) + '" y="' + certTop.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(0.5, baseY - certTop).toFixed(1) + '"/>');
        svg.push('<rect class="perm-bar-other" x="' + bx.toFixed(1) + '" y="' + stackTop.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(0.5, certTop - stackTop).toFixed(1) + '"/>');
      }
      svg.push("</g>");
      svg.push('<text class="perm-xlabel" x="' + cx.toFixed(1) + '" y="' + (baseY + 14) + '" text-anchor="end" transform="rotate(-40 ' + cx.toFixed(1) + " " + (baseY + 14) + ')">' + esc(lbl) + "</text>");
    }

    svg.push('<text class="perm-axtitle" x="' + (padL + plotW / 2) + '" y="' + (H - 4) + '" text-anchor="middle">Fiscal quarter (FY2023 Q1 &rarr; FY2026 Q2)</text>');
    svg.push('<text class="perm-axtitle" transform="translate(12 ' + (padT + plotH / 2) + ') rotate(-90)" text-anchor="middle">Decisions per quarter</text>');
    svg.push("</svg>");

    var legend =
      '<div class="perm-legend" aria-hidden="true">' +
      '<span class="perm-leg"><span class="perm-leg-swatch perm-leg-cert"></span>Certified</span>' +
      '<span class="perm-leg"><span class="perm-leg-swatch perm-leg-other"></span>Denied + withdrawn</span>' +
      '<span class="perm-leg"><span class="perm-leg-swatch perm-leg-flag"></span>Partial quarter (excluded from scale)</span>' +
      "</div>";

    return '<figure class="perm-figure">' +
      '<figcaption class="perm-cap">Decision volume by quarter' +
      '<span class="perm-cap-sub">Certified cases (primary) with denied and withdrawn stacked on top. Hover a bar for exact counts.</span></figcaption>' +
      legend + svg.join("") +
      '<p class="perm-foot">FY2024Q4 is partial (DOL form transition); its bar is drawn hollow and excluded from the y-scale.</p>' +
      "</figure>";
  }

  // ---------------------------------------------------------------------
  // Where the DOL queue stands right now. Reads automation/dol_queue.json,
  // which fetch_dol_queue.py mirrors weekly from flag.dol.gov/processingtimes.
  // No-op on any page without #dol-queue-out.
  //
  // Every field is guarded individually and NOT on parse_ok, because parse_ok
  // only means "at least one figure was read" - never that a given figure is
  // populated. DOL publishes "N/A" and "--" for some cells and the fetcher
  // records those as null, so a missing value must render as absent, never as
  // "undefined" and never as zero.
  // ---------------------------------------------------------------------
  function initDolQueue() {
    var out = document.getElementById("dol-queue-out");
    if (!out) return;

    function ageDays(iso) {
      if (!iso) return null;
      var t = Date.parse(iso + "T00:00:00Z");
      if (isNaN(t)) return null;
      return Math.floor((Date.now() - t) / 86400000);
    }
    function stale(iso) {
      var d = ageDays(iso);
      if (d === null) return "";
      // Plain text: cell() wraps this in .sub, which already carries the muted
      // small styling. Nesting a .help span inside it double-styled the line.
      return "as of " + esc(iso) + ", " + d + " day" + (d === 1 ? "" : "s") + " ago";
    }
    function cell(label, value, note) {
      if (value === null || value === undefined || value === "") return "";
      // These MUST be divs, not spans. The other four .bulletin-cell call sites use
      // divs; spans are inline, so the label and the value rendered on the same line
      // and their margins were ignored entirely.
      return '<div class="bulletin-cell"><div class="label">' + esc(label) +
             '</div><div class="value">' + esc(String(value)) + "</div>" +
             (note ? '<div class="sub">' + note + "</div>" : "") + "</div>";
    }

    fetch("automation/dol_queue.json", { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) { out.innerHTML = ""; return; }
        var perm = d.perm || {}, pwd = d.prevailing_wage || {};
        var st = perm.stages || {};
        var avg = (perm.average_calendar_days || {}).analyst_review || {};
        var q = (pwd.queues || {})["PERM"] || {};
        var pend = (pwd.pending_requests || {})["PERM"] || {};

        var cells = [
          cell("PERM in analyst review", (st.analyst_review || {}).month_label,
               stale(perm.as_of)),
          cell("PERM in audit review", (st.audit_review || {}).month_label),
          cell("Average days to a PERM decision",
               avg.calendar_days != null ? avg.calendar_days + " days" : null),
          cell("Prevailing wage requests being worked",
               (q.oews_receipt || {}).month_label, stale(pwd.as_of)),
          cell("Prevailing wage requests pending",
               pend.total_remaining_requests != null
                 ? Number(pend.total_remaining_requests).toLocaleString() : null)
        ].join("");

        if (!cells) { out.innerHTML = ""; return; }
        out.innerHTML =
          '<p class="hub-sub" style="margin-bottom:10px;"><strong>Where the queue stands ' +
          'now.</strong> These are the months the Department of Labor says it is currently ' +
          'working on. They are not a prediction of your own case.</p>' +
          '<div class="bulletin-row dol-row">' + cells + "</div>" +
          (d.source_note ? '<p class="perm-foot">' + esc(d.source_note) + "</p>" : "");
      })
      .catch(function () { out.innerHTML = ""; });
  }

  // Standalone PERM Processing Time section on tools.html. No-op elsewhere.
  function initPermHistory() {
    var out = document.getElementById("perm-standalone-out");
    if (!out) return;

    function render() {
      if (PERM_FETCH_STATE === "failed") {
        out.innerHTML = '<div class="tl-note">Could not load the PERM processing-time data (perm_history.json). The other tools on this page still work. Try reloading.</div>';
        return;
      }
      if (PERM_FETCH_STATE !== "ready" || !PERM_CACHE) {
        out.innerHTML = '<p class="help">Loading PERM processing-time data&hellip;</p>';
        return;
      }
      var records = PERM_CACHE;
      if (!records || !records.length) {
        out.innerHTML = '<div class="tl-note">No PERM processing-time data available.</div>';
        return;
      }
      out.innerHTML = permMedianChart(records) + permVolumeChart(records) + PERM_CAVEAT;
    }

    render(); // shows the loading state immediately
    if (PERM_FETCH_STATE === "ready" || PERM_FETCH_STATE === "loading") return;
    PERM_FETCH_STATE = "loading";
    try {
      fetch("perm_history.json").then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (json) {
        PERM_CACHE = json; PERM_FETCH_STATE = "ready"; render();
      })["catch"](function () {
        PERM_FETCH_STATE = "failed"; render();
      });
    } catch (e) {
      PERM_FETCH_STATE = "failed"; render();
    }
  }

  // Floating "back to top" button, injected on every page (app.js loads on all).
  // Appears only after scrolling past a threshold; returns focus to main for a11y.
  function initBackToTop() {
    if (document.getElementById("back-to-top")) return;
    var btn = document.createElement("button");
    btn.id = "back-to-top";
    btn.type = "button";
    btn.className = "back-to-top";
    btn.setAttribute("aria-label", "Back to top");
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg><span class="btt-label">Top</span>';
    btn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
      var main = document.getElementById("maincontent");
      if (main && main.focus) { try { main.focus({ preventScroll: true }); } catch (e) { main.focus(); } }
    });
    document.body.appendChild(btn);
    var shown = false;
    function onScroll() {
      var y = window.pageYOffset || document.documentElement.scrollTop || 0;
      var need = y > 400;
      if (need !== shown) { shown = need; btn.classList.toggle("show", need); }
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ---- Sticky-nav smooth scroll + active-section highlight ----
  function wireHubNav() {
    var navLinks = document.querySelectorAll(".hubnav-links a");
    if (!navLinks.length) return;
    var byId = {};
    var sections = [];
    for (var i = 0; i < navLinks.length; i++) {
      var href = navLinks[i].getAttribute("href") || "";
      if (href.charAt(0) !== "#") continue;
      var id = href.slice(1);
      var sec = document.getElementById(id);
      if (!sec) continue;
      byId[id] = navLinks[i];
      sections.push(sec);
      // Smooth scroll (belt-and-suspenders alongside CSS scroll-margin-top).
      navLinks[i].addEventListener("click", (function (target) {
        return function (e) {
          if (!target) return;
          e.preventDefault();
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          if (window.history && window.history.replaceState) {
            window.history.replaceState(null, "", "#" + target.id);
          }
        };
      })(sec));
    }

    function setActive(id) {
      for (var k = 0; k < navLinks.length; k++) { navLinks[k].classList.remove("active"); }
      if (byId[id]) { byId[id].classList.add("active"); }
    }

    if ("IntersectionObserver" in window) {
      var visible = {};
      var obs = new IntersectionObserver(function (entries) {
        for (var e = 0; e < entries.length; e++) {
          visible[entries[e].target.id] = entries[e].isIntersecting ? entries[e].intersectionRatio : 0;
        }
        // Pick the topmost section that's currently intersecting.
        var bestId = null, bestTop = Infinity;
        for (var s = 0; s < sections.length; s++) {
          if (visible[sections[s].id]) {
            var top = sections[s].getBoundingClientRect().top;
            if (top < bestTop) { bestTop = top; bestId = sections[s].id; }
          }
        }
        if (bestId) { setActive(bestId); }
      }, { rootMargin: "-130px 0px -55% 0px", threshold: [0, 0.25, 0.5, 1] });
      for (var s2 = 0; s2 < sections.length; s2++) { obs.observe(sections[s2]); }
    }
  }

  // ---- Hub init (DOM is ready — this script is at end of body) ----
  // Freshness chip: a persistent "how current is the bulletin data" badge in the
  // disclaimer banner on every page, driven by the rulebook's own verified dates.
  function initFreshnessChip() {
    var rb = window.__RULEBOOK__;
    if (!rb || !rb.meta) return;
    var banner = document.querySelector('.disclaimer-banner');
    if (!banner || banner.querySelector('.freshness-chip')) return;
    var asOf = (rb.bulletin && rb.bulletin.as_of) ? fmtMonth(rb.bulletin.as_of) : '';
    var verified = rb.meta.last_verified ? fmtDate(rb.meta.last_verified) : '';
    var chip = document.createElement('span');
    chip.className = 'freshness-chip';
    chip.setAttribute('title', 'How current the built-in Visa Bulletin data is');
    chip.innerHTML = 'Bulletin data: <strong>' + esc(asOf) + '</strong>' + (verified ? ' · verified ' + esc(verified) : '');
    banner.appendChild(chip);
  }

  // ---- First-visit onboarding tour (homepage only) ----
  // A self-contained stepped intro card over a dim backdrop. No page-element
  // positioning, so it is robust on any layout. Auto-shows only on the homepage
  // and only when the benign UI-preference key 'gc_tour_dismissed' is unset —
  // read/written in try/catch, exactly like the 'gc_theme' theme code. Nothing
  // here is personal data; it is only "has this browser seen the intro."
  function initOnboardingTour() {
    // Homepage marker: .landing-hero exists on index.html only. No-op elsewhere.
    var home = document.querySelector('.landing-hero');
    if (!home) return;
    if (document.querySelector('.gc-tour-overlay')) return; // already built

    // Only the explicit "Don't show this again" button sets this. Skip / Esc /
    // backdrop / finishing just close for now, so the tour auto-shows again on the
    // next visit until the user opts out. (Key bumped from gc_tour_dismissed so the
    // old one-close-persists flag no longer suppresses it.)
    var STORAGE_KEY = 'gc_tour_optout';
    function isDismissed() {
      try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) { return false; }
    }
    function persistDismiss() {
      try { localStorage.setItem(STORAGE_KEY, '1'); } catch (e) {}
    }
    // "Seen" flag: set the first time the tour auto-opens, so a first-time
    // visitor is greeted exactly once and it never auto-opens again after that.
    var SEEN_KEY = 'gc_tour_seen';
    function hasSeen() {
      try { return localStorage.getItem(SEEN_KEY) === '1'; } catch (e) { return false; }
    }
    function markSeen() {
      try { localStorage.setItem(SEEN_KEY, '1'); } catch (e) {}
    }

    var steps = [
      {
        eyebrow: 'Welcome',
        title: 'Green Card Navigator',
        body: 'A plain-language guide to the U.S. employment-based (EB) green card path. It is a personal learning tool, not legal advice, and nothing you enter here is ever saved or transmitted.'
      },
      {
        eyebrow: 'Step 1',
        title: 'Check My Status',
        body: 'New here? Start with "The 5 steps to a green card" on the home page for a plain-English walkthrough. Then Check My Status asks four quick questions (category, work visa, country, priority date) to show where your priority date sits against the current cutoff, plus a historical-pace timeline for your category and country.'
      },
      {
        eyebrow: 'Step 2',
        title: 'Live Tools',
        body: 'Read the current Visa Bulletin, use the timeline scenarios tool and scenario compare, and explore years of History & Trends.'
      },
      {
        eyebrow: 'Step 3',
        title: 'Glossary & Resources',
        body: 'Plain-English definitions for the jargon (EB-1 through EB-5, PERM, priority date) and links to official government sources.'
      }
    ];

    var idx = 0;
    var lastTrigger = null;

    // ---- Build the DOM once ----
    var overlay = document.createElement('div');
    overlay.className = 'gc-tour-overlay';
    overlay.setAttribute('hidden', '');

    var card = document.createElement('div');
    card.className = 'gc-tour-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.setAttribute('aria-labelledby', 'gcTourTitle');
    card.setAttribute('aria-describedby', 'gcTourBody');
    card.setAttribute('tabindex', '-1');

    var skipBtn = document.createElement('button');
    skipBtn.type = 'button';
    skipBtn.className = 'gc-tour-skip';
    skipBtn.innerHTML = 'Skip <span class="gc-tour-x" aria-hidden="true">&times;</span>';
    skipBtn.setAttribute('aria-label', 'Skip the tour');

    var eyebrow = document.createElement('span');
    eyebrow.className = 'gc-tour-eyebrow';

    var title = document.createElement('h2');
    title.className = 'gc-tour-title';
    title.id = 'gcTourTitle';

    var body = document.createElement('p');
    body.className = 'gc-tour-body';
    body.id = 'gcTourBody';

    var progress = document.createElement('div');
    progress.className = 'gc-tour-progress';
    var dots = document.createElement('div');
    dots.className = 'gc-tour-dots';
    dots.setAttribute('aria-hidden', 'true');
    var count = document.createElement('span');
    count.className = 'gc-tour-count';
    var dotEls = [];
    for (var d = 0; d < steps.length; d++) {
      var dot = document.createElement('span');
      dot.className = 'gc-tour-dot';
      dots.appendChild(dot);
      dotEls.push(dot);
    }
    progress.appendChild(dots);
    progress.appendChild(count);

    var controls = document.createElement('div');
    controls.className = 'gc-tour-controls';
    var backBtn = document.createElement('button');
    backBtn.type = 'button';
    backBtn.className = 'gc-tour-btn';
    backBtn.textContent = 'Back';
    var nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'gc-tour-btn gc-tour-primary';
    nextBtn.textContent = 'Next';
    controls.appendChild(backBtn);
    controls.appendChild(nextBtn);

    var footer = document.createElement('div');
    footer.className = 'gc-tour-footer';
    var dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.className = 'gc-tour-dismiss';
    dismissBtn.textContent = "Don't show this again";
    footer.appendChild(dismissBtn);

    card.appendChild(skipBtn);
    card.appendChild(eyebrow);
    card.appendChild(title);
    card.appendChild(body);
    card.appendChild(progress);
    card.appendChild(controls);
    card.appendChild(footer);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    // ---- Rendering ----
    function render() {
      var s = steps[idx];
      eyebrow.textContent = s.eyebrow;
      title.textContent = s.title;
      body.textContent = s.body;
      count.textContent = (idx + 1) + ' of ' + steps.length;
      for (var i = 0; i < dotEls.length; i++) {
        if (i === idx) { dotEls[i].className = 'gc-tour-dot is-active'; }
        else { dotEls[i].className = 'gc-tour-dot'; }
      }
      backBtn.hidden = (idx === 0);
      if (idx === steps.length - 1) { nextBtn.textContent = 'Get started'; }
      else { nextBtn.textContent = 'Next'; }
    }

    // ---- Focus trap ----
    function focusable() {
      return [skipBtn, backBtn.hidden ? null : backBtn, nextBtn, dismissBtn]
        .filter(function (el) { return el; });
    }
    function onKeydown(e) {
      if (e.key === 'Escape' || e.keyCode === 27) {
        e.preventDefault();
        close(false);
        return;
      }
      if (e.key === 'Tab' || e.keyCode === 9) {
        var items = focusable();
        if (!items.length) return;
        var first = items[0];
        var last = items[items.length - 1];
        var active = document.activeElement;
        if (e.shiftKey) {
          if (active === first || !card.contains(active)) { e.preventDefault(); last.focus(); }
        } else {
          if (active === last) { e.preventDefault(); first.focus(); }
        }
      }
    }

    // ---- Open / close ----
    function open(trigger) {
      lastTrigger = trigger || document.activeElement || null;
      idx = 0;
      render();
      overlay.removeAttribute('hidden');
      document.addEventListener('keydown', onKeydown, true);
      // Move focus into the dialog (the card heading region).
      card.focus();
    }
    function close(persist) {
      if (overlay.hasAttribute('hidden')) return;
      overlay.setAttribute('hidden', '');
      document.removeEventListener('keydown', onKeydown, true);
      if (persist) { persistDismiss(); }
      if (lastTrigger && typeof lastTrigger.focus === 'function') {
        lastTrigger.focus();
      }
      // Safety: never leave focus trapped inside the now-hidden card (e.g. if the
      // trigger was a non-focusable element like the hero header on auto-open).
      if (card.contains(document.activeElement)) {
        try { document.activeElement.blur(); } catch (e) {}
      }
      lastTrigger = null;
    }

    // ---- Wiring ----
    nextBtn.addEventListener('click', function () {
      if (idx < steps.length - 1) { idx++; render(); nextBtn.focus(); }
      else { close(false); } // finishing just closes; shows again next visit
    });
    backBtn.addEventListener('click', function () {
      if (idx > 0) { idx--; render(); nextBtn.focus(); }
    });
    skipBtn.addEventListener('click', function () { close(false); }); // skip = close for now, not opt-out
    dismissBtn.addEventListener('click', function () { close(true); }); // the ONLY control that persists opt-out
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) { close(false); } // backdrop click = close for now
    });

    // Re-open affordance: always shows the tour, regardless of the flag.
    var reopen = document.getElementById('tourReopen');
    if (reopen) {
      reopen.addEventListener('click', function () { open(reopen); });
    }

    // ---- Auto-open behavior (EDIT THIS BLOCK to change how the tour behaves) ----
    // CURRENT: auto-open ONCE for a first-time visitor, then never nag again.
    //   It opens only if the visitor hasn't opted out AND hasn't seen it before,
    //   then marks it "seen" so it won't auto-open on future visits.
    // To auto-open on EVERY visit until "Don't show this again" is clicked, use:
    //     if (!isDismissed()) { open(reopen || home); }
    // To DISABLE auto-open entirely (button-only), delete this whole block.
    // The "Take a quick tour" button always opens it regardless of these flags.
    if (!isDismissed() && !hasSeen()) {
      markSeen();
      open(reopen || home);
    }
  }

  renderProcessExplainer();
  populateHubStatics();
  initFreshnessChip();
  initStandaloneTools(); // Live tools page: interactive parsers (no-op elsewhere)
  renderH1bChecklist(); // Live tools page: interactive H-1B process checklist (no-op elsewhere)
  renderJobChangeChecker(); // Live tools page: job/location change impact checker (no-op elsewhere)
  initStandaloneProjector(); // Live tools page: standalone projector + compare (no-op elsewhere)
  initHistoryTrends(); // Live tools page: History & Trends charts from vb_history.json (no-op elsewhere)
  initDolQueue();      // Live tools page: current DOL queue position from dol_queue.json (no-op elsewhere)
  initPermHistory(); // Live tools page: PERM Processing Time charts from perm_history.json (no-op elsewhere)
  wireToolIndex(); // Live tools page: jump-to-tool index (no-op elsewhere)
  wireHubNav();
  initBackToTop(); // Floating back-to-top button on every page
  initOnboardingTour(); // First-visit intro tour (homepage only; no-op elsewhere)
  loadCommunitySnapshot(); // populate the standalone #community section on load

})();

/* ========================== THEME TOGGLE IIFE ========================= */
  // ---- Theme toggle (Light / Dark / System) ----
  // Kept separate from the main app IIFE so it always works even if the
  // rulebook fails to parse. Persists only the preference key 'gc_theme'.
  (function () {
    "use strict";
    var root = document.documentElement;
    var buttons = Array.prototype.slice.call(document.querySelectorAll('.theme-toggle button'));
    var mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function readPref() {
      try { return localStorage.getItem('gc_theme') || 'system'; }
      catch (e) { return 'system'; }
    }
    function effectiveOf(pref) {
      if (pref === 'system') return (mql && mql.matches) ? 'dark' : 'light';
      return pref;
    }
    function apply(pref, save) {
      root.setAttribute('data-theme', effectiveOf(pref));
      if (save) { try { localStorage.setItem('gc_theme', pref); } catch (e) {} }
      buttons.forEach(function (b) {
        b.setAttribute('aria-pressed', String(b.getAttribute('data-theme-pref') === pref));
      });
    }

    buttons.forEach(function (b) {
      b.addEventListener('click', function () {
        apply(b.getAttribute('data-theme-pref'), true);
      });
    });

    // When on "system", follow live OS changes.
    if (mql) {
      var onChange = function () { if (readPref() === 'system') apply('system', false); };
      if (mql.addEventListener) mql.addEventListener('change', onChange);
      else if (mql.addListener) mql.addListener(onChange);  // older Safari
    }

    // Sync the control to the already-applied (pre-paint) preference.
    apply(readPref(), false);
  })();

/* =========================== EASTER EGG IIFE ========================== */
/* Easter egg: click the little passport in the header and a few of them rain
   down for ~3s, then clean themselves up. Independent of the main app IIFE so a
   rulebook parse failure can't disable it. Respects reduced-motion; zero layout
   impact (nodes are position:fixed and removed on animationend). */
(function () {
  "use strict";
  var btn = document.getElementById("eggBtn");
  if (!btn) return;

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  var running = false;

  btn.addEventListener("click", function () {
    if (running) return;
    if (reduce && reduce.matches) {
      // Honor reduced-motion: a tiny non-animated acknowledgement, no rain.
      btn.animate
        ? btn.animate([{ opacity: 1 }, { opacity: 0.5 }, { opacity: 1 }], { duration: 400 })
        : null;
      return;
    }
    running = true;

    var emoji = btn.textContent.trim() || "🛂";
    var COUNT = 14;
    var maxLife = 0;

    for (var i = 0; i < COUNT; i++) {
      var span = document.createElement("span");
      span.className = "egg-fall";
      span.textContent = emoji;
      span.setAttribute("aria-hidden", "true");
      span.style.left = (Math.random() * 96 + 2) + "vw";
      span.style.fontSize = (Math.random() * 18 + 20) + "px";
      var delay = Math.random() * 900;                 // ms, staggered start
      var dur = Math.random() * 1200 + 2000;           // 2.0s - 3.2s fall
      span.style.animationDelay = delay + "ms";
      span.style.animationDuration = dur + "ms";
      maxLife = Math.max(maxLife, delay + dur);
      (function (node) {
        node.addEventListener("animationend", function () {
          if (node.parentNode) node.parentNode.removeChild(node);
        });
      })(span);
      document.body.appendChild(span);
    }

    // Safety net: guarantee cleanup + re-arm even if animationend doesn't fire.
    window.setTimeout(function () {
      var leftovers = document.querySelectorAll(".egg-fall");
      for (var j = 0; j < leftovers.length; j++) {
        if (leftovers[j].parentNode) leftovers[j].parentNode.removeChild(leftovers[j]);
      }
      running = false;
    }, maxLife + 300);
  });
})();

/* ===================== PATHS PAGE (paths.html only) ===================== */
/* Self-contained and guarded so it is a no-op on every other page. Adds three
   things: smooth in-page scrolling for the "On this page" table of contents,
   a lightweight scroll-spy that highlights the current section, and a live
   EB-1 versus EB-2 comparison read from vb_history.json. Fails safe: if the
   fetch or parse fails, the static fallback text already in the callout stays. */
(function () {
  "use strict";
  if (!document.body || document.body.className.indexOf("paths-page") === -1) return;

  // Smooth scrolling, scoped to this page only.
  try { document.documentElement.style.scrollBehavior = "smooth"; } catch (e) {}

  // ---- Table-of-contents scroll-spy ----
  // Handles both the flat index used by the path pages and the two-level index
  // on the FAQ (section, then that section's questions). The section highlight
  // and the question highlight are tracked separately, so a question lighting
  // up never steals the section's highlight.
  (function () {
    var links = Array.prototype.slice.call(document.querySelectorAll(".paths-toc nav a"));
    if (!links.length) return;

    function resolve(sel) {
      return Array.prototype.slice.call(document.querySelectorAll(sel)).map(function (a) {
        var id = (a.getAttribute("href") || "").slice(1);
        return { a: a, el: document.getElementById(id) };
      }).filter(function (t) { return t.el; });
    }
    // On a flat index every link is a section link.
    var secs = resolve(".paths-toc nav a.toc-sec");
    if (!secs.length) secs = resolve(".paths-toc nav a");
    var qs = resolve(".paths-toc nav a.toc-q");
    if (!secs.length) return;

    // Document-relative top. offsetTop is measured from the offsetParent, which
    // on these pages is .paths-content, so it under-reports and the highlight
    // drifts. A collapsed section reports a small height, which is fine here.
    function topOf(el) { return el.getBoundingClientRect().top + window.scrollY; }

    function lastAbove(list, y) {
      var cur = null;
      for (var i = 0; i < list.length; i++) if (topOf(list[i].el) <= y) cur = list[i];
      return cur;
    }

    function onScroll() {
      var y = window.scrollY + 130;
      var curSec = lastAbove(secs, y) || secs[0];
      // A short final section can never reach the 130px line, because there is
      // not enough page left to scroll it up that far. Without this the last
      // entry never lights up and the previous one stays stuck highlighted.
      var docH = document.documentElement.scrollHeight;
      var atBottom = window.innerHeight + window.scrollY >= docH - 4;
      if (atBottom) curSec = secs[secs.length - 1];

      links.forEach(function (a) { a.classList.remove("toc-active"); });
      if (curSec) curSec.a.classList.add("toc-active");

      // Expand only the section being read, and mark the question inside it.
      var groups = document.querySelectorAll(".paths-toc nav .toc-group");
      if (groups.length && curSec) {
        var activeGroup = curSec.a.closest(".toc-group");
        Array.prototype.forEach.call(groups, function (g) {
          g.classList.toggle("is-active", g === activeGroup);
        });
        if (activeGroup && qs.length) {
          var mine = qs.filter(function (q) { return activeGroup.contains(q.a); });
          var curQ = lastAbove(mine, y);
          if (atBottom && mine.length) curQ = mine[mine.length - 1];
          if (curQ) curQ.a.classList.add("toc-active");
        }
      }
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    // A section collapsing or expanding changes every position below it.
    document.addEventListener("toggle", function (e) {
      if (e.target && e.target.tagName === "DETAILS") onScroll();
    }, true);
    onScroll();
  })();

  // ---- Live EB-1 vs EB-2 comparison from vb_history.json ----
  var box = document.getElementById("niw-bulletin-callout");
  if (!box) return;
  var MON_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var MON_LONG = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  fetch("vb_history.json").then(function (r) { return r.json(); }).then(function (data) {
    function newest(key) { var a = data[key]; return (a && a.length) ? a[a.length - 1] : null; }
    function rank(v) {
      if (v === "CURRENT") return Infinity;
      if (v == null) return -Infinity;
      var p = String(v).split("-");
      var y = parseInt(p[0], 10), m = parseInt(p[1] || "1", 10), d = parseInt(p[2] || "1", 10);
      if (isNaN(y)) return -Infinity;
      return Date.UTC(y, m - 1, d);
    }
    function label(v) {
      if (v === "CURRENT") return "Current";
      if (v == null) return "Unavailable";
      var p = String(v).split("-");
      var mi = parseInt(p[1], 10) - 1;
      return (MON_SHORT[mi] || "") + " " + p[0];
    }
    function pick(rec) {
      if (!rec) return null;
      // Always report the Final Action Date. If it is unavailable (null), say
      // "Unavailable" outright rather than falling back to the Dates for Filing.
      return { v: rec.fad, which: "final action date" };
    }
    function line(country) {
      var e1 = newest("EB-1|" + country), e2 = newest("EB-2|" + country);
      if (!e1 || !e2) return "";
      var p1 = pick(e1), p2 = pick(e2);
      var mp = (e1.month || e2.month || "").split("-");
      var monthLabel = mp.length >= 2 ? ((MON_LONG[parseInt(mp[1], 10) - 1] || "") + " " + mp[0]) : "the latest";
      var ahead;
      if (rank(p1.v) > rank(p2.v)) ahead = "EB-1 is currently ahead of EB-2 for " + country + ", which points to a shorter wait through EB-1A for anyone who can meet its higher bar";
      else if (rank(p2.v) > rank(p1.v)) ahead = "EB-2 is currently ahead of EB-1 for " + country;
      else ahead = "EB-1 and EB-2 are about even for " + country + " right now";
      var note = (p1.which !== "final action date" || p2.which !== "final action date")
        ? " (shown on dates for filing where a final action date was not published)" : "";
      return "For someone born in " + country + ", as of the " + monthLabel + " Visa Bulletin, EB-1 shows " +
        label(p1.v) + " and EB-2 shows " + label(p2.v) + ". " + ahead + note + ".";
    }
    var india = line("India"), china = line("China");
    if (!india && !china) return; // keep the static fallback already in the box
    var html = "<strong>EB-1 versus EB-2 right now.</strong> ";
    if (india) html += india + " ";
    if (china) html += china + " ";
    html += "These positions change every month, so always check the current " +
      '<a href="https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html" target="_blank" rel="noopener noreferrer">Visa Bulletin</a>' +
      ', and see the <a href="tools.html#tools-history">History and Trends charts</a> for how the two lines have moved over time.';
    box.innerHTML = html;
    box.removeAttribute("data-fallback");
  }).catch(function () { /* keep the static fallback text in the box */ });
})();

/* ==================== MOBILE NAV + DISCLAIMER CHIP (Phase 1) ==================== */
/* Self-contained IIFE, independent of the main app IIFE, so it runs on every
   page. It (A) injects a bottom tab bar + a "More" bottom-sheet drawer, (B)
   collapses the disclaimer banner to a short strip with a Show more/Show less
   toggle, and (D) keeps the active Paths chip centered in the mobile chip strip.
   All of it is inert on desktop: the injected chrome is display:none above 767px
   via the stylesheet, and the disclaimer collapse only clamps inside that media
   query. Labels mirror the existing top navigation verbatim (plus "Home" and
   "More" for the two new affordances); no existing copy is reworded. */
(function () {
  "use strict";
  var doc = document;
  if (!doc.body || doc.getElementById("m-drawer")) return; // guard double-inject

  // Inline icons (stroke = currentColor, 24x24) so they recolor with the theme.
  var W = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
  var ICON = {
    home:  '<svg ' + W + '><path d="M4 11 12 4l8 7"/><path d="M6 9.5V20h12V9.5"/></svg>',
    check: '<svg ' + W + '><rect x="5.5" y="4.5" width="13" height="16" rx="2"/><path d="M9 4.5h6v2.6H9z"/><path d="M9 12.5l2 2 4-4"/></svg>',
    paths: '<svg ' + W + '><path d="M9 4 3.5 6v13.5L9 17.5l6 2 5.5-2V4L15 6 9 4Z"/><path d="M9 4v13.5M15 6v13.5"/></svg>',
    tools: '<svg ' + W + '><path d="M5 21v-6M5 11V3M12 21v-8M12 9V3M19 21v-4M19 13V3"/><circle cx="5" cy="13" r="1.8"/><circle cx="12" cy="7" r="1.8"/><circle cx="19" cy="15" r="1.8"/></svg>',
    more:  '<svg ' + W + '><rect x="4" y="4" width="6.5" height="6.5" rx="1.4"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.4"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.4"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.4"/></svg>',
    close: '<svg ' + W + '><path d="M6 6l12 12M18 6 6 18"/></svg>'
  };

  var page = (location.pathname.split("/").pop() || "").toLowerCase();
  if (page === "") page = "index.html";

  // Primary bottom-bar destinations. Labels match the top nav; "Home" is the
  // index tab (on desktop the brand logo is home). "EB Paths" opens the first
  // guide (eb1a.html) and stays highlighted across all six guide pages.
  var PRIMARY = [
    { label: "Home",            href: "index.html",  icon: "home",  match: "index.html" },
    { label: "Check My Status", href: "status.html", icon: "check", match: "status.html" },
    { label: "EB Paths",           href: "eb1a.html",   icon: "paths", match: ["eb1a.html", "eb1b.html", "eb1c.html", "eb2.html", "eb3.html", "paths.html"] },
    { label: "Tools",           href: "tools.html",  icon: "tools", match: "tools.html" }
  ];
  // Overflow destinations, live in the "More" drawer. FAQ is a visible tab on
  // desktop but lives here on mobile: the bottom bar is capped at 4 + More, and
  // adding a 6th slot crowds the labels below legibility on a 390px screen.
  var MORE = [
    { label: "FAQ",       href: "faq.html" },
    { label: "Glossary",  href: "glossary.html" },
    // niw-appeals.html was in NEITHER array, so below 768px - where .hubnav-links is
    // display:none - it was reachable only from the footer. A page absent from both
    // nav arrays is effectively unreachable on a phone.
    { label: "NIW Appeals", href: "niw-appeals.html" },
    { label: "Resources", href: "resources.html" },
    { label: "About",     href: "about.html" },
    { label: "Privacy",   href: "privacy.html" }
  ];
  var isMorePage = MORE.some(function (m) { return m.href === page; });

  function el(tag, cls, attrs) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) { for (var k in attrs) { if (attrs.hasOwnProperty(k)) e.setAttribute(k, attrs[k]); } }
    return e;
  }

  // ---- A1: bottom tab bar ----
  var bar = el("nav", "m-tabbar", { "aria-label": "Primary" });
  PRIMARY.forEach(function (item) {
    var a = el("a", "m-tab", { href: item.href });
    a.innerHTML = ICON[item.icon] + '<span class="m-tab-label"></span>';
    a.querySelector(".m-tab-label").textContent = item.label;
    var matchHit = Array.isArray(item.match) ? item.match.indexOf(page) !== -1 : item.match === page;
    if (matchHit) { a.setAttribute("aria-current", "page"); a.classList.add("is-active"); }
    bar.appendChild(a);
  });
  var moreBtn = el("button", "m-tab", { type: "button", "aria-expanded": "false", "aria-controls": "m-drawer", "aria-haspopup": "dialog" });
  moreBtn.innerHTML = ICON.more + '<span class="m-tab-label"></span>';
  moreBtn.querySelector(".m-tab-label").textContent = "More";
  if (isMorePage) moreBtn.classList.add("is-active");
  bar.appendChild(moreBtn);
  doc.body.appendChild(bar);

  // ---- A2: More drawer (bottom sheet) ----
  var backdrop = el("div", "m-drawer-backdrop");
  var drawer = el("div", "m-drawer", { id: "m-drawer", role: "dialog", "aria-modal": "true", "aria-label": "More pages", "aria-hidden": "true" });
  var grip = el("div", "m-drawer-grip", { "aria-hidden": "true" });
  var head = el("div", "m-drawer-head");
  var title = el("span", "m-drawer-title"); title.textContent = "More";
  var closeBtn = el("button", "m-drawer-close", { type: "button", "aria-label": "Close menu" });
  closeBtn.innerHTML = ICON.close;
  head.appendChild(title); head.appendChild(closeBtn);
  var dnav = el("nav", "m-drawer-nav", { "aria-label": "More pages" });
  MORE.forEach(function (m) {
    var a = el("a", null, { href: m.href });
    a.textContent = m.label;
    if (m.href === page) a.setAttribute("aria-current", "page");
    a.addEventListener("click", function () { closeDrawer(); });
    dnav.appendChild(a);
  });
  drawer.appendChild(grip); drawer.appendChild(head); drawer.appendChild(dnav);
  doc.body.appendChild(backdrop); doc.body.appendChild(drawer);

  var lastFocus = null;
  function openDrawer() {
    lastFocus = doc.activeElement;
    backdrop.classList.add("open");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    moreBtn.setAttribute("aria-expanded", "true");
    doc.body.style.overflow = "hidden";
    doc.addEventListener("keydown", onKey);
    // Defer focus: the sheet is visibility:hidden at the first frame of the
    // open transition, so focus() must wait until it is focusable.
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        var first = drawer.querySelector(".m-drawer-nav a");
        if (first) { try { first.focus(); } catch (e) {} }
      });
    });
  }
  function closeDrawer() {
    backdrop.classList.remove("open");
    drawer.classList.remove("open");
    moreBtn.setAttribute("aria-expanded", "false");
    doc.body.style.overflow = "";
    doc.removeEventListener("keydown", onKey);
    // Return focus to the trigger BEFORE hiding the drawer, so aria-hidden is never
    // set while a descendant still holds focus (avoids a Chrome accessibility warning).
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
    drawer.setAttribute("aria-hidden", "true");
  }
  function onKey(e) {
    if (e.key === "Escape" || e.keyCode === 27) { e.preventDefault(); closeDrawer(); return; }
    if (e.key === "Tab") {
      var f = drawer.querySelectorAll("a[href], button");
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }
  moreBtn.addEventListener("click", function () {
    if (drawer.classList.contains("open")) closeDrawer(); else openDrawer();
  });
  closeBtn.addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);

  // ---- B: disclaimer collapses to a short strip on phones ----
  (function () {
    var banner = doc.querySelector(".disclaimer-banner");
    if (!banner) return;
    var textEl = banner.querySelector("span:not(.icon)");
    if (!textEl) return;
    textEl.classList.add("disclaimer-text");
    var KEY = "gc_disclaimer_collapsed";
    var collapsed = true; // default: collapsed (still shows "Not legal advice")
    try { if (localStorage.getItem(KEY) === "0") collapsed = false; } catch (e) {}

    var toggle = el("button", "disclaimer-toggle", { type: "button" });
    var tlabel = el("span", "dt-label");
    toggle.appendChild(tlabel);
    if (textEl.nextSibling) banner.insertBefore(toggle, textEl.nextSibling);
    else banner.appendChild(toggle);

    function render() {
      if (collapsed) {
        banner.classList.add("is-collapsed");
        tlabel.textContent = "Show more";
        toggle.setAttribute("aria-expanded", "false");
      } else {
        banner.classList.remove("is-collapsed");
        tlabel.textContent = "Show less";
        toggle.setAttribute("aria-expanded", "true");
      }
    }
    toggle.addEventListener("click", function () {
      collapsed = !collapsed;
      try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
      render();
    });
    render();
  })();

  // ---- D: the in-page section index becomes a bottom-sheet jump menu on phones ----
  // One uniform pattern for every page that has a section index: Paths (.paths-toc)
  // and Live Tools (.tool-index). Tapping the sticky bar opens the same style of
  // bottom sheet as the More menu.
  (function () {
    var toc = doc.querySelector(".paths-toc") || doc.querySelector(".tool-index");
    if (!toc) return;
    var anchorHost = toc.matches("nav") ? toc : toc.querySelector("nav");
    if (!anchorHost) return;
    var anchors = [].slice.call(anchorHost.querySelectorAll("a"));
    if (!anchors.length) return;

    var sections = anchors.map(function (a) {
      var strong = a.querySelector("strong");
      return { href: a.getAttribute("href") || "", label: ((strong ? strong.textContent : a.textContent) || "").trim() };
    });

    // Trigger bar: shows the current section, opens the sheet.
    var trigger = doc.createElement("button");
    trigger.type = "button";
    trigger.className = "paths-jump";
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", "paths-sheet");
    var lab = doc.createElement("span");
    lab.className = "paths-jump-label";
    lab.appendChild(doc.createTextNode("On this page: "));
    var labB = doc.createElement("b");
    labB.textContent = sections[0].label;
    lab.appendChild(labB);
    var chev = doc.createElement("span");
    chev.className = "paths-jump-chev";
    chev.setAttribute("aria-hidden", "true");
    chev.textContent = "▾";
    trigger.appendChild(lab);
    trigger.appendChild(chev);
    toc.parentNode.insertBefore(trigger, toc.nextSibling);

    // Backdrop + sheet, reusing the More-drawer styling for consistency.
    var backdrop = doc.createElement("div");
    backdrop.className = "m-drawer-backdrop";
    var sheet = doc.createElement("div");
    sheet.className = "m-drawer";
    sheet.id = "paths-sheet";
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-label", "Jump to section");
    sheet.setAttribute("aria-hidden", "true");
    var grip = doc.createElement("div"); grip.className = "m-drawer-grip";
    var head = doc.createElement("div"); head.className = "m-drawer-head";
    var title = doc.createElement("span"); title.className = "m-drawer-title"; title.textContent = "On this page";
    var closeBtn = doc.createElement("button"); closeBtn.type = "button"; closeBtn.className = "m-drawer-close"; closeBtn.setAttribute("aria-label", "Close");
    closeBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
    head.appendChild(title); head.appendChild(closeBtn);
    var list = doc.createElement("nav"); list.className = "m-drawer-nav";
    sheet.appendChild(grip); sheet.appendChild(head); sheet.appendChild(list);
    doc.body.appendChild(backdrop);
    doc.body.appendChild(sheet);

    function setActive(i) {
      labB.textContent = sections[i].label;
      var rows = list.querySelectorAll("a");
      for (var r = 0; r < rows.length; r++) {
        if (r === i) rows[r].setAttribute("aria-current", "page");
        else rows[r].removeAttribute("aria-current");
      }
    }

    sections.forEach(function (s, i) {
      var a = doc.createElement("a");
      a.href = s.href;
      a.textContent = s.label;
      if (i === 0) a.setAttribute("aria-current", "page");
      a.addEventListener("click", function () { setActive(i); close(); });
      list.appendChild(a);
    });

    var lastFocus = null;
    function onKey(e) { if (e.key === "Escape" || e.keyCode === 27) { e.preventDefault(); close(); } }
    function open() {
      lastFocus = doc.activeElement;
      backdrop.classList.add("open");
      sheet.classList.add("open");
      sheet.setAttribute("aria-hidden", "false");
      trigger.setAttribute("aria-expanded", "true");
      doc.body.style.overflow = "hidden";
      doc.addEventListener("keydown", onKey);
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          var cur = list.querySelector('a[aria-current="page"]') || list.querySelector("a");
          if (cur) { try { cur.focus({ preventScroll: true }); } catch (e) {} }
        });
      });
    }
    function close() {
      backdrop.classList.remove("open");
      sheet.classList.remove("open");
      trigger.setAttribute("aria-expanded", "false");
      doc.body.style.overflow = "";
      doc.removeEventListener("keydown", onKey);
      if (lastFocus && lastFocus.focus) { try { lastFocus.focus({ preventScroll: true }); } catch (e) {} }
      sheet.setAttribute("aria-hidden", "true");
    }
    trigger.addEventListener("click", function () { if (sheet.classList.contains("open")) close(); else open(); });
    closeBtn.addEventListener("click", close);
    backdrop.addEventListener("click", close);

    // Scroll-spy: reflect the section currently at the top of the reading area.
    // The active section is the last one whose top has scrolled to or above the
    // sticky bar (about 80px from the viewport top).
    var secEls = sections.map(function (s) { return doc.getElementById(s.href.replace("#", "")); });
    var spyPending = false;
    function currentIndex() {
      var idx = 0;
      for (var i = 0; i < secEls.length; i++) {
        if (secEls[i] && secEls[i].getBoundingClientRect().top <= 80) idx = i;
      }
      return idx;
    }
    function spy() { spyPending = false; setActive(currentIndex()); }
    window.addEventListener("scroll", function () {
      if (!spyPending) { spyPending = true; window.requestAnimationFrame(spy); }
    }, { passive: true });
    spy();
  })();

})();

/* ==================== DESKTOP TOP-NAV OVERFLOW ("Learn") MENU ==================== */
/* Desktop-only (min-width: 768px). Collapses the two secondary top-nav links
   (Glossary, Resources) into a single "Learn" button that opens a dropdown, so
   the nav row stays compact and the reading material reads as a shelf. Injected here
   (rather than hand-edited into nine pages) so every page gets it identically.
   The button + panel are appended INSIDE #hubnav-links, which the stylesheet sets
   to display:none below 768px, so this chrome never appears on phones. The mobile
   bottom tab bar + More drawer are injected by a separate IIFE above and are NOT
   touched here (that IIFE builds its own hardcoded destination lists from
   location.pathname, so moving these <a> nodes does not affect it). */
(function () {
  "use strict";
  function init() {
    var doc = document;
    var links = doc.getElementById("hubnav-links");
    if (!links || doc.getElementById("hubnav-more-btn")) return; // guard double-inject

    // Secondary destinations, in top-nav order. Mirrors the mobile More drawer.
    // "appeals" rides in the Learn dropdown rather than as a 6th visible chip: the
    // row is already tight at 5 + Learn, but the page still needs a desktop entry
    // point. Without one its only link on most pages was the footer.
    // "decisions" rides here for the same reason "appeals" does, and so that the two
    // NIW data pages sit together under Learn. Without a topbar entry of its own,
    // niw-decisions.html showed Learn > NIW Appeals as the active trail, which is the
    // wrong parent for a page that is also its own tab in the EB Paths strip.
    var SECONDARY = ["glossary", "guide", "appeals", "decisions", "resources"];
    var moved = [];
    SECONDARY.forEach(function (nav) {
      var a = links.querySelector('a[data-nav="' + nav + '"]');
      if (a) moved.push(a);
    });
    if (!moved.length) return;

    // Is the current page one of the secondary items? The active link is marked
    // in each page's HTML with class "active" / aria-current="page".
    var activeInMore = moved.some(function (a) {
      return a.classList.contains("active") || a.getAttribute("aria-current") === "page";
    });

    // ---- "More" button + caret ----
    var wrap = doc.createElement("div");
    wrap.className = "hubnav-more";

    var btn = doc.createElement("button");
    btn.type = "button";
    btn.id = "hubnav-more-btn";
    btn.className = "hubnav-more-btn" + (activeInMore ? " active" : "");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-haspopup", "true");
    btn.setAttribute("aria-controls", "hubnav-more-panel");
    var label = doc.createElement("span");
    label.textContent = "Learn";
    var caret = doc.createElement("span");
    caret.className = "hubnav-more-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
    btn.appendChild(label);
    btn.appendChild(caret);

    // ---- dropdown panel (moves the five <a> nodes into it) ----
    var panel = doc.createElement("div");
    panel.id = "hubnav-more-panel";
    panel.className = "hubnav-more-panel";
    panel.setAttribute("aria-label", "More pages");
    moved.forEach(function (a) { panel.appendChild(a); });

    wrap.appendChild(btn);
    wrap.appendChild(panel);
    links.appendChild(wrap); // stays inside #hubnav-links -> inherits mobile display:none

    function isOpen() { return wrap.classList.contains("open"); }
    function open() {
      wrap.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      doc.addEventListener("keydown", onKey, true);
      doc.addEventListener("click", onDocClick, true);
      var first = panel.querySelector("a");
      if (first) { try { first.focus(); } catch (e) {} }
    }
    function close(refocus) {
      if (!isOpen()) return;
      wrap.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
      doc.removeEventListener("keydown", onKey, true);
      doc.removeEventListener("click", onDocClick, true);
      if (refocus) { try { btn.focus(); } catch (e) {} }
    }
    function onKey(e) {
      if (e.key === "Escape" || e.keyCode === 27) { e.preventDefault(); close(true); }
    }
    function onDocClick(e) {
      if (!wrap.contains(e.target)) close(false);
    }

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (isOpen()) close(true); else open();
    });
    // A chosen link navigates away; close cleanly for any same-page case too.
    panel.addEventListener("click", function (e) {
      if (e.target && e.target.closest && e.target.closest("a")) close(false);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

/* =========================================================================
   LIVE TOOLS: one-tool-at-a-time tabs (tools.html only)
   The .tool-switch bar shows a single tool section at a time, like the EB
   Paths tab strip. Panels render as scalable SVG, so hiding inactive ones with
   display:none is safe (charts scale via viewBox when shown). This runs
   synchronously at end of <body>, before the chart init on DOMContentLoaded,
   and only sets data-tooltabs="on" once the tabs are actually wired — so with
   JS off every tool simply stacks and stays reachable (no regression).
   ========================================================================= */
(function () {
  var bar = document.querySelector(".tool-switch");
  if (!bar) return;
  var panels = [].slice.call(document.querySelectorAll(".tool-panel"));
  if (!panels.length) return;
  var tabs = [].slice.call(bar.querySelectorAll("button[data-tool-target]"));
  if (!tabs.length) return;
  var host = document.getElementById("maincontent") || document.body;

  function activate(id, updateHash) {
    if (!panels.some(function (p) { return p.id === id; })) id = panels[0].id;
    panels.forEach(function (p) { p.classList.toggle("tool-panel--active", p.id === id); });
    tabs.forEach(function (t) {
      var on = t.getAttribute("data-tool-target") === id;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    if (updateHash && window.history && window.history.replaceState) {
      try { window.history.replaceState(null, "", "#" + id); } catch (e) {}
    }
  }

  // Enable panel hiding now that the tabs are confirmed present and wired.
  host.setAttribute("data-tooltabs", "on");

  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      activate(t.getAttribute("data-tool-target"), true);
      window.scrollTo({ top: 0 });
    });
    t.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      var i = tabs.indexOf(t);
      var n = e.key === "ArrowRight" ? (i + 1) % tabs.length : (i - 1 + tabs.length) % tabs.length;
      tabs[n].focus();
      activate(tabs[n].getAttribute("data-tool-target"), true);
    });
  });

  // Deep links from other pages (e.g. tools.html#tools-history) and any in-page
  // hash change activate the matching tab.
  window.addEventListener("hashchange", function () {
    var id = (location.hash || "").slice(1);
    var el = id && document.getElementById(id);
    if (el && el.classList.contains("tool-panel")) activate(id, false);
  });

  var initial = (location.hash || "").slice(1);
  activate(panels.some(function (p) { return p.id === initial; }) ? initial : panels[0].id, false);
})();

// ============================================================================
// Site-wide acronym glossary tooltips.
// Feedback (Conor A.): "I don't even know what H-1B, L-1, O-1, F-1 mean… a
// hover tooltip site-wide for acronym explanations with links out to the Learn
// section could be useful." This wraps the FIRST occurrence of each known
// acronym in body prose (p / li / dd only) with a subtly-underlined link:
// hovering shows a one-line definition (native title), clicking jumps to the
// matching Glossary entry. It skips the Glossary page itself, form controls,
// code, headings, existing links, and the questionnaire option cards, so it
// can't break layout or double-wrap. Definitions mirror glossary.html.
// ============================================================================
(function () {
  "use strict";
  // [term, one-line definition, glossary group anchor]. Longest terms FIRST so
  // "STEM OPT" wins over "OPT", "EB-2 NIW" over "EB-2", etc.
  var TERMS = [
    // --- multi-word terms first (longest wins in the regex alternation) ---
    ["labor condition application", "The employer's wage and working-conditions filing with the Department of Labor (Form ETA-9035).", "gc-process"],
    ["automatic revalidation", "A narrow rule letting some people re-enter on an expired visa after a short trip to Canada or Mexico.", "gc-process"],
    ["duration of status", "Admission for as long as you keep studying, rather than to a fixed end date.", "gc-work"],
    ["consular processing", "Getting your visa at a U.S. consulate abroad instead of changing status inside the U.S.", "gc-process"],
    ["extension of stay", "Asking to stay longer in the status you already hold.", "gc-process"],
    ["change of status", "Switching from one nonimmigrant status to another without leaving the U.S.", "gc-process"],
    ["receipt notice", "The notice confirming USCIS received your filing. It is not an approval.", "gc-process"],
    ["Visa Bulletin", "The monthly State Department chart showing which priority dates can move forward.", "gc-process"],
    ["portability", "Starting a new job as soon as the petition is filed, before it is approved.", "gc-process"],
    ["wage level", "One of four pay tiers, I to IV, set for a job in a given area. Drives your H-1B lottery odds.", "gc-process"],
    ["cap-gap", "Keeps F-1 status and OPT alive while a timely-filed H-1B change of status is pending.", "gc-process"],
    // --- forms and codes. H-1B1 before H-1B, I-94 before I-9, or the shorter
    //     term would try to match inside the longer one. ---
    ["ETA-9035", "The Labor Condition Application form an employer files before an H-1B petition.", "gc-process"],
    ["DS-2019", "The certificate of eligibility your program sponsor issues for J-1 status.", "gc-work"],
    ["I-797C", "Notice of Action: the receipt USCIS sends when it takes a filing. Not an approval.", "gc-process"],
    ["DS-160", "The online form used to apply for a U.S. visa at a consulate.", "gc-process"],
    ["H-1B1", "A separate work visa for nationals of Chile and Singapore, outside the H-1B lottery.", "gc-work"],
    ["I-129", "The petition an employer files to get you a work visa such as H-1B or L-1.", "gc-process"],
    ["I-765", "The application for a work permit (EAD).", "gc-process"],
    ["I-94", "Your arrival record. The 'admit until' date on it is how long you may stay.", "gc-process"],
    ["I-20", "The certificate of eligibility your school issues for F-1 status.", "gc-work"],
    ["I-9", "The form your employer completes to verify your identity and right to work.", "gc-process"],
    ["H-4", "Dependent status for the spouse and children of an H-1B holder. No work permission by itself.", "gc-work"],
    ["L-2", "Dependent status for the spouse and children of an L-1 holder. The spouse may work.", "gc-work"],
    ["EAD", "Employment Authorization Document: the physical work-permit card.", "gc-process"],
    ["TN", "USMCA professional status for Canadian and Mexican citizens.", "gc-work"],
    ["STEM OPT", "A 24-month work-authorization extension after OPT for STEM graduates.", "gc-work"],
    ["EB-2 NIW", "EB-2 National Interest Waiver: a self-petition that waives the job offer and PERM.", "gc-eb"],
    ["ETA 9089", "The PERM labor-certification form filed with the Department of Labor.", "gc-process"],
    ["EB-1A", "EB-1 for individuals of extraordinary ability (self-petition, no employer).", "gc-eb"],
    ["EB-1B", "EB-1 for outstanding researchers and professors (employer-sponsored).", "gc-eb"],
    ["EB-1C", "EB-1 for multinational managers and executives (employer-sponsored).", "gc-eb"],
    ["L-1A", "Intracompany transfer visa for managers/executives (7-year max).", "gc-work"],
    ["L-1B", "Intracompany transfer visa for specialized-knowledge staff (5-year max).", "gc-work"],
    ["H-1B", "Employer-sponsored specialty-occupation work visa (6-year max, cap lottery).", "gc-work"],
    ["EB-1", "First-preference employment green card (extraordinary ability, etc.). No PERM required.", "gc-eb"],
    ["EB-2", "Second-preference green card: advanced degree or exceptional ability.", "gc-eb"],
    ["EB-3", "Third-preference green card: skilled worker or bachelor's degree.", "gc-eb"],
    ["I-140", "Immigrant petition establishing that you qualify for the EB category.", "gc-process"],
    ["I-485", "Adjustment of Status: becoming a permanent resident from inside the U.S.", "gc-process"],
    ["L-1", "Intracompany transfer visa (L-1A for managers, L-1B for specialized knowledge).", "gc-work"],
    ["O-1", "Extraordinary-ability work visa; pairs naturally with the EB-1A green card.", "gc-work"],
    ["F-1", "Student visa; OPT / STEM OPT provide post-graduation work authorization.", "gc-work"],
    ["NIW", "National Interest Waiver: an EB-2 self-petition, no employer or PERM.", "gc-eb"],
    ["PERM", "Labor-certification step for EB-2/EB-3; the filing date sets your priority date.", "gc-process"],
    ["priority date", "The date that fixes your place in the queue — the day your PERM (or, for EB-1/NIW, your I-140) is filed.", "gc-process"],
    ["PWD", "Prevailing Wage Determination: the first step of PERM.", "gc-process"],
    ["OPT", "Optional Practical Training: 12 months of post-graduation work authorization.", "gc-work"],
    ["FAD", "Final Action Dates: the Visa Bulletin chart that lets a green card be approved.", "gc-process"],
    ["DFF", "Dates for Filing: the earlier Visa Bulletin chart that can let you file I-485.", "gc-process"]
  ];
  var DEF = {}, ANCHOR = {};
  TERMS.forEach(function (t) { DEF[t[0]] = t[1]; ANCHOR[t[0]] = t[2]; });

  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  var RE = new RegExp("(" + TERMS.map(function (t) { return esc(t[0]); }).join("|") + ")");
  var BOUND = /[\w-]/;  // a term match must not be flanked by a word char or hyphen

  var EXCLUDE_TAGS = { A: 1, CODE: 1, ABBR: 1, SCRIPT: 1, STYLE: 1, NOSCRIPT: 1,
    BUTTON: 1, LABEL: 1, INPUT: 1, SELECT: 1, TEXTAREA: 1, H1: 1, H2: 1, H3: 1 };
  var EXCLUDE_CLASS = { "gloss-tip": 1, "radio-card": 1, "workvisa-chip": 1,
    "topbar": 1, "hubnav": 1, "jm-timeline": 1, "hero-metric": 1,
    // Step titles in the "5 steps" explainer read like headings; don't linkify them
    // (their body paragraphs carry the linked term instead).
    "bs-title": 1 };

  // Nearest prose block (P/LI/DD) that contains a node. Used to scope the
  // "link each term once" rule per paragraph rather than once per whole page.
  function proseBlock(node, root) {
    var el = node.parentElement;
    while (el && el !== root) {
      if (el.tagName === "P" || el.tagName === "LI" || el.tagName === "DD") return el;
      el = el.parentElement;
    }
    return root;
  }

  // Accept a text node only if it lives inside prose (p/li/dd) and no excluded
  // ancestor sits between it and that prose block.
  function nodeOK(node, root) {
    if (!node.nodeValue || !RE.test(node.nodeValue)) return false;
    var el = node.parentElement, inProse = false;
    while (el && el !== root) {
      if (EXCLUDE_TAGS[el.tagName]) return false;
      if (el.classList) {
        for (var k in EXCLUDE_CLASS) { if (EXCLUDE_CLASS.hasOwnProperty(k) && el.classList.contains(k)) return false; }
      }
      if (el.tagName === "P" || el.tagName === "LI" || el.tagName === "DD") inProse = true;
      el = el.parentElement;
    }
    return inProse;
  }

  // Wrap acronyms within `root`. First-occurrence scope is LOCAL to each call, so
  // the questionnaire prose and the dynamically-rendered result each get their own
  // links. Exposed as window.GCN_glossify so renderResult can re-run it on the
  // result container after each render (the initial pass runs before it exists).
  function glossify(root) {
    if (!root) return;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [], n;
    while ((n = walker.nextNode())) { if (nodeOK(n, root)) nodes.push(n); }

    // "Seen" is scoped per prose block (paragraph / list item), not per whole
    // page: a term links once per paragraph, so the same acronym in two different
    // steps each get a tooltip (e.g. H-1B in the Priya intro AND in step 1).
    var blockSeen = (typeof WeakMap === "function") ? new WeakMap() : null;
    var flatSeen = {};
    function seenFor(node) {
      if (!blockSeen) return flatSeen;
      var block = proseBlock(node, root);
      var s = blockSeen.get(block);
      if (!s) { s = {}; blockSeen.set(block, s); }
      return s;
    }
    nodes.forEach(function (node) {
      var seen = seenFor(node);
      var text = node.nodeValue, m, idx = -1, term = null;
      // find the first UNSEEN term in this node with valid word boundaries
      RE.lastIndex = 0;
      var scan = text, base = 0;
      while ((m = RE.exec(scan))) {
        var t = m[1], at = base + m.index;
        var before = at > 0 ? text.charAt(at - 1) : "";
        var after = text.charAt(at + t.length);
        if (!BOUND.test(before) && !BOUND.test(after) && !seen[t]) { idx = at; term = t; break; }
        base = at + t.length; scan = text.slice(base);
      }
      if (idx < 0) return;
      seen[term] = true;
      var a = document.createElement("a");
      a.className = "gloss-tip";
      a.href = "glossary.html#" + ANCHOR[term];
      a.title = DEF[term];
      a.textContent = term;
      var post = node.splitText(idx);
      post.nodeValue = post.nodeValue.slice(term.length);
      node.parentNode.insertBefore(a, post);
    });
  }

  // Expose so the Status result (rendered after load) can be glossified too.
  window.GCN_glossify = glossify;

  function initialPass() {
    // The Glossary page IS the definitions — don't tooltip it.
    if (document.querySelector(".gloss-group")) return;
    glossify(document.getElementById("maincontent") || document.querySelector(".container"));
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialPass);
  else initialPass();
})();

// Landing-page section collapsibles: open the target section's <details> when it
// is reached via an in-page anchor (e.g. the hero "New here? Learn how it works"
// -> #basics, or the footer "The Process" -> #overview), so those links aren't a
// dead two-click. Collapsed-by-default otherwise. No-op on pages without them.
(function () {
  "use strict";
  function openFor(hash) {
    if (!hash || hash.charAt(0) !== "#" || hash.length < 2) return;
    var sec = document.getElementById(hash.slice(1));
    if (!sec) return;

    // The target may itself be a disclosure (an FAQ question), so open it.
    if (sec.tagName === "DETAILS") sec.open = true;

    // Open every disclosure ABOVE it too. A question lives inside its section's
    // collapse shell, so opening only the question would leave it hidden. Walk
    // up rather than matching one fixed class, since the nesting differs by page.
    var el = sec.parentElement;
    while (el && el !== document.body) {
      if (el.tagName === "DETAILS") el.open = true;
      el = el.parentElement;
    }

    // And the original case: an anchor pointing at a section that WRAPS a
    // collapse shell, e.g. the hero link to #basics.
    var inner = sec.querySelector && sec.querySelector("details.section-collapse");
    if (inner) inner.open = true;
  }
  function init() {
    openFor(window.location.hash);
    window.addEventListener("hashchange", function () { openFor(window.location.hash); });
    // Same-hash re-clicks don't fire hashchange, so also open on the click itself.
    var links = document.querySelectorAll('a[href^="#"]');
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener("click", function () { openFor(this.getAttribute("href")); });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

/* ============================================================================
   SITEWIDE SEARCH — client-side, injected into the topbar on every page.
   ============================================================================
   The index (search-index.json, ~46KB) is fetched lazily the FIRST time the box
   is focused, not on page load, so it costs nothing for the many visitors who
   never search. Matching happens entirely in the browser: no query, no keypress
   and no result ever leaves the device, which keeps the privacy note accurate.

   Regenerate the index with `node build-search-index.mjs` after editing content.

   Deliberately NOT a fuzzy or semantic search. It is prefix-and-token matching
   over titles and short answers, with a small synonym map for the handful of
   everyday words people use instead of the legal term. That is honest about what
   it can do; it will not answer a question the site does not already answer.
   ========================================================================== */
(function () {
  "use strict";

  // Everyday phrasing -> the words actually used on the site. Kept short on
  // purpose; a big list here starts silently guessing at intent.
  var SYN = {
    wife: "spouse", husband: "spouse", partner: "spouse", married: "spouse",
    kid: "child", kids: "children", son: "child", daughter: "child",
    "work permit": "employment authorization ead", ead: "employment authorization work permit",
    "green card": "permanent resident immigrant", greencard: "permanent resident immigrant",
    fired: "laid off termination cessation", layoff: "laid off termination cessation",
    "laid off": "termination cessation grace period", quit: "termination cessation",
    lottery: "cap selection registration", raffle: "cap selection registration",
    salary: "wage compensation", pay: "wage compensation", stock: "equity wage",
    rsu: "equity stock wage", bonus: "wage compensation",
    travel: "abroad departure re-entry", trip: "abroad departure re-entry",
    stamp: "visa", stamping: "visa consulate", interview: "consulate visa",
    move: "relocation worksite location", moving: "relocation worksite location",
    remote: "home worksite location", wfh: "home worksite remote",
    backlog: "queue priority date wait", wait: "queue priority date backlog",
    transfer: "portability change employer", switch: "portability change employer"
  };

  var STOP = { the:1, a:1, an:1, is:1, are:1, do:1, does:1, did:1, can:1, i:1,
    my:1, me:1, of:1, to:1, in:1, on:1, for:1, and:1, or:1, if:1, it:1, what:1,
    how:1, when:1, why:1, be:1, am:1, was:1, will:1, with:1, that:1, this:1 };

  var GROUP = { q: "Questions", g: "Glossary", p: "Pages" };

  var idx = null, loading = false, sel = -1, shown = [];

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function tokens(q) {
    var raw = q.toLowerCase();
    var out = [];
    // Multi-word synonym keys first, so "laid off" beats "laid" + "off".
    Object.keys(SYN).forEach(function (k) {
      if (k.indexOf(" ") > 0 && raw.indexOf(k) !== -1) out = out.concat(SYN[k].split(" "));
    });
    raw.split(/[^a-z0-9-]+/).forEach(function (w) {
      if (!w || STOP[w]) return;
      out.push(w);
      if (SYN[w]) out = out.concat(SYN[w].split(" "));
    });
    return out.filter(function (w, i, a) { return w && a.indexOf(w) === i; });
  }

  // Strip everything that is not a letter or digit. The site writes "H-1B",
  // "EB-2", "I-140"; people type "h1b", "eb2", "i140". Comparing the stripped
  // forms makes the hyphen irrelevant in both directions, which is more robust
  // than trying to list every spelling as a synonym.
  function flat(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, ""); }

  function score(e, toks, rawq) {
    var L = e.l.toLowerCase(), B = (e.b || "").toLowerCase(), S = (e.s || "").toLowerCase();
    // Computed once per entry and cached on it; the index is reused across
    // every keystroke, so re-stripping 139 entries per character would be waste.
    if (e.__fl === undefined) {
      e.__fl = flat(e.l); e.__fb = flat(e.b || ""); e.__fs = flat(e.s || "");
    }
    var fq = flat(rawq);
    var n = 0, hit = 0, bodyPts = 0;
    if (rawq.length > 2 && L.indexOf(rawq) !== -1) n += 60;          // whole phrase in the title
    else if (fq.length > 2 && e.__fl.indexOf(fq) !== -1) n += 52;    // same, ignoring punctuation
    for (var i = 0; i < toks.length; i++) {
      var t = toks[i], got = false;
      if (L.indexOf(t) !== -1) { n += L.indexOf(t) === 0 ? 26 : 18; got = true; }
      if (S.indexOf(t) !== -1) { n += 6; got = true; }
      // Body hits are capped in total. A long page blurb can otherwise collect
      // a dozen incidental matches and outrank the question that actually
      // answers the query in its title.
      if (B.indexOf(t) !== -1) { bodyPts = Math.min(bodyPts + 4, 12); got = true; }
      // Punctuation-blind fallback, scored slightly below an exact hit so a
      // literal match still wins when both are present.
      if (!got) {
        var ft = flat(t);
        if (ft.length > 1) {
          if (e.__fl.indexOf(ft) !== -1) { n += e.__fl.indexOf(ft) === 0 ? 22 : 16; got = true; }
          else if (e.__fs.indexOf(ft) !== -1) { n += 5; got = true; }
          else if (e.__fb.indexOf(ft) !== -1) { bodyPts = Math.min(bodyPts + 3, 12); got = true; }
        }
      }
      if (got) hit++;
    }
    n += bodyPts;
    if (!hit) return 0;
    // Reward covering more of what was typed, so a 3-of-3 beats a 1-of-3 that
    // happens to repeat its single hit.
    n += Math.round((hit / toks.length) * 22);
    if (e.t === "q") n += 5;   // a direct question is usually the better answer
    return n;
  }

  function mark(s, toks) {
    var out = esc(s);
    toks.forEach(function (t) {
      if (t.length < 2) return;
      out = out.replace(new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
    });
    return out;
  }

  function build() {
    var actions = document.querySelector(".hubnav-actions");
    if (!actions || document.getElementById("gcs-input")) return null;

    // An inline input in the topbar does not fit. .hubnav-links has
    // overflow-x:auto and .hubnav-actions has flex-shrink:0, so a 148px box
    // (260px focused) squeezed the link row and it clipped its last item
    // instead of reflowing. An icon costs ~30px, and moving the search into an
    // overlay also gives the results far more room than a dropdown had.
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "gcs-trigger";
    btn.id = "gcs-trigger";
    btn.setAttribute("aria-label", "Search this site");
    btn.setAttribute("title", "Search (press /)");
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" ' +
      'stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4.2-4.2"/></svg>';
    actions.insertBefore(btn, actions.firstChild);

    // Lives on <body>, so the topbar's flex layout can never constrain it.
    var modal = document.createElement("div");
    modal.className = "gcs-modal";
    modal.id = "gcs-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Search this site");
    modal.hidden = true;
    // Results are plain anchors, deliberately NOT role="listbox"/"option".
    // Those roles forbid the native link behavior worth keeping (open in a new
    // tab, copy link); arrow keys move real DOM focus instead, and the live
    // region below announces the count.
    modal.innerHTML =
      '<div class="gcs-backdrop"></div>' +
      '<div class="gcs-sheet" role="document">' +
        '<div class="gcs-field">' +
          '<svg class="gcs-mag" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" ' +
            'stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4.2-4.2"/></svg>' +
          '<input id="gcs-input" class="gcs-input" type="search" autocomplete="off" ' +
            'placeholder="Search questions, terms, and pages" aria-label="Search this site">' +
          '<button type="button" class="gcs-close" aria-label="Close search">Esc</button>' +
        '</div>' +
        '<div class="gcs-panel" id="gcs-panel"></div>' +
        '<span class="sr-only" id="gcs-live" aria-live="polite"></span>' +
      '</div>';
    document.body.appendChild(modal);

    return {
      input: modal.querySelector("#gcs-input"),
      panel: modal.querySelector("#gcs-panel"),
      modal: modal,
      trigger: btn
    };
  }

  var ui = null, lastFocused = null;

  function openModal() {
    if (!ui || !ui.modal.hidden) return;
    lastFocused = document.activeElement;
    ui.modal.hidden = false;
    document.body.style.overflow = "hidden";
    load();
    ui.input.focus();
  }

  function closeModal() {
    if (!ui || ui.modal.hidden) return;
    ui.modal.hidden = true;
    document.body.style.overflow = "";
    ui.input.value = "";
    close();
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  function close() {
    if (!ui) return;
    ui.panel.classList.remove("open");
    ui.panel.innerHTML = "";
    sel = -1;
  }

  function render(q) {
    if (!ui) return;
    var toks = tokens(q), rawq = q.toLowerCase().trim();
    if (!toks.length) { close(); return; }

    shown = [];
    if (idx) {
      var scored = [];
      for (var i = 0; i < idx.length; i++) {
        var sc = score(idx[i], toks, rawq);
        if (sc > 0) scored.push({ e: idx[i], sc: sc });
      }
      scored.sort(function (a, b) { return b.sc - a.sc; });
      shown = scored.slice(0, 12).map(function (x) { return x.e; });
    }

    var html = "";
    if (!idx) {
      html = '<div class="gcs-empty">Loading the index…</div>';
    } else if (!shown.length) {
      html = '<div class="gcs-empty">Nothing matched <strong>' + esc(q) + '</strong>.' +
             ' Try a shorter phrase, or the word the site would use: "spouse" rather than "wife",' +
             ' "termination" rather than "fired".</div>';
    } else {
      var last = null, n = 0;
      shown.forEach(function (e) {
        if (e.t !== last) { html += '<div class="gcs-group">' + GROUP[e.t] + "</div>"; last = e.t; }
        html += '<a class="gcs-item" href="' + esc(e.u) + '">' +
                '<span class="gi-l">' + mark(e.l, toks) + "</span>" +
                (e.s ? '<span class="gi-s">' + esc(e.s) + "</span>" : "") +
                (e.b ? '<span class="gi-b">' + mark(e.b, toks) + "</span>" : "") +
                "</a>";
        n++;
      });
      html += '<div class="gcs-hint">Searches this site only. Nothing you type is sent anywhere.</div>';
    }
    ui.panel.innerHTML = html;
    ui.panel.classList.add("open");
    var live = document.getElementById("gcs-live");
    if (live) {
      live.textContent = !idx ? "Loading results"
        : shown.length ? shown.length + (shown.length === 1 ? " result" : " results")
        : "No results";
    }
    sel = -1;
  }

  function items() { return ui ? ui.panel.querySelectorAll(".gcs-item") : []; }

  function move(d) {
    var els = items();
    if (!els.length) return;
    if (sel >= 0 && els[sel]) els[sel].classList.remove("is-sel");
    sel = (sel + d + els.length) % els.length;
    els[sel].classList.add("is-sel");
    // Move real focus rather than tracking a virtual cursor. Enter then
    // activates the link natively, and Shift+Tab returns to the input.
    els[sel].focus();
    els[sel].scrollIntoView({ block: "nearest" });
  }

  function load() {
    if (idx || loading) return;
    loading = true;
    fetch("search-index.json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        idx = d || [];
        loading = false;
        window.__gcsReady = true;
        if (ui && ui.input.value.trim()) render(ui.input.value);
      })
      .catch(function () { idx = []; loading = false; });
  }

  function init() {
    ui = build();
    if (!ui) return;

    ui.trigger.addEventListener("click", openModal);
    ui.modal.querySelector(".gcs-backdrop").addEventListener("click", closeModal);
    ui.modal.querySelector(".gcs-close").addEventListener("click", closeModal);

    ui.input.addEventListener("focus", load);
    ui.input.addEventListener("input", function () {
      var v = this.value.trim();
      if (v.length < 2) { close(); return; }
      render(v);
    });
    ui.input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    });
    // Escape from anywhere inside the overlay, including from a focused result.
    ui.modal.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); closeModal(); }
    });
    // "/" opens search, the convention on docs sites. Ignored while typing.
    document.addEventListener("keydown", function (e) {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      var t = e.target, tag = t && t.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
      e.preventDefault(); openModal();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
