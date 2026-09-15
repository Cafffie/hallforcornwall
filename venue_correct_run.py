"""Hallforcornwall extractor implementation using the framework."""
import json
import random
import re
import sys
import time
from datetime import date, datetime

import pandas as pd
from dateutil import parser
from selenium.webdriver.common.by import By
from seleniumbase import SB

from utils.base_extractor import BaseExtractor
from utils.logger import setup_logger
from utils.scraping_helpers import (
    extract_postcode,
    format_datetime_key,
    get_city_country_uk,
    get_currency_from_price,
    get_scrape_datetime,
    human_delay,
    human_scroll,
    normalize_country,
    parse_booking_dates,
    standardize_category,
)

from .hallforcornwall_config import (
    DEFAULT_CURRENCY,
    DEFAULT_THEATRE_DETAILS,
    PAGES,
    SELECTORS,
    VENUE_MAP,
)

logger = setup_logger(__name__, log_to_file=False)


class HallforcornwallExtractor(BaseExtractor):
    """Extractor for hallforcornwall website."""

    def __init__(self, local_test=False, show_count=2, **kwargs):
        super().__init__(
            site_id="hallforcornwall",
            log_to_file=False,
            log_to_terminal=True,
            local_test=local_test,
            show_count=show_count,
            **kwargs,
        )
        self.all_data = []

    def safe_get(self, sb, url, wait=10):
        try:
            # self.custom_logger.info("Loading URL: %s", url)
            sb.uc_open_with_reconnect(url, reconnect_time=wait if wait > 4 else 4)
            if (
                "captcha" in sb.get_current_url().lower()
                or "distil" in sb.get_page_source().lower()
            ):
                self.custom_logger.warning("Bot protection detected. Solving...")
                sb.uc_gui_handle_captcha()
                time.sleep(random.uniform(2, 4))
            self.custom_logger.info("Page loaded successfully: %s", url)
            return True
        except Exception as e:
            self.custom_logger.error(
                "Failed to load page: %s | Exception: %s", url, repr(e)
            )
            return None

    def accept_cookies(self, sb):
        cookie_xpath = SELECTORS["cookie_button"]
        try:
            if sb.is_element_visible(cookie_xpath):
                human_delay(1, 2.5)
                sb.click(cookie_xpath)
                human_delay(2, 3)
        except Exception:
            pass

    def _parse_date(self, text: str) -> date | None:
        try:
            dt = parser.parse(text, dayfirst=True, fuzzy=True)
            if dt.date() < date.today():
                dt = dt.replace(year=dt.year + 1)
            return dt.strftime("%Y-%m-%d")
        except Exception as e:
            self.custom_logger.error(f"_parse_date failed for '{text}': {e}")
            return None

    def _clean_date_text(self, raw_text: str) -> str | None:
        """Pull just the date substring out of a raw_date_text blob.

        Some .row_date cells carry extra notices in the same textContent
        (e.g. "Fri 26 Mar 2027\n...Under 16s must be accompanied by an
        adult 18+"), and some already include their own year while others
        don't. Isolating the date via regex keeps that trailing text out
        of the string we hand to _parse_date.
        """
        match = re.search(
            r"(?:[A-Za-z]{3,9}\s+)?\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{4})?",
            raw_text,
        )
        return match.group(0) if match else None

    def get_show_links(self, sb):
        elements = sb.find_elements(By.CSS_SELECTOR, SELECTORS["shows_link"])
        return [e.get_attribute("href") for e in elements if e.get_attribute("href")]

    # Trailing UK postcode shape (e.g. "TR1 2LL", "TR7 3JA"): 1-2 letters,
    # a digit, an optional letter/digit, optional space, a digit, 2
    # letters, end of string. Used only to recognize and strip the
    # postcode text itself out of an address segment -- never to resolve,
    # validate, or look anything up from it.
    _TRAILING_UK_POSTCODE_RE = re.compile(
        r"[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}$"
    )

    @classmethod
    def _city_from_address(cls, address: str) -> str | None:
        """Pull the city straight from a "<street>, <city>, <postcode>"
        address string -- no postcode lookup involved at all, the sole
        source for `city` on this scraper. `get_city_country_uk`'s city
        value comes from postcodes.io's `admin_district` field, which for
        a unitary authority (Cornwall included) is the county-wide
        authority name, not the actual town -- confirmed live wrong for
        "TR1 2LL" (returned "Cornwall", real town "Truro", per postcodes.io's
        own `parish`/`bua` fields) -- not reliable enough to use even as a
        fallback.

        The postcode isn't always its own comma segment -- "Back Quay,
        Truro, TR1 2LL" has it standalone, but "Treviglas Academy Sports
        Hub, Bradley Rd, Newquay TR7 3JA" glues it straight onto the city
        with no comma. Handle both: strip a trailing postcode-shaped
        pattern off the last segment first (leaves "Newquay" untouched in
        the second case); only if that empties the segment entirely (the
        first case, where the last segment WAS just the postcode) does the
        city fall back to the segment before it. `city` stays `None` (an
        honest gap) rather than guessing if nothing usable is left.
        """
        parts = [p.strip() for p in address.split(",") if p.strip()]
        if not parts:
            return None

        last = cls._TRAILING_UK_POSTCODE_RE.sub("", parts[-1]).strip()
        if last:
            return last
        return parts[-2] if len(parts) >= 2 else None

    @staticmethod
    def _normalize_whitespace(text: str | None) -> str:
        """Collapse any run of whitespace (spaces, tabs, newlines -- e.g.
        from raw DOM `textContent`, which unlike the rendered `.text`
        preserves source-HTML indentation) into single spaces, trimmed.
        """
        return " ".join((text or "").split())

    def _get_show_title(self, sb) -> str | None:
        """Extract show title."""
        try:
            return self._normalize_whitespace(sb.get_text(SELECTORS["title"])) or None
        except Exception:
            return None

    def _get_terminal_dates(
        self, sb
    ) -> str | None:  # Fixed type hinting hint to match output tuple
        """Extract show header dates."""
        try:
            # Mon 13 - Sat 18 Jul 2026
            terminal_date_el = sb.get_text(SELECTORS["terminal_date"])

            if "," in terminal_date_el:
                terminal_date = terminal_date_el.split(",")[0]
            else:
                terminal_date = terminal_date_el

            return terminal_date.strip() if terminal_date else None
        except Exception as e:
            self.custom_logger.debug(
                f" terminal date extraction failed: {e}", "warning"
            )
            return None

    def _get_venue_details_from_page(self, sb) -> dict | None:
        """Scrape venue name/address live from the Spektrix booking widget's
        own venue-details line, instead of the site's separate static
        "visiting us" page -- the widget's address is the one that actually
        corresponds to where this specific show is booked. Call this once
        we're wherever the widget actually lives (inside #SpektrixIFrame,
        or the main page for a directly-embedded widget) -- returns None if
        it doesn't expose a venue name here (e.g. no seat map for this
        performance at all -- see `_get_event_venue` for that case).

        Reads via `execute_script`/`querySelector` + `textContent`, not
        `sb.find_element(...)`/`get_text()`: confirmed live that the
        `<p id="...VenueDetails" class="Event AreaAndVenueDetails">`
        wrapping `.VenueName`/`.VenueAddress` is inline-styled
        `display:none` on a show WITH an interactive seat map (Agatha
        Christie's The Hollow) -- SeleniumBase's `find_element` waits for
        *visibility* by default and raises/times out on a hidden element
        (confirmed live: "Element {.VenueName} was not visible after 10
        seconds!"), even though the real values are genuinely present in
        the DOM the whole time and readable immediately via a raw JS
        `querySelector` + `textContent`, no area selection or wait needed.
        """
        try:
            venue_name, raw_address = sb.execute_script(
                """
                var nameEl = document.querySelector(arguments[0]);
                var addrEl = document.querySelector(arguments[1]);
                return [
                    nameEl ? nameEl.textContent : null,
                    addrEl ? addrEl.textContent : null
                ];
                """,
                SELECTORS["venue_name"],
                SELECTORS["venue_address"],
            )
        except Exception:
            return None

        venue_name = self._normalize_whitespace(venue_name)
        if not venue_name:
            return None
        raw_address = self._normalize_whitespace(raw_address)

        postcode = extract_postcode(raw_address, region="UK")
        # `get_city_country_uk`'s city value comes from postcodes.io's
        # `admin_district` field, which for a unitary authority (Cornwall
        # included) is the county-wide authority name, not the actual town
        # -- confirmed live wrong for "TR1 2LL" (returned "Cornwall", real
        # town "Truro"). Not trustworthy enough to use, even as a fallback
        # -- only ever take `country` from it; city comes solely from the
        # widget's own address text.
        _, country = get_city_country_uk(postcode) if postcode else (None, None)
        city = self._city_from_address(raw_address)

        self.custom_logger.info(
            " Scraped venue from Spektrix widget: %s | %s", venue_name, raw_address
        )

        return {
            "venue": venue_name,
            "address": raw_address or venue_name,
            "city": city,
            "country": normalize_country(country) if country else None,
        }

    def _get_event_venue(self, sb) -> dict | None:
        """Extract an event-specific venue from the current show page."""

        try:
            description = sb.get_text(SELECTORS["event_description"]).strip().lower()

            for venue_name, venue_details in VENUE_MAP.items():
                if venue_name.lower() in description:
                    self.custom_logger.info(
                        "Event-specific venue found: %s",
                        venue_details["venue"],
                    )
                    return venue_details

        except Exception as e:
            self.custom_logger.warning(
                "Event-specific venue extraction failed: %s",
                e,
            )

        return None

    def _extract_performances(self, sb) -> list[dict]:
        """Parses performance instances directly from hallforcornwall's single or continuous date markers."""

        performances = []

        # Try clicking a 'Book' tab or button if performances are hidden behind a modal (common for Spektrix)
        try:
            sb.wait_for_element_present(SELECTORS["first_book_btn"], timeout=10)

            first_book_btn = sb.find_element(SELECTORS["first_book_btn"])
            sb.execute_script("arguments[0].click();", first_book_btn)
            # first_book_btn.click()
            human_delay(1.0, 2.0)
            self.custom_logger.info(" First Book button clicked successfully.")
        except Exception as e:
            self.custom_logger.info(f"  Error finding first booking button: {e}")
            return []

        try:
            date_blocks = sb.find_elements(By.CSS_SELECTOR, SELECTORS["date_blocks"])
            self.custom_logger.info(f" Found {len(date_blocks)} performance dates")

            for block in date_blocks:
                try:
                    booking_url = block.find_element(
                        By.CSS_SELECTOR, SELECTORS["booking_url"]
                    ).get_attribute("href")

                    raw_date_text = (
                        block.find_element(By.CSS_SELECTOR, SELECTORS["raw_date_text"])
                        .get_attribute("textContent")
                        .strip()
                    )

                    raw_time_text = (
                        block.find_element(By.CSS_SELECTOR, SELECTORS["raw_time_text"])
                        .get_attribute("textContent")
                        .strip()
                    )

                    if not raw_date_text or not raw_time_text:
                        self.custom_logger.info(
                            " performance raw_date_text, raw_time_text not found "
                        )
                        continue

                    # Strip out any trailing notices (e.g. age restriction text)
                    # riding along in the same cell as the date.
                    clean_date_text = self._clean_date_text(raw_date_text)
                    if not clean_date_text:
                        self.custom_logger.info(
                            f" Could not isolate a date from raw_date_text: {raw_date_text}"
                        )
                        continue

                    # Only append the current year as a fallback when the
                    # cleaned date doesn't already carry its own year.
                    if re.search(r"\d{4}", clean_date_text):
                        date_string = f"{clean_date_text} {raw_time_text}"
                    else:
                        year = str(datetime.now().year)
                        date_string = f"{clean_date_text} {year} {raw_time_text}"

                    self.custom_logger.info(f" performance date_string : {date_string}")

                    date_ymd = self._parse_date(date_string)
                    time_hm = parser.parse(raw_time_text).strftime("%H:%M")
                    # time_hm = convert_to_24hr(raw_time_text)

                    performances.append(
                        {"date": date_ymd, "time": time_hm, "booking_url": booking_url}
                    )

                except Exception as inner_e:
                    self.custom_logger.debug(
                        f"Date block parsing failed due to inner error: {inner_e}"
                    )
                    continue

        except Exception as e:
            self.custom_logger.debug(f" Error extracting performances: {e}")
        return performances

    def extract_seats(self, sb) -> tuple:
        """Extracts seats and pricing from the currently open SVG modal."""

        perf_capacity = 0
        currency = None
        all_seats = {}
        venue_details = None

        try:
            sb.wait_for_ready_state_complete()
            human_delay(2, 3)

            dropdown_selector = SELECTORS["seating_dropdown"]
            has_dropdown = False
            areas = []

            try:
                sb.wait_for_element_present(dropdown_selector, timeout=15)
                has_dropdown = True
                self.custom_logger.info("Dropdown found on main page")
            except Exception:
                pass

            if not has_dropdown:
                try:
                    iframes = sb.find_elements(SELECTORS["iframe"])
                    for iframe in iframes:
                        try:
                            sb.switch_to_frame(iframe)
                            human_delay(2, 3)
                            sb.execute_script("window.scrollTo(0, 300);")
                            human_delay(1, 2)
                            sb.execute_script("window.scrollTo(0, 0);")
                            human_delay(1, 2)

                            # -----------------------------
                            # CASE 1: iframe has dropdown
                            # -----------------------------
                            if sb.is_element_present(dropdown_selector):
                                has_dropdown = True
                                self.custom_logger.info("Dropdown found in iframe")
                                break

                            # -----------------------------
                            # CASE 2: iframe has seat map
                            # (single seating layout)
                            # -----------------------------
                            self.custom_logger.info(
                                "No dropdown found. Checking for seat map..."
                            )

                            for _ in range(20):
                                seats = sb.find_elements(
                                    By.CSS_SELECTOR,
                                    SELECTORS["seats"],
                                )

                                if seats:
                                    self.custom_logger.info(
                                        "Single seat map found in iframe "
                                        f"({len(seats)} seats)"
                                    )
                                    break

                                human_delay(1, 1.5)

                            if seats:
                                # IMPORTANT:
                                # Stay inside this iframe.
                                # The seat map lives here.
                                self.custom_logger.info(
                                    "Using single-level seat map in iframe"
                                )
                                break

                            # Wrong iframe
                            sb.switch_to_default_content()

                        except Exception:
                            sb.switch_to_default_content()
                except Exception as iframe_err:
                    self.custom_logger.warning("iframe search failed: %s", iframe_err)

            if has_dropdown:
                raw_options = sb.execute_script(
                    """
                    var select = document.querySelector(arguments[0]);
                    if (!select) return [];
                    var options = [];
                    for (var i = 0; i < select.options.length; i++) {
                        options.push(select.options[i].text.trim());
                    }
                    return options;
                    """,
                    dropdown_selector,
                )
                areas = [o for o in raw_options if o and o != "Cornwall Playhouse"]
                self.custom_logger.info("Found dropdown with areas: %s", areas)
            else:
                self.custom_logger.info("No dropdown — using single level seating")
                areas = ["Stalls"]

            prev_seat_count = -1  # sentinel: no area scraped yet

            for area in areas:
                try:
                    self.custom_logger.info("Selecting area: %s", area)

                    if has_dropdown:
                        try:
                            result = sb.execute_script(
                                """
                                var select = document.querySelector(arguments[0]);
                                if (!select) return false;
                                var areaName = arguments[1];
                                for (var i = 0; i < select.options.length; i++) {
                                    if (select.options[i].text.trim() === areaName) {
                                        select.value = select.options[i].value;
                                        select.dispatchEvent(new Event('change', { bubbles: true }));
                                        return true;
                                    }
                                }
                                return false;
                                """,
                                dropdown_selector,
                                area,
                            )
                            if not result:
                                self.custom_logger.warning(
                                    "Could not find area %s in dropdown", area
                                )
                                continue
                            sb.wait_for_ready_state_complete()
                            for _ in range(15):
                                human_delay(2, 3)
                                # Break only when the seat count changes from the
                                # previous area — proving the iframe re-rendered.
                                # Without this check the stale previous-area chart
                                # (still visible during re-render) triggers a false
                                # break and every subsequent area returns wrong data.
                                _cur_count = len(
                                    sb.find_elements(
                                        By.CSS_SELECTOR, SELECTORS["seats"]
                                    )
                                )
                                if _cur_count > 0 and _cur_count != prev_seat_count:
                                    break
                                sb.execute_script("window.scrollTo(0, 300);")
                                human_delay(1, 2)
                                sb.execute_script("window.scrollTo(0, 0);")
                        except Exception as dropdown_error:
                            self.custom_logger.warning(
                                "Failed to select area %s: %s", area, dropdown_error
                            )
                            continue

                    self.custom_logger.info("Scraping seats for: %s", area)

                    # Grab the widget's venue details once, from wherever
                    # we currently are (main page or inside the iframe).
                    if venue_details is None:
                        venue_details = self._get_venue_details_from_page(sb)

                    try:
                        # sb.wait_for_element_present(SELECTORS["seats"], timeout=12)
                        seats = sb.find_elements(SELECTORS["seats"])
                        self.custom_logger.info(f" Found {len(seats)} unique seats. ")

                        area_capacity = len(seats)
                        prev_seat_count = area_capacity  # update for next area
                        perf_capacity += area_capacity

                        self.custom_logger.info(
                            "Area: %s | Total Seats: %s", area, area_capacity
                        )

                        for seat in seats:
                            try:
                                tooltip = (
                                    seat.get_attribute("tooltip")
                                    or seat.get_attribute("title")
                                    or ""
                                )

                                if currency is None and tooltip:
                                    currency = get_currency_from_price(tooltip)

                                if not tooltip or "Unavailable" in tooltip:
                                    continue

                                seat_id = None
                                ticket_price = None

                                # Multi-tier Text Format Parsing ("Seat: A1 Price: £15.00")
                                if "Seat:" in tooltip:
                                    seat_match = re.search(r"Seat:\s*(\S+)", tooltip)
                                    price_match = re.search(
                                        r"Price:\s*[^\d]*([\d,.]+)", tooltip
                                    )
                                    if seat_match and price_match:
                                        seat_id = seat_match.group(1)
                                        ticket_price = float(
                                            price_match.group(1).replace(",", "")
                                        )

                                # Single-tier Clean/Legacy Text Format Parsing ("A1 - £15.00")
                                elif " - " in tooltip:
                                    parts = tooltip.split(" - ")
                                    if len(parts) == 2:
                                        seat_id = parts[0].strip()
                                        price_digits = re.search(r"([\d,.]+)", parts[1])
                                        if price_digits:
                                            ticket_price = float(
                                                price_digits.group(1).replace(",", "")
                                            )

                                # Safeguard: skip processing if data didn't cleanly match either pattern
                                if not seat_id or ticket_price is None:
                                    continue

                                seat_id_ = f"{area} {seat_id}"
                                all_seats[seat_id_] = {
                                    "seat": seat_id_,
                                    "ticket_price": ticket_price,
                                }

                            except Exception as seat_error:
                                self.custom_logger.warning(
                                    "Failed to parse seat: %s", seat_error
                                )
                                continue

                    except Exception as seat_extraction_error:
                        self.custom_logger.error(
                            "Seat extraction error for area %s: %s",
                            area,
                            seat_extraction_error,
                        )
                        continue

                except Exception as area_error:
                    self.custom_logger.warning(
                        "Failed to process area %s: %s", area, area_error
                    )
                    continue

        except Exception as e:
            self.custom_logger.error("Seat map scraping failed: %s", e)
        finally:
            try:
                sb.switch_to_default_content()
            except Exception:
                pass

        seat_list = list(all_seats.values())
        self.custom_logger.info(
            f" Total capacity: {perf_capacity} seats ({len(seat_list)} priced)"
        )

        return (
            seat_list,
            currency,
            (perf_capacity if perf_capacity > 0 else None),
            venue_details,
        )

    def extract_seat_metrics(self, sb, performances):  # Fixed: Indented inside class
        """Extracts seats and pricing from internal ticket frame configurations."""

        seat_pricing = {}

        capacity = None
        currency = None
        venue_details = None
        encountered_no_seatmap = False
        max_seatmap_retries = 3  # Number of retry attempts per performance

        for i, perf in enumerate(performances, start=1):
            key = format_datetime_key(perf["date"], perf["time"])
            if not key:
                continue

            self.custom_logger.info(
                f" [{i}/{len(performances)}] Seats for {perf['date']} {perf['time']}"
            )

            # Confirm if sold out / Performance has no digital booking URL (likely telephone booking)."
            if not self.safe_get(sb, perf["booking_url"]):
                self.custom_logger.info(f"Performance {key} is sold out.")
                seat_pricing[key] = []
                continue

            seat_list = []
            perf_currency = None
            perf_capacity = None
            perf_venue = None
            # -------------------------------------------------------------
            # RETRY LOOP FOR SEAT MAP EXTRACTION
            # -------------------------------------------------------------
            for attempt in range(1, max_seatmap_retries + 1):
                try:
                    self.custom_logger.info(
                        f"Attempt {attempt}/{max_seatmap_retries} extracting seatmap for {key}"
                    )
                    # If this is a retry attempt, refresh/re-navigate to reset the iframe state
                    if attempt > 1:
                        self.safe_get(sb, perf["booking_url"])
                        human_delay(3, 5)

                    human_delay(2, 3)

                    # Try to scrape the seatmap
                    (
                        seat_list,
                        perf_currency,
                        perf_capacity,
                        perf_venue,
                    ) = self.extract_seats(sb)

                    # If seats were found, store results and break the retry loop
                    if seat_list:
                        self.custom_logger.info(
                            f" Successfully extracted {len(seat_list)} seats on attempt {attempt}"
                        )
                        break
                    else:
                        self.custom_logger.warning(
                            f" Attempt {attempt} returned 0 seats for {key}."
                        )

                except Exception as e:
                    self.custom_logger.warning(
                        f" Attempt {attempt} threw an error extracting seatmap: {e}"
                    )
                finally:
                    # Always ensure we clear frame context before the next attempt or iteration
                    try:
                        sb.switch_to_default_content()
                    except Exception:
                        pass

            # -------------------------------------------------------------
            # RECORD RESULTS AFTER RETRIES EXHAUSTED OR SUCCEEDED
            # -------------------------------------------------------------
            if perf_venue and not venue_details:
                venue_details = perf_venue

            if seat_list:
                seat_pricing[key] = seat_list
                currency = perf_currency
                capacity = perf_capacity
                self.custom_logger.info(
                    f" Seats: {len(seat_list)} | Capacity: {capacity} | Currency: {currency}"
                )
            else:
                seat_pricing[key] = []
                encountered_no_seatmap = True
                self.custom_logger.info(
                    f" No seat map available for {perf['date']} {perf['time']} after {max_seatmap_retries} attempts."
                )

            human_delay(3, 5)

        if encountered_no_seatmap and all(
            len(seat_list) == 0 for seat_list in seat_pricing.values()
        ):
            self.custom_logger.info(
                " All performances lack a seat map layout. Resetting seat_pricing = {}"
            )
            seat_pricing = {}

        self.custom_logger.info(" Seat extraction flow processed")
        return seat_pricing, currency, capacity, venue_details

    def _scrape_one_show(self, sb, show_url: str, category: str) -> dict | None:
        """Scrape a single show page end-to-end.

        Returns a completed row dict on success, or None if the show page
        did not render (bot challenge, timeout) — the caller retries.
        """

        if not self.safe_get(sb, show_url):
            return None

        title = self._get_show_title(sb)
        if not title:
            self.custom_logger.warning("No title found for: %s", show_url)

        venue_url = sb.get_current_url()
        self.custom_logger.info("venue_url: %s", venue_url)

        open_date, close_date = None, None
        terminal_date = self._get_terminal_dates(sb)
        if terminal_date:
            match = re.match(
                r"^(\d+)\s*-\s*(\d+)\s+([A-Za-z]+)\s+(\d{4})$", terminal_date.strip()
            )
            if match:
                day_start, day_end, month, year = match.groups()
                terminal_date = f"{day_start} {month} {year} - {day_end} {month} {year}"
            try:
                booking_dates = parse_booking_dates(terminal_date)
                open_date = booking_dates.get("start_date")
                close_date = booking_dates.get("end_date")
            except Exception as e:
                self.custom_logger.warning(
                    f"Shared parse_booking_dates utility failed: {e}"
                )

        # Event-specific alternate venue named in the show's own description
        # text (e.g. "Please note this performance takes place at Treviglas
        # Academy Sports Hub") -- computed early since some of these shows
        # have no Spektrix seat map at all, so the live widget scrape below
        # never gets a chance to run. Takes priority over everything else:
        # it's explicit evidence this particular show isn't at Hall for
        # Cornwall itself.
        event_venue = self._get_event_venue(sb)

        self.accept_cookies(sb)
        human_delay(2, 4)

        self.custom_logger.info("Category: %s", category)
        self.custom_logger.info("Title: %s", title)
        self.custom_logger.info("Terminal: %s", terminal_date)

        self.custom_logger.info("Open Date: %s", open_date)
        self.custom_logger.info("Close Date: %s", close_date)
        self.custom_logger.info("-" * 50)

        human_delay(10, 12.5)
        human_scroll(sb)
        time.sleep(3)

        performances = self._extract_performances(sb)
        if not performances:
            self.custom_logger.warning(
                f"  No performances found for '{title}', skipping"
            )
            return None

        sorted_dates = sorted([p["date"] for p in performances])
        if not open_date:
            open_date = sorted_dates[0]

        if not close_date:
            close_date = sorted_dates[-1]

        if open_date > close_date:
            self.custom_logger.warning(
                "  Open date %s is after close date %s. Adjusting open date to performance.",
            )
            open_date = sorted_dates[0]

        (
            seat_pricing,
            currency,
            capacity,
            scraped_venue_details,
        ) = self.extract_seat_metrics(sb, performances)

        # Priority: explicit alternate-venue text on the show's own page >
        # venue/address scraped live from the Spektrix booking widget >
        # hardcoded default (only if neither source produced anything, e.g.
        # every performance was sold out/unbookable so no booking page was
        # ever visited). Deliberately `.get(key) or default`, not
        # `.get(key, default)`: a scraped dict can carry an explicit None
        # for city/country (no postcode found in the widget's address),
        # which `dict.get`'s default only covers when the key is missing
        # entirely.
        venue_details = event_venue or scraped_venue_details or DEFAULT_THEATRE_DETAILS
        venue_name = venue_details.get("venue") or DEFAULT_THEATRE_DETAILS["venue"]
        address = venue_details.get("address") or DEFAULT_THEATRE_DETAILS["address"]
        city = venue_details.get("city") or DEFAULT_THEATRE_DETAILS["city"]
        country = normalize_country(
            venue_details.get("country") or DEFAULT_THEATRE_DETAILS["country"]
        )

        self.custom_logger.info(
            "Performances: %d | Seat keys: %d",
            len(performances),
            len(seat_pricing),
        )
        self.custom_logger.info("Venue: %s", venue_name)
        self.custom_logger.info("Address: %s", address)
        self.custom_logger.info("City: %s", city)
        self.custom_logger.info("Country: %s", country)
        self.custom_logger.info("Capacity: %s", capacity)
        self.custom_logger.info("Currency: %s", currency)

        return {
            "title": title,
            "category": standardize_category(category),
            "venue": venue_name,
            "venue_url": venue_url,
            "address": address,
            "city": city,
            "country": country,
            "open_date": open_date,
            "close_date": close_date,
            "booking_start_date": None,
            "booking_end_date": close_date,
            "upcoming_performances": [
                {"date": p["date"], "time": p["time"]} for p in performances
            ],
            "seat_pricing": seat_pricing,
            "capacity": int(capacity) if capacity is not None else None,
            "currency": currency or DEFAULT_CURRENCY,
            "is_limited_run": bool(open_date or close_date),
            "scrape_datetime": get_scrape_datetime(),  # datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def _scrape_shows(self, sb, show_links: list, category: str) -> None:
        """Scrape individual show pages with multi-pass retry (Denver pattern)."""
        _MAX_PASSES = 3
        pending = list(show_links)

        for _pass in range(1, _MAX_PASSES + 1):
            if not pending:
                break

            self.custom_logger.info(
                "Show pass %d/%d — %d show(s)", _pass, _MAX_PASSES, len(pending)
            )
            still_pending = []

            for show_url in pending:
                row = self._scrape_one_show(sb, show_url, category)
                if row is None:
                    still_pending.append(show_url)
                    self.custom_logger.warning(
                        "Pass %d: show deferred — %s", _pass, show_url
                    )
                else:
                    self.all_data.append(row)
                    self.log_record(row)
                    human_delay(8, 15)

            pending = still_pending

            if pending and _pass < _MAX_PASSES:
                self.custom_logger.info(
                    "Pass %d complete — %d show(s) still pending. "
                    "Cooling down before pass %d",
                    _pass,
                    len(pending),
                    _pass + 1,
                )
                human_scroll(sb)
                human_delay(60, 120)

        if pending:
            self.custom_logger.warning(
                "%d show(s) could not be scraped after %d passes: %s",
                len(pending),
                _MAX_PASSES,
                pending,
            )

    def extract(self) -> bytes:
        """Open SB session, scrape all shows, populate self.all_data, return JSON bytes."""
        self.all_data = []
        seen_links = set()

        with SB(
            uc=True,
            test=True,
            headless=True,
            browser="chrome",
            locale="en-US",
            chromium_arg="--enable-features=TranslateUI",
        ) as sb:
            self.custom_logger.info("Starting extraction from hallforcornwall")

            for i, (url, category) in enumerate(PAGES):
                self.custom_logger.info(f"[Listing] {category}: {url}")
                if not self.safe_get(sb, url):
                    continue

                human_delay(4, 6)
                sb.maximize_window()
                self.accept_cookies(sb)

                # Get links and filter out duplicates in one step
                raw_links = ["https://www.hallforcornwall.co.uk/whats-on/rsc-first-encounters-julius-caesar/#"]
                #raw_links = ["https://www.hallforcornwall.co.uk/whats-on/rsc-first-encounters-julius-caesar/#"]
                #raw_links = self.get_show_links(sb)
                show_links = [link for link in raw_links if link not in seen_links]
                seen_links.update(show_links)

                if self.local_test:
                    self.custom_logger.info(
                        "LOCAL TEST MODE: Limiting to %s shows", self.show_count
                    )
                    show_links = show_links[: self.show_count]

                self._scrape_shows(sb, show_links, category)

        # Deduplicate extracted rows by (title, venue)
        deduped_data = []
        seen_keys = set()

        for row in self.all_data:
            key = (row.get("title"), row.get("venue"))
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_data.append(row)
            else:
                self.custom_logger.warning(f"Dropped duplicate row for key: {key}")

        self.all_data = deduped_data

        return json.dumps(self.all_data, default=str).encode("utf-8")

    def _parse(self, _raw: bytes):
        """Build DataFrame from self.all_data collected during extract()."""
        df = pd.DataFrame(self.all_data)
        if "capacity" in df.columns:
            df["capacity"] = df["capacity"].astype("Int64")
        self.custom_logger.info("Parsing completed. Extracted %s shows", len(df))
        return df

    def _transform_to_uniform_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Same as BaseExtractor, but keeps `capacity` a real nullable int.

        BaseExtractor's implementation rebuilds the DataFrame from Event
        dataclass instances via `pd.DataFrame(events)` -- pandas infers
        float64 for the `capacity` column whenever any row's capacity is
        None (89 -> 89.0, blank rows -> NaN), which then round-trips into
        the saved CSV as "89.0" instead of "89". Recast to pandas'
        nullable Int64 right after so this scraper's CSV keeps real
        integers, without changing behavior for any other scraper.
        """
        result = super()._transform_to_uniform_schema(df)
        if "capacity" in result.columns:
            result["capacity"] = result["capacity"].astype("Int64")
        return result


def main():
    """Example usage of the hallforcornwall extractor."""
    extractor = HallforcornwallExtractor(
        save_csv_locally=False, csv_incremental_mode=False
    )
    result = extractor.run()
    logger.info(f"Extraction result: {result}")
    if result.get("status") not in ("success", "validation_failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
