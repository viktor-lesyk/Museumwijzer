"""Acceptance tests for Phase 2 MVP static site.

Validates Acceptance Criteria 1, 2, 3, 5, 6, 10 from museumwijzer-requirements.md.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
import yaml

SITE_DIST = Path(__file__).resolve().parent.parent / "site" / "dist"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class MuseumListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.current_card = None
        self.in_card_title = False
        self.current_title = ""

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = (attr_dict.get("class") or "").split()
        if tag == "article" and "museum-card" in classes:
            self.current_card = {
                "slug": attr_dict.get("data-slug", ""),
                "name": attr_dict.get("data-name", ""),
                "province": attr_dict.get("data-province", ""),
                "city": attr_dict.get("data-city", ""),
                "aliases": attr_dict.get("data-city-aliases", ""),
                "street": attr_dict.get("data-street", ""),
                "postcode": attr_dict.get("data-postcode", ""),
            }
        elif self.current_card is not None and tag == "h2" and "card-title" in classes:
            self.in_card_title = True
            self.current_title = ""

    def handle_endtag(self, tag):
        if tag == "article" and self.current_card is not None:
            self.cards.append(self.current_card)
            self.current_card = None
        elif tag == "h2" and self.in_card_title:
            self.in_card_title = False
            if self.current_card is not None and not self.current_card["name"]:
                self.current_card["name"] = self.current_title.strip()

    def handle_data(self, data):
        if self.in_card_title:
            self.current_title += data


def normalize_search(s: str) -> str:
    if not s:
        return ""
    normalized = unicodedata.normalize("NFD", s.lower())
    without_diacritics = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return without_diacritics.strip()


def simulate_client_search(cards, query: str, city_aliases_map: dict):
    norm_query = normalize_search(query)
    # resolve alias for query
    query_alias = norm_query
    for alias, canonical in city_aliases_map.items():
        if normalize_search(alias) == norm_query:
            query_alias = normalize_search(canonical)
            break

    matches = []
    for card in cards:
        name = normalize_search(card["name"])
        city = normalize_search(card["city"])
        aliases = normalize_search(card["aliases"])
        province = card["province"].lower()
        street = normalize_search(card["street"])
        postcode = normalize_search(card["postcode"])

        is_match = (
            not norm_query
            or norm_query in name
            or query_alias in name
            or norm_query in city
            or query_alias in city
            or norm_query in aliases
            or query_alias in aliases
            or norm_query in province
            or norm_query in street
            or norm_query in postcode
        )
        if is_match:
            matches.append(card)
    return matches


def get_parsed_cards(lang="nl"):
    html_file = SITE_DIST / lang / "index.html"
    assert html_file.exists(), f"Static build output missing: {html_file}"
    content = html_file.read_text(encoding="utf-8")
    parser = MuseumListParser()
    parser.feed(content)
    return parser.cards


def load_city_aliases():
    aliases_file = DATA_DIR / "city-aliases.yaml"
    with open(aliases_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def test_ac5_full_list_readable_without_javascript():
    """AC 5: With JavaScript disabled, the full list of museums is readable in raw HTML."""
    with open(DATA_DIR / "museums.json", encoding="utf-8") as f:
        expected_count = len([m for m in json.load(f)["museums"] if not m.get("duplicate_of") and m.get("status") != "removed"])
    for lang in ("nl", "en"):
        cards = get_parsed_cards(lang)
        assert len(cards) == expected_count, f"Expected {expected_count} cards in {lang} static HTML, found {len(cards)}"
        for card in cards:
            assert card["slug"], "Card missing slug"
            assert card["name"], "Card missing name"
            assert card["province"], f"Card {card['slug']} missing province"


def test_ac1_diacritic_and_case_insensitive_search():
    """AC 1: Searching 'zypendaal', 'Zypendaal' and 'zypendaál' returns Huis Zypendaal."""
    cards = get_parsed_cards("nl")
    aliases = load_city_aliases()

    for variant in ("zypendaal", "Zypendaal", "zypendaál", "ZYPENDAAL"):
        results = simulate_client_search(cards, variant, aliases)
        matched_slugs = [r["slug"] for r in results]
        assert "huis-zypendaal" in matched_slugs, f"Failed to match {variant}"
        assert len(results) == 1, f"Expected exactly 1 match for {variant}, got {len(results)}"


def test_ac2_city_search_and_aliases():
    """AC 2: Searching a city name returns all museums in that city, including via aliases (e.g. 'Den Haag')."""
    cards = get_parsed_cards("nl")
    aliases = load_city_aliases()

    # In data, Hague museums have city "'s-Gravenhage"
    hague_canonical = simulate_client_search(cards, "'s-Gravenhage", aliases)
    assert len(hague_canonical) == 13, f"Expected 13 museums in 's-Gravenhage, got {len(hague_canonical)}"

    # Via alias "Den Haag"
    hague_alias_nl = simulate_client_search(cards, "Den Haag", aliases)
    assert len(hague_alias_nl) == 13, f"Expected 13 museums via alias 'Den Haag', got {len(hague_alias_nl)}"

    # Via English alias "The Hague"
    hague_alias_en = simulate_client_search(cards, "The Hague", aliases)
    assert len(hague_alias_en) == 13, f"Expected 13 museums via alias 'The Hague', got {len(hague_alias_en)}"

    # Via partial alias "Haag"
    hague_partial = simulate_client_search(cards, "Haag", aliases)
    assert len(hague_partial) >= 13, f"Expected at least 13 museums for 'Haag', got {len(hague_partial)}"

    # Via alias "Den Bosch" -> 's-Hertogenbosch
    bosch_alias = simulate_client_search(cards, "Den Bosch", aliases)
    bosch_canonical = simulate_client_search(cards, "'s-Hertogenbosch", aliases)
    assert len(bosch_alias) > 0, "Expected museums for 'Den Bosch'"
    assert len(bosch_alias) == len(bosch_canonical), "Den Bosch matches must equal 's-Hertogenbosch matches"


def test_ac3_not_found_messaging():
    """AC 3: A museum not in the data yields 'Not found in the current list (updated <date>)'

    with a link to the official list, and never a claim that it does not participate.
    """
    cards = get_parsed_cards("nl")
    aliases = load_city_aliases()

    results = simulate_client_search(cards, "Louvre Museum Paris", aliases)
    assert len(results) == 0, "Expected 0 results for non-existent museum"

    # Check the static HTML template for not-found box
    html_nl = (SITE_DIST / "nl" / "index.html").read_text(encoding="utf-8")
    assert "not-found-box" in html_nl
    assert "not-found-title" in html_nl

    # Check for presence of updated date in not-found banner
    assert "Niet gevonden in de huidige lijst (bijgewerkt:" in html_nl

    # Check for link to official list
    assert "https://welkominhetmuseum.vriendenloterij.nl/nl/deelnemende-musea/" in html_nl

    # Never claim that the museum does not participate
    assert "doet niet mee" not in html_nl.lower()
    assert "does not participate" not in html_nl.lower()


def test_ac6_no_third_party_requests():
    """AC 6: No network requests to third-party domains occur during normal use (automated check)."""
    # Scan all HTML and CSS files in dist
    html_and_css_files = list(SITE_DIST.rglob("*.html")) + list(SITE_DIST.rglob("*.css"))
    assert len(html_and_css_files) > 0

    external_resource_regex = re.compile(
        r'<(?:script|link\s+[^>]*rel=["\']stylesheet["\']|img)[^>]+(?:src|href)=["\'](https?://[^"\']+)["\']',
        re.IGNORECASE,
    )
    css_url_regex = re.compile(r'url\(["\']?(https?://[^"\')]+)["\']?\)', re.IGNORECASE)

    violations = []
    for file_path in html_and_css_files:
        content = file_path.read_text(encoding="utf-8")
        for match in external_resource_regex.finditer(content):
            url = match.group(1)
            violations.append((file_path.name, url))
        for match in css_url_regex.finditer(content):
            url = match.group(1)
            violations.append((file_path.name, url))

    assert not violations, f"Third-party external asset requests found: {violations}"


def test_ac10_disclaimer_attribution_and_last_updated():
    """AC 10: Every page shows the disclaimer, attribution and last-updated date."""
    # Check sample of pages: Finder (nl/en), About (nl/en), and 5 detail pages
    sample_pages = [
        SITE_DIST / "nl" / "index.html",
        SITE_DIST / "en" / "index.html",
        SITE_DIST / "nl" / "about" / "index.html",
        SITE_DIST / "en" / "about" / "index.html",
        SITE_DIST / "nl" / "museum" / "huis-zypendaal" / "index.html",
        SITE_DIST / "en" / "museum" / "huis-zypendaal" / "index.html",
        SITE_DIST / "nl" / "museum" / "rijksmuseum" / "index.html",
        SITE_DIST / "nl" / "museum" / "van-gogh-museum" / "index.html",
        SITE_DIST / "nl" / "museum" / "anne-frank-huis" / "index.html",
    ]

    for page in sample_pages:
        assert page.exists(), f"Page missing: {page}"
        html = page.read_text(encoding="utf-8")

        # Disclaimer
        assert (
            "Dit is een onafhankelijke, onofficiële website" in html
            or "This is an independent, unofficial website" in html
        ), f"Missing disclaimer in {page.name}"

        # Attribution
        assert "PDOK" in html and "Kadaster" in html, f"Missing PDOK attribution in {page.name}"

        # Last updated date
        assert (
            "Laatst bijgewerkt:" in html or "Last updated:" in html
        ), f"Missing last-updated date in {page.name}"
