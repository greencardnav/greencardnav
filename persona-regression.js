/* persona-regression.js — Check My Status persona regression matrix.
 *
 * The Status result is computed client-side (app.js + rulebook.js), so unlike
 * smoke-test.mjs (a dependency-free static fetch check) these assertions can only
 * run in the browser where the logic executes. This file is therefore a
 * browser-injectable harness: it drives the questionnaire through each persona and
 * asserts signals about the rendered result. It is NOT referenced by any page, so
 * it never ships to users; it is a QA artifact.
 *
 * How to run:
 *   1. Open status.html (local or deployed) in a browser.
 *   2. Paste this file's contents into the devtools console, OR inject it via a
 *      Playwright/automation `evaluate`, then call:  await runPersonaRegression()
 *   It returns { passed, failed, total, results: [...] } and logs a table.
 *
 * What it guards (the reviewer's "verification > invention" matrix):
 *   - every category x country x priority-date combination renders without error
 *   - the retrogressed/Unavailable case (EB-2 India) is flagged, not shown "current"
 *   - a behind-the-cutoff case is a "structural wait", not falsely "current"
 *   - optional-detail branches (I-140 approved/pending, spouse cross-charge,
 *     IC->Manager move) change the output correctly
 *   - the F-1/OPT and "no GC started" (PRE) flows render their planning views
 *   - NO surface ever claims a category "skips"/"bypasses" the Visa Bulletin queue
 *   - the PRE flow never asserts "you qualify" (no deterministic eligibility verdict)
 */
