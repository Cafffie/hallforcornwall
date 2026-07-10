import re
import os
import time
import logging
import pandas as pd
from datetime import datetime, date
from dateutil import parser

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import undetected_chromedriver as uc

# ============================================================
# CONFIG & LOGGING
# ============================================================
RUN_HEADLESS = False
OUTPUT_FILE = "hallforcornwall_shows.csv"
PAGES = [
    ("https://www.hallforcornwall.co.uk/whats-on/?category=musical-theatre", "Musical"),
    ("https://www.hallforcornwall.co.uk/whats-on/?category=plays-drama", "Plays")
]

if not os.path.exists("log"):
    os.makedirs("log")

logging.basicConfig(
    filename="log/scrape.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def log(msg, level="info"):
    print(f"[LOG] {msg}")
    if level == "error": logging.error(msg)
    elif level == "warning": logging.warning(msg)
    else: logging.info(msg)


# ============================================================
# BROWSER SETUP
# ============================================================
def setup_browser():
    log("🚀 Starting browser...")
    options = uc.ChromeOptions()
    if RUN_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options, version_main=148)
    driver.implicitly_wait(10)
    return driver


def safe_get(driver, url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            log(f"🌍 Loading page ({attempt}/{retries}): {url}")
            driver.get(url)
            return True
        except Exception as e:
            log(f"❌ Load failed: {e}", "error")
            time.sleep(2)
    return False


def handle_cookies(driver):
    try:
        # Hall for Cornwall uses CookieYes banner based on the HTML
        cookie_btn_selector = "#cky-btn-accept, .cky-btn-accept"
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, cookie_btn_selector))
        )
        driver.find_element(By.CSS_SELECTOR, cookie_btn_selector).click()
        log("Cookies accepted.")
        time.sleep(1)
    except TimeoutException:
        pass


def scroll_to_load_all(driver):
    log("⬇️ Scrolling page...")
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    log("✅ Finished scrolling")


def _parse_date(text: str) -> str | None:
    try:
        # Clean text first in case of date ranges
        text = text.split("-")[0].strip() 
        dt = parser.parse(text, dayfirst=True, fuzzy=True)
        if dt.date() < date.today():
            dt = dt.replace(year=dt.year + 1)
        return dt.strftime("%Y-%m-%d")
    except Exception as e:
        log(f"_parse_date failed for '{text}': {e}")
        return None


# ============================================================
# 1. VENUE DETAILS FUNCTION
# ============================================================
def _get_venue_details(driver) -> dict:
    """Return static venue details as the footer isn't present in the provided HTML context."""
    data = {
        "venue": None,
        "address": None,
        "city": None,
        "country": "UK"
    }
    visiting_url = "https://www.hallforcornwall.co.uk/visiting-us/"
    
    if not safe_get(driver, visiting_url):
        return data

    handle_cookies(driver)

    try:
        # Locate the <p> tag that directly follows the <h2>Address</h2> header
        #address_element = driver.find_element(
        #    By.XPATH, "//h2[normalize-space()='Address']/following-sibling::p[1]"
        #)
        # Locate the <p> tag following the <h2>Address</h2> header
        address_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//h2[normalize-space()='Address']/following-sibling::p[1]"))
        )
        
        # Extract and clean the text
        full_address = address_element.text.strip()
        log(f"📍 Successfully found address: {full_address}")
        
        # Hall for Cornwall, Back Quay, Truro TR1 2LL
        parts = [part.strip() for part in full_address.split(",")]
        if len(parts) >= 3:
            data["venue"] = parts[0]
            data["address"] = parts[1]
            # Splits 'Truro TR1 2LL' into city and postcode
            city_postcode = parts[2].rsplit(" ", 2) 
            data["city"] = city_postcode[0]
            data["postcode"] = ' '.join(city_postcode[1:])

    except Exception as e:
        print(f"Could not extract the address: {e}")
    
    return data


