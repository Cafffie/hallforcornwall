"""Configuration for Hallforcornwall Theatre scraper."""

SITE_ID = "hall_for_cornwall"
BASE_URL = "https://www.hallforcornwall.co.uk/"
RUN_HEADLESS = True
DEFAULT_CURRENCY = "GBP"

PAGES = [
    (f"{BASE_URL}whats-on/?category=plays-drama", "Play"),
    (f"{BASE_URL}whats-on/?category=musical-theatre", "Musical"),
    (f"{BASE_URL}whats-on/?category=christmas-show", "Musical"),
    (f"{BASE_URL}whats-on/?category=christmas-show", "Musical"),
]

COOKIE_BTN_XPATH = (
    "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']"
)

ADDRESS_URL = "https://www.hallforcornwall.co.uk/visiting-us/"

DEFAULT_THEATRE_DETAILS = {
    "venue": "Cornwall Play House",
    "address": "Hall for Cornwall, Back Quay, Truro TR1 2LL",
    "city": "Truro",
    "country": "UK",
}

VENUE_MAP = {
    "princess pavilion": {
        "venue": "Princess Pavilion",
        "address": None,
        "city": "Falmouth",
        "country": "United Kingdom",
    },

    "truro school concert hall": {
        "venue": "Truro School Concert Hall",
        "address": None,
        "city": "Truro",
        "country": "United Kingdom",
    },

    "truro school": {
        "venue": "Truro School",
        "address": None,
        "city": "Truro",
        "country": "United Kingdom",
    },
}

SELECTORS = {
    "cookie_button": "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']",
    "theatre_address_xpath": "//h2[normalize-space()='Address']/following-sibling::p[1]",
    "shows_link": ".WhatsonItem .WhatsOnDateBnt a:first-of-type",
    "title": ".whatson-event-detailsHeading-title h1",
    "terminal_date": ".EventDetailHeading_row span.EventpostDate",
    "event_description": "div.whatson-event-details-content",
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