(function (root) {
  "use strict";

  // Harmful-claim guard: a CATEGORY skipping/bypassing the visa-bulletin queue.
  // Deliberately scoped so the legitimate "all three skip PERM and share the same
  // visa queue" (EB-1 sub-categories) does NOT trip it.
  var QUEUE_SKIP_RE = /(niw|national interest waiver|eb-?[123])[^.]{0,45}(skip|bypass|jump)[^.]{0,30}(queue|bulletin|the line|the wait)/i;

  // Persona matrix. steps = radio (name,value) clicks; pd = priority date (ISO) or null.
  // assert = signals expected present (want:true) or absent (want:false) in the result text.
  var PERSONAS = [
    { name: "EB-2 India, PD 2021 (retrogressed)", steps: [["category","EB-2"],["country","India"]], pd: "2021-03-15",
      assert: [{ d: "flags paused/Unavailable", re: /(paused|unavailable|used up|retrogress)/i, want: true }] },
    { name: "EB-3 India, PD 2013", steps: [["category","EB-3"],["country","India"]], pd: "2013-01-01",
      assert: [{ d: "EB-2/EB-3 comparison framed as counsel evaluation", re: /counsel may evaluate whether a second petition/i, want: true },
               { d: "does NOT use the categorical 'moves you faster' promise", re: /moves you faster/i, want: false }] },
    { name: "EB-1A India, PD 2023 (behind cutoff)", steps: [["category","EB-1"],["d-eb1sub","EB-1A"],["country","India"]], pd: "2023-06-01",
      assert: [{ d: "shows a structural wait, not current", re: /(structural wait|serving priority dates|cutoff .* advance)/i, want: true }] },
    { name: "EB-1A Rest of World, PD 2024", steps: [["category","EB-1"],["d-eb1sub","EB-1A"],["country","ROW"]], pd: "2024-01-01", assert: [] },
    { name: "EB-2 Rest of World, PD 2023", steps: [["category","EB-2"],["country","ROW"]], pd: "2023-01-01", assert: [] },
    { name: "EB-2 China, PD 2020", steps: [["category","EB-2"],["country","China"]], pd: "2020-06-01", assert: [] },
    { name: "EB-3 Philippines, PD 2022", steps: [["category","EB-3"],["country","Philippines"]], pd: "2022-01-01", assert: [] },
    { name: "EB-2 India + I-140 approved", steps: [["category","EB-2"],["country","India"],["d-i140","approved"]], pd: "2015-01-01",
      assert: [{ d: "reflects PERM+I-140 done / structural wait", re: /(PERM and I-140 are done|structural wait)/i, want: true },
               { d: "addresses priority-date portability", re: /(portab|place in line|when it becomes)/i, want: true },
               { d: "EB-2/EB-3 comparison framed as counsel evaluation", re: /counsel may evaluate whether a second petition/i, want: true },
               { d: "does NOT use the categorical 'moves you faster' promise", re: /moves you faster/i, want: false },
               { d: "different-MSA move framed as reassessment, not automatic restart", re: /reassess whether new PERM steps/i, want: true }] },
    { name: "EB-2 India + I-140 pending", steps: [["category","EB-2"],["country","India"],["d-i140","pending-regular"]], pd: "2015-01-01",
      assert: [{ d: "reflects I-140 pending", re: /i-140[^.]{0,40}pend/i, want: true }] },
    { name: "EB-2 India + spouse cross-charge (ROW)", steps: [["category","EB-2"],["country","India"],["d-spouse","ROW"]], pd: "2015-01-01",
      assert: [{ d: "surfaces cross-chargeability", re: /(cross.?charg|202\(b\)|spouse's country)/i, want: true }] },
    { name: "EB-2 India + IC-to-manager role change", steps: [["category","EB-2"],["country","India"],["d-rolechange","ic-to-manager"]], pd: "2015-01-01",
      assert: [{ d: "surfaces move impact", re: /(impact|amendment|new PERM|priority date)/i, want: true }] },
    { name: "F-1 / OPT (no PD)", steps: [["category","F-1"],["country","India"]], pd: null,
      assert: [{ d: "shows OPT/lottery/H-1B path", re: /(OPT|lottery|H-1B|cap)/i, want: true }] },
    { name: "No GC started + H-1B Year 6 (PRE)", steps: [["category","PRE"],["country","India"],["d-previsa","H-1B"],["d-preyear","6"],["d-preintent","EB-2"]], pd: null,
      assert: [{ d: "shows a forward-looking runway/PERM plan", re: /(plan|runway|when to start|PERM|AC21|sixth year|6-year)/i, want: true },
               { d: "does NOT assert 'you qualify'", re: /you qualify\b/i, want: false }] }
  ];

  function pick(name, val) {
    var inp = document.querySelector('input[name="' + name + '"][value="' + val + '"]');
    if (!inp) return false;
    var card = inp.closest(".radio-card");
    if (card) { card.click(); return true; }
    inp.checked = true; inp.dispatchEvent(new Event("change", { bubbles: true })); return true;
  }
  function setPd(v) {
    var i = document.getElementById("pd-input");
    if (!i) return;
    i.value = v; i.dispatchEvent(new Event("input", { bubbles: true })); i.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  root.runPersonaRegression = async function runPersonaRegression() {
    var startBtn = [].slice.call(document.querySelectorAll("button")).find(function (b) { return /^start$/i.test((b.textContent || "").trim()); });
    if (startBtn) startBtn.click();
    var rc = document.getElementById("result-content");
    if (!rc) return { error: "Not on status.html (no #result-content). Open status.html first." };

    var results = [];
    for (var i = 0; i < PERSONAS.length; i++) {
      var p = PERSONAS[i];
      p.steps.forEach(function (s) { pick(s[0], s[1]); });
      if (p.pd) setPd(p.pd);
      // Work visa is a required 4th question. Ensure one chip is selected (default
      // "None", which is neutral for every persona's assertions) so the result
      // computes. Only click when nothing is selected, so we never toggle it off.
      var wvOn = [].some.call(document.querySelectorAll(".workvisa-chip"), function (c) { return c.classList.contains("selected"); });
      if (!wvOn) { var wvNone = document.querySelector('.workvisa-chip[data-value="None"]'); if (wvNone) wvNone.click(); }
      await wait(180);
      // The result groups its detail into collapsed <details> dropdowns. innerText
      // omits content inside a closed <details>, so expand them all first — this
      // asserts the content EXISTS and is correct (a user opens the dropdown to see
      // it), independent of the default collapsed presentation.
      [].slice.call(rc.querySelectorAll("details")).forEach(function (d) { d.open = true; });
      await wait(30);
      var t = rc.innerText || "";
      var failures = [];
      if (t.trim().length < 40) failures.push("did not render a result");
      if (QUEUE_SKIP_RE.test(t)) failures.push("claims a category skips/bypasses the visa-bulletin queue");
      p.assert.forEach(function (a) {
        var hit = a.re.test(t);
        if (hit !== a.want) failures.push((a.want ? "missing: " : "unexpected: ") + a.d);
      });
      results.push({ persona: p.name, pass: failures.length === 0, failures: failures });
    }
    var passed = results.filter(function (r) { return r.pass; }).length;
    var summary = { passed: passed, failed: results.length - passed, total: results.length, results: results };
    if (root.console && console.table) { console.table(results.map(function (r) { return { persona: r.persona, pass: r.pass, failures: r.failures.join("; ") }; })); }
    return summary;
  };
})(typeof window !== "undefined" ? window : this);