# ============================================================
# 2. EVENT LIST SELECTION
# ============================================================
def _extract_event_list(driver, category: str) -> list[dict]:
    """
    Parses individual cards inside the main events list.
    Since the actual event list container content was truncated in the HTML snippet, 
    we target the expected class wrapper and provide fallback selectors mapping to the slider.
    """
    shows = []
    
    # Wait for either the event list wrapper or the slider (as fallback)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "ul#gridview-new li.WhatsonItem")
            )
        )
    except Exception as e:
        log("  No event wrapper found on listing page")
        return []

    # Attempt to find standard event cards (Update these classes based on live site)
    shows_cards = driver.find_elements(By.CSS_SELECTOR, "ul#gridview-new li.WhatsonItem")
    log(f"📦 Found {len(shows_cards)} show cards")

    for item in shows_cards:
        try:
            # Using selectors matching the slider items as reliable fallbacks
            title_element = item.find_element(By.CSS_SELECTOR, "h3 a")
            title = title_element.get_attribute("textContent").strip()
            link = title_element.get_attribute("href")

            # Avoid duplicates if slider has cloned elements
            if any(show['title'] == title for show in shows):
                continue

            shows.append({
                "title": title,
                "event_url": link,
                "category": category
            })
        except Exception:
            continue
            
    return shows


# ============================================================
# 3. PERFORMANCE TIMELINE PROCESSING
# ============================================================
def _extract_performances(driver) -> list[dict]:
    """
    Parses performance instances row-by-row.
    NOTE: The event detail page HTML was not provided. These are assumed generic selectors.
    You will need to update them to match the Hall for Cornwall event page DOM.
    """
    performances = []

    # Try clicking a 'Book' tab or button if performances are hidden behind a modal (common for Spektrix)
    try:
        first_book_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".BannerBookBtn"))
        )
        driver.execute_script("arguments[0].click();", first_book_btn)
        time.sleep(2)
        log("✅ 'First Book' button clicked successfully.")
    except Exception as e:
        log(f"  Error finding first booking button: {e}")
        return []

    try:
        year_el = driver.find_element(By.CSS_SELECTOR, ".EventDetailHeading_row span.EventpostDate").get_attribute("textContent").strip()
        year = re.search(r"\b\d{4}\b", year_el)
        log(f"📦 Found year: {year}")
    except:
        log(f" year el not found")
        year = None

    # Wait for the performance details block to load
    try:
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
   
        rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
        log(f"📦 Found {len(rows)} performance dates")

        for row in rows:
            try:
                # Update these selectors based on the live detail page
                date_element = row.find_element(By.CSS_SELECTOR, ".row_date").get_attribute("textContent").strip()
                time_element = row.find_element(By.CSS_SELECTOR, ".row_time").get_attribute("textContent").strip()
                
                try:
                    book_link_el = row.find_element(By.CSS_SELECTOR, ".BookingList_btn a")
                    book_link = book_link_el.get_attribute("href")
                except:
                    book_link = None

                date_string = f"{date_element} {year.group(0)} {time_element}"
                #log(f"📦 date_string: {date_string}")
                parsed_dt = parser.parse(date_string)

                parsed_date = parsed_dt.strftime("%Y-%m-%d") if year else None
                perf_time = parsed_dt.strftime("%H:%M")
                if not parsed_date or not time_element:
                    continue
                
                performances.append({
                    "date": parsed_date,
                    "time": perf_time,
                    "booking_url": book_link
                })
            except Exception:
                continue

    except Exception as e:
        log(f"  Error extracting performances or elements not found (Update selectors): {e}")           
    
    return performances

# ============================================================
# SEAT PRICING
# ============================================================
def extract_all_seats(driver, performances):
    """Extracts seats and pricing from internal ticket frame configurations."""
    
    seat_pricing = {}
    currency = None
    
    for i, perf in enumerate(performances, start=1):
        try:
            start = time.time()
            log(f"   🔄 [{i}/{len(performances)}] {perf['date']} {perf['time']}")

            driver.get(perf["booking_url"])

            try:
                iframe = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.ID, "SpektrixIFrame"))
                )
                log(f"iframe found: {iframe.get_attribute('id')}")
                driver.switch_to.frame(iframe)
                
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.SeatingArea img, rect.seat"))
                )

                seats = driver.find_elements(By.CSS_SELECTOR, "div.SeatingArea img[class*='Seat'], rect.seat")
                log(f"📦 Found {len(seats)} unique seats. ")
            except Exception as e:
                log(f"seats not found : {e}", "warning")

            seat_list = []
            for seat in seats:
                tooltip = seat.get_attribute("tooltip") or seat.get_attribute("title") or ""
                
                detected_currency = detect_currency(tooltip)
                if detected_currency and currency is None:
                    currency = detected_currency

                if not tooltip:
                    continue

                match = re.search(r"([A-Z]+\d+)\s*-\s*£?([\d,.]+)", tooltip)
                if not match:
                    continue
                seat_id = match.group(1)
                ticket_price = float(match.group(2).replace(",", ""))

                seat_list.append({
                    "seat": seat_id,
                    "ticket_price": ticket_price
                })

            perf["capacity"] = len(seats) if seats else None
            key = f"{perf['date']} {perf['time']}"
            seat_pricing[key] = seat_list

            log(f" ✅ Seat lists: {len(seat_list)} | Time: {round(time.time()-start,2)}s")

        except Exception as e:
            log(f"❌ Seat extraction skipped or unavailable for current iframe context: {e}", "warning")
            perf["capacity"] = None
        finally:
            try:
                driver.switch_to.default_content()
            except:
                pass

    log("✅ Seat extraction flow processed")
    return seat_pricing, currency


