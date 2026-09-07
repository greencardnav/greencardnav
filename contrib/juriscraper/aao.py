"""Scraper for the USCIS Administrative Appeals Office (AAO)

CourtID: aao
Court Short Name: AAO
Author: greencardnav
History:
    2026-09-06: Created

The AAO decides administrative appeals of USCIS immigration benefit denials --
employment-based petitions, national interest waivers, appeals of revocation.
Its non-precedent decisions are published as PDFs behind a faceted Drupal
listing. Free Law Project declares `aao` among its federal-special
jurisdictions but has no scraper for it.
"""

from datetime import date, datetime

from juriscraper.OpinionSiteLinear import OpinionSiteLinear


class Site(OpinionSiteLinear):
    """Scrape the AAO non-precedent decision listing.

    Two things about this source are worth knowing before editing:

    1. The year facet takes an ORDINAL, not a year. `y=1` is the current year,
       `y=2` the one before, and so on, up to 22 options. Passing `y=2024`
       returns zero results *silently* rather than erroring, so a naive year
       filter looks like it works and quietly scrapes nothing. See
       `_year_ordinal`.

    2. `uri_1` is the decision-category facet and there are 83 of them. `All`
       spans every category in one pass, which is what we want -- iterating the
       categories individually multiplies requests by 83 for the same rows.
    """

    base_url = (
        "https://www.uscis.gov/administrative-appeals/aao-decisions/"
        "aao-non-precedent-decisions"
    )
    # The listing's own year <select>: ordinal = YEAR_BASE - year.
    YEAR_BASE = 2027
    first_opinion_date = datetime(2005, 1, 1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.court_id = self.__module__
        self.url = self._build_url("All")
        self.status = "Unpublished"

    def _build_url(self, year_param, page=0, per_page=50):
        return (
            f"{self.base_url}?uri_1=All&m=All&y={year_param}"
            f"&items_per_page={per_page}&page={page}"
        )

    def _year_ordinal(self, year):
        ordinal = self.YEAR_BASE - int(year)
        if not 1 <= ordinal <= 22:
            raise ValueError(
                f"year {year} is outside the listing's range "
                f"({self.YEAR_BASE - 22}-{self.YEAR_BASE - 1})"
            )
        return str(ordinal)

    def _process_html(self):
        for row in self.html.xpath("//div[contains(@class, 'views-row')]"):
            link = row.xpath(
                ".//*[contains(@class, 'views-item-title')]//a/@href"
            )
            if not link:
                continue
            url = link[0]
            if not url.lower().endswith(".pdf"):
                continue

            raw_date = row.xpath(
                ".//*[contains(@class, 'views-field-field-display-date')]"
                "//time/@datetime"
            )
            if not raw_date:
                raw_date = row.xpath(
                    ".//*[contains(@class, 'views-field-field-display-date')]"
                    "//text()"
                )
            case_date = self._parse_date(raw_date)
            if not case_date:
                continue

            name = row.xpath(
                ".//*[contains(@class, 'views-item-title')]//a//text()"
            )
            self.cases.append(
                {
                    "url": url,
                    "date": case_date,
                    "name": " ".join(" ".join(name).split()) or "Matter of Unnamed",
                    # AAO publishes no docket number. Its decisions are cited by
                    # the redacted "Matter of X-" caption plus the decision date;
                    # the internal receipt number is deliberately withheld from
                    # the published PDF. Sending an empty string rather than
                    # inventing one from the filename, which would look like a
                    # citation while being an artifact of USCIS's file naming.
                    "docket": "",
                }
            )

    # Formats observed on this listing.
    #
    # VERIFIED AGAINST LIVE MARKUP 2026-09-06: the listing emits NO <time
    # datetime> attribute at all (0 occurrences in a real page containing 10
    # rows). The date arrives as visible text in the
    # views-field-field-display-date cell, so the text fallback in
    # _process_html is the real path and the attribute lookup is defensive only.
    # An earlier comment here called the attribute the "primary path" -- that was
    # reconstructed from notes and is wrong for this source.
    #
    # The ISO formats are kept anyway: they cost nothing and Drupal listings
    # commonly add datetime= when a view is reconfigured.
    #
    # Separately, an earlier version truncated input to value[:19] before
    # matching, stripping a trailing "Z" so ISO input could never match. Combined
    # with the date-missing `continue` in _process_html that returned ZERO cases
    # with no error. Match the untruncated value first, then shorter prefixes.
    DATE_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                    "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y")

    @classmethod
    def _parse_date(cls, raw):
        for value in raw:
            value = value.strip()
            if not value:
                continue
            for candidate in (value, value[:19], value[:10]):
                for fmt in cls.DATE_FORMATS:
                    try:
                        return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
        return None

    def _download_backwards(self, dates):
        """Walk the year facet, since the listing has no date-range filter."""
        start, end = dates
        for year in range(start.year, end.year + 1):
            try:
                param = self._year_ordinal(year)
            except ValueError:
                continue
            self.url = self._build_url(param)
            self.html = self._download()
            self._process_html()

    def make_backscrape_iterable(self, kwargs):
        start = kwargs.get("backscrape_start") or self.first_opinion_date
        end = kwargs.get("backscrape_end") or date.today()
        if isinstance(start, str):
            start = datetime.strptime(start, "%Y/%m/%d")
        if isinstance(end, str):
            end = datetime.strptime(end, "%Y/%m/%d")
        self.back_scrape_iterable = [(start, end)]
