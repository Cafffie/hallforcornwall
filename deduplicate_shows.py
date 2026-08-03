import json

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
        sb.maximize_window()
        self.custom_logger.info("Starting extraction from Leicester Curve")

        for url, category in PAGES:
            self.custom_logger.info(f"[Listing] {category}: {url}")
            if not self.safe_get(sb, url):
                continue

            human_delay(4, 6)
            sb.maximize_window()
            self.accept_cookies(sb)

            # Get links and filter out duplicates in one step
            raw_links = self.get_show_links(sb)
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