# ============================================================
# MAIN APPLICATION FLOW
# ============================================================
def scrape_shows():
    log("🚀 SCRAPER STARTED")

    driver = setup_browser()
    all_rows = []
    # STEP 1: Grab address details right at the start before looping
    venue_details = _get_venue_details(driver)

    try:
        for page_idx, (url, category) in enumerate(PAGES, start=1):
            log(f"\n🌍 CATEGORY CORRELATION {page_idx}/{len(PAGES)} → {category}")

            if not safe_get(driver, url):
                continue

            handle_cookies(driver)
            scroll_to_load_all(driver)

            shows = _extract_event_list(driver, category)

            for i, show in enumerate(shows, start=1):
                log(f"\n🎭 EVENT SPECIFIC EXTRACTION {i}/{len(shows)} → {show['title']}")

                if not safe_get(driver, show["event_url"]):
                    continue

                handle_cookies(driver)
                scroll_to_load_all(driver)
                scrape_dt = datetime.now().strftime("%Y-%m-%d %H:%M")

                raw_performances = _extract_performances(driver)
                
                if not raw_performances:
                    log(f"⚠️ No active performances extracted for '{show['title']}'. Ensure detail page selectors are correct.")

                dates = [p["date"] for p in raw_performances if p.get("date")]
                open_date = min(dates) if dates else ""
                close_date = max(dates) if dates else ""

                formatted_performances = str([
                    {"date": p["date"], "time": p["time"]} for p in raw_performances
                ])

                seat_pricing, currency, venue_details = extract_all_seats(driver, raw_performances)
                formatted_seat_pricing = repr(seat_pricing) if seat_pricing else "{}"

                capacity = max([p.get("capacity", 0) for p in raw_performances], default=0)          

                row = {
                    "title": show["title"],
                    "venue_url": show["event_url"],
                    "category": show["category"],
                    "venue": venue_details["venue"],
                    "address": venue_details["address"],
                    "city": venue_details["city"],
                    "country": venue_details["country"],
                    "open_date": open_date,
                    "close_date": close_date,
                    "booking_start_date": open_date,
                    "booking_end_date": close_date,
                    "upcoming_performances": formatted_performances if raw_performances else "[]",
                    "capacity": ,
                    "currency":  "GBP",
                    "is_limited_run": ,
                    "seat_pricing": ,
                    "scrape_datetime": scrape_dt
                }
                all_rows.append(row)
                log(f"✅ Extracted Row Record Saved: {show['title']}")

    except Exception as e:
        log(f"⚠️ Error occurred while scraping shows: {e}", "warning")

    finally:
        driver.quit()
        log("🛑 Browser processes completely shut down.")

    # Build CSV in strict canonical order
    canonical_columns = [
        "title", "venue_url", "category", "venue", "address", "city", "country",
        "open_date", "close_date", "booking_start_date", "booking_end_date",
        "upcoming_performances", "capacity", "currency", "is_limited_run",
        "seat_pricing", "scrape_datetime"
    ]

    if all_rows:
        df = pd.DataFrame(all_rows)
        df = df.reindex(columns=canonical_columns)
    else:
        df = pd.DataFrame(columns=canonical_columns)

    df.to_csv(OUTPUT_FILE, index=False)
    log(f"✅ Scraped data saved to: {OUTPUT_FILE} ({len(df)} lines generated).")


if __name__ == "__main__":
    scrape_shows()
