"""Configuration for Curve Online Theatre scraper."""

SITE_ID = "hall_for_cornwall"
BASE_URL = "https://www.hallforcornwall.co.uk/"
RUN_HEADLESS = True
DEFAULT_CURRENCY = "GBP"

PAGES = [
    (f"{BASE_URL}whats-on/?category=musical-theatre", "Musical"),
    (f"{BASE_URL}whats-on/?category=plays-drama", "Play"),
]

COOKIE_BTN_XPATH = (
    "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']"
)

address_url = "https://www.hallforcornwall.co.uk/visiting-us/"

DEFAULT_THEATRE_DETAILS = {
    "venue": "Hall for Cornwall",
    "address": "Hall for Cornwall, Back Quay, Truro TR1 2LL",
    "city": "Back Quay",
    "country": "UK",
}

SELECTORS = {
    "cookie_button": "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']",
    "theatre_address_xpath": "//h2[normalize-space()='Address']/following-sibling::p[1]",
    #"address_header_xpath": "//p[contains(@class, 'h4') and contains(text(), 'Address')]",
    #"address_paragraph_xpath": "/following-sibling::p",
    #"shows_cards": "article.listing__item",
    #"shows_link": "article.grid__cell a",
    "title": "li.WhatsonItem h3 a",
    "terminal_date": ".EventDetailHeading_row span.EventpostDate",
    #"venue_url": "article.listing__item a",
    "first_book_btn": ".BannerBookBtn",
    "date_blocks": "tbody tr",
    "booking_url": ".BookingList_btn a",
    "raw_date_text": ".row_date",
    "raw_time_text": ".row_time",
    "seating_dropdown": "select[id*='AvailableAreas']",
    "iframe": "#SpektrixIFrame",
    "seats": "div.SeatingArea img[class*='Seat'], rect.seat",
    "available_seats": "img[class*='Seat']",
}

# 1. Click the dropdown itself to "open" it / focus it
sb.click("#ctl00_ContentPlaceHolder_AvailableAreas")

# 2. Select your option
sb.select_option_by_text("#ctl00_ContentPlaceHolder_AvailableAreas", "Balcony")
