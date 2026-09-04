/* Green Card Navigator — single source of truth for dynamic immigration data.
   Self-contained (no dependency on app.js). Loaded before app.js/rulebook.js so
   window.GCN_DATA exists first. Every displayed dynamic fee is defined ONCE here
   and stamped with a "verified as of" date + a link to the official source, so a
   fee change is a one-line edit in this file rather than an edit across pages.

   To update a fee: change the amount + display below, then bump feesVerified.date.
   NOTE: the EB guide/compare pages also carry a STATIC fallback of each fee inside
   its [data-fee] span (so no-JS clients and crawlers see an amount, not a blank).
   This script overwrites those spans with the value below on load, so users always
   see the canonical amount here — but when a fee changes, update the matching
   fallback text in the *.html [data-fee] spans too, or no-JS views go stale. */
(function () {
  "use strict";

  window.GCN_DATA = {
    // USCIS filing fees. Amounts are the source of truth; `display` is the
    // pre-formatted string rendered into every [data-fee] element on the site.
    fees: {
      i140Online: { amount: 665, display: "$665" },
      i140Paper: { amount: 715, display: "$715" },
      i485Online: { amount: 1390, display: "$1,390" },
      i485Paper: { amount: 1440, display: "$1,440" },
      i907Premium: { amount: 2965, display: "$2,965" },
      // The Asylum Program Fee is an ADDITIONAL fee due WITH the I-140, not part of it, and
      // the I-140 filing fee above is listed by USCIS as "$715 plus additional fees, if
      // applicable". It was missing from every I-140 fee table on this site, which
      // understated the real cost of a self-petition by $300.
      //
      // G-1055 Edition 05/29/26, page 9, I-140 block, verbatim:
      //     1. Asylum Program Fee
      //        a. If you are filing as a Regular Petitioner            a. $600
      //        b. If filing as a Nonprofit                             b. $0
      //        c. If filing as a Small Employer or self-petitioner     c. $300
      //
      // "or self-petitioner" is explicit in that line, so $300 is the figure that applies to
      // an EB-1A or EB-2 NIW self-petitioner - the exact audience of the pages showing this
      // table. Corroborated by uscis.gov/i-140, which instructs self-petitioners to answer
      // No to the nonprofit question and Yes to the small-employer question, which is the
      // combination that yields the reduced amount.
      asylumProgramFeeSelf: { amount: 300, display: "$300" }
    },
    // Governance stamp: when the fees above were last checked, and where to
    // confirm the current amount before filing.
    feesVerified: {
      date: "September 2026",
      sourceName: "USCIS fee schedule (Form G-1055, Edition 05/29/26)",
      sourceUrl: "https://www.uscis.gov/g-1055"
    },

    // H-1B fee landscape (reflects the 2024 USCIS final fee rule). These are
    // employer-side petition fees plus the consular visa fee; amounts change
    // and several vary by employer size/type, so each row links its official
    // page and the whole table is stamped with a verified date. Rendered by the
    // H-1B checklist's "Fees at a glance" section (renderH1bChecklist in app.js).
    h1bFees: [
      {
        label: "H-1B registration",
        amount: "$215",
        who: "Employer",
        when: "Cap-subject petitions only, during the annual electronic registration window (typically March).",
        url: "https://www.uscis.gov/working-in-the-united-states/temporary-workers/h-1b-specialty-occupations/h-1b-electronic-registration-process",
        urlText: "USCIS H-1B registration"
      },
      {
        label: "Form I-129 base filing fee",
        amount: "$780",
        who: "Employer",
        when: "Filed with every H-1B petition (new, transfer, extension, or amendment). Reduced to $460 for small employers (25 or fewer full-time employees) and nonprofits.",
        url: "https://www.uscis.gov/i-129",
        urlText: "Form I-129 (USCIS)"
      },
      {
        label: "Asylum Program Fee",
        amount: "$600",
        who: "Employer",
        when: "Filed with the I-129. Reduced to $300 for small employers (25 or fewer full-time employees) and $0 for nonprofits — confirm which applies.",
        url: "https://www.uscis.gov/g-1055",
        urlText: "USCIS fee schedule"
      },
      {
        label: "ACWIA training fee",
        amount: "$1,500",
        who: "Employer (cannot be charged to the employee)",
        when: "With the I-129 on most cap and change-of-employer petitions. Reduced to $750 for employers with 25 or fewer full-time employees.",
        url: "https://www.uscis.gov/i-129",
        urlText: "Form I-129 (USCIS)"
      },
      {
        label: "Fraud Prevention & Detection fee",
        amount: "$500",
        who: "Employer (cannot be charged to the employee)",
        when: "New employment and change-of-employer (transfer) petitions. Not charged on a straight extension with the same employer.",
        url: "https://www.uscis.gov/i-129",
        urlText: "Form I-129 (USCIS)"
      },
      {
        label: "Presidential Proclamation fee",
        amount: "$100,000",
        who: "Employer (petitioner)",
        when: "Applies to certain H-1B petitions under a 2025 Presidential Proclamation, unless an exception has been granted. Highly situation-specific, subject to change and legal challenge, and paid separately (not with the petition). Most petitions are not affected — confirm applicability with counsel.",
        url: "https://www.uscis.gov/sites/default/files/document/memos/H1B_Proc_Memo_FINAL.pdf",
        urlText: "USCIS proclamation guidance"
      },
      {
        label: "Premium processing (Form I-907)",
        amount: "$2,965",
        who: "Optional — employer or employee",
        when: "Optional. Guarantees a USCIS decision on the I-129 within the posted business-day window. Does not change the outcome, only the speed.",
        url: "https://www.uscis.gov/i-907",
        urlText: "Form I-907 (USCIS)"
      },
      {
        label: "Consular visa fee (MRV, DS-160)",
        amount: "$205",
        who: "You (the beneficiary)",
        when: "Consular stamping only — paid abroad before the visa interview. Not owed if you gain H-1B by change of status inside the U.S.",
        url: "https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/fees/fees-visa-services.html",
        urlText: "State Dept visa fees"
      }
    ],
    // A separate large-employer surcharge (Public Law 114-113, $4,000) applies to
    // certain 50+-employee employers that are more than 50% H-1B/L-1 — an edge
    // case surfaced as a note rather than a standard row.
    h1bFeesNote: "Certain large employers (50+ employees that are more than 50% H-1B or L-1 workers) owe an additional $4,000 fee under Public Law 114-113. Most employers do not.",
    h1bFeesVerified: {
      date: "August 2026",
      sourceName: "the 2024 USCIS fee rule (Form G-1055)",
      sourceUrl: "https://www.uscis.gov/g-1055"
    }
  };

  function applyData() {
    var data = window.GCN_DATA;
    if (!data) { return; }

    // Fill every fee placeholder from the single definition.
    var feeEls = document.querySelectorAll("[data-fee]");
    var i;
    for (i = 0; i < feeEls.length; i++) {
      var key = feeEls[i].getAttribute("data-fee");
      var fee = data.fees[key];
      if (fee) { feeEls[i].textContent = fee.display; }
    }

    // Fill every "verified as of / official source" stamp.
    var stampEls = document.querySelectorAll("[data-fees-stamp]");
    var v = data.feesVerified;
    var stampHtml =
      "Fees reflect the " + v.sourceName + ", last checked " + v.date +
      '. Confirm the current amount on the <a href="' + v.sourceUrl +
      '" target="_blank" rel="noopener noreferrer">official fee schedule</a> before filing.';
    var j;
    for (j = 0; j < stampEls.length; j++) {
      stampEls[j].innerHTML = stampHtml;
    }
  }

  // Run on DOMContentLoaded, or immediately if the DOM is already parsed.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyData);
  } else {
    applyData();
  }
})();
