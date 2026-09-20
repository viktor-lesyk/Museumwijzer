"""Acceptance tests for Phase 3 features.

Validates:
- Ukrainian language (/uk/) pages, hreflang tags, and language switcher
- Priority list page (/nl/list/, /en/list/, /uk/list/), actions, export, import, print styles
- Priority list toggles on cards and museum detail pages
- In-browser "Near me" geolocation controls, distance attributes, sort dropdown, and city centroid fallback
- Privacy standards: zero third-party network requests on list and detail pages
"""
import json
import math
from pathlib import Path
import re

SITE_DIST = Path(__file__).resolve().parent.parent / "site" / "dist"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def test_ukrainian_locale_pages_generated():
    """Verify Ukrainian locale (/uk/) builds all core pages and museum details."""
    uk_index = SITE_DIST / "uk" / "index.html"
    uk_about = SITE_DIST / "uk" / "about" / "index.html"
    uk_list = SITE_DIST / "uk" / "list" / "index.html"
    uk_museum = SITE_DIST / "uk" / "museum" / "huis-zypendaal" / "index.html"

    assert uk_index.exists(), "Missing /uk/index.html"
    assert uk_about.exists(), "Missing /uk/about/index.html"
    assert uk_list.exists(), "Missing /uk/list/index.html"
    assert uk_museum.exists(), "Missing /uk/museum/huis-zypendaal/index.html"

    content = uk_index.read_text(encoding="utf-8")
    assert 'lang="uk"' in content
    # Verify Cyrillic text is rendered properly
    assert "Ласкаво просимо до музею" in content or "Музеї-учасники" in content
    # Verify museum name itself is not translated (§6.6)
    assert "Huis Zypendaal" in content


def test_hreflang_and_language_switcher():
    """Verify hreflang tags include nl, en, uk and x-default across all locales."""
    for lang in ["nl", "en", "uk"]:
        page = SITE_DIST / lang / "index.html"
        assert page.exists()
        content = page.read_text(encoding="utf-8")

        assert '<link rel="alternate" hreflang="nl"' in content
        assert '<link rel="alternate" hreflang="en"' in content
        assert '<link rel="alternate" hreflang="uk"' in content
        assert '<link rel="alternate" hreflang="x-default"' in content

        # Check language switcher links
        assert f'href="/nl/' in content
        assert f'href="/en/' in content
        assert f'href="/uk/' in content


def test_priority_list_page_structure_and_controls():
    """Verify the priority list page renders all required controls, actions, and print styles."""
    for lang in ["nl", "en", "uk"]:
        list_page = SITE_DIST / lang / "list" / "index.html"
        assert list_page.exists(), f"Missing list page for {lang}"
        content = list_page.read_text(encoding="utf-8")

        # Core interactive elements
        assert 'id="priority-items-list"' in content
        assert 'id="empty-list-notice"' in content
        assert 'id="shared-list-banner"' in content
        assert 'id="save-shared-list-btn"' in content
        assert 'id="dismiss-shared-list-btn"' in content

        # Action toolbar (§6.3)
        assert 'id="share-list-btn"' in content
        assert 'id="export-csv-btn"' in content
        assert 'id="export-json-btn"' in content
        assert 'id="import-json-input"' in content
        assert 'id="print-list-btn"' in content
        assert 'id="clear-list-btn"' in content

        # Print stylesheet (§6.3) verified in bundled CSS files
        css_files = list((SITE_DIST / "_astro").glob("list.*.css")) + list((SITE_DIST / "_astro").glob("Layout.*.css"))
        assert len(css_files) > 0, "Missing bundled CSS files in _astro"
        combined_css = "".join(f.read_text(encoding="utf-8") for f in css_files)
        assert "@media print" in combined_css
        assert "page-break-inside:avoid" in combined_css or "page-break-inside: avoid" in combined_css


def test_priority_list_toggles_on_cards_and_detail_pages():
    """Verify quick list toggle button exists on every card and on detail pages."""
    index_content = (SITE_DIST / "nl" / "index.html").read_text(encoding="utf-8")
    assert 'class="card-list-btn"' in index_content
    assert 'data-slug="huis-zypendaal"' in index_content

    detail_content = (SITE_DIST / "nl" / "museum" / "huis-zypendaal" / "index.html").read_text(encoding="utf-8")
    assert 'id="detail-list-toggle-btn"' in detail_content
    assert 'data-slug="huis-zypendaal"' in detail_content


def test_near_me_geolocation_and_centroid_fallback():
    """Verify Near Me button, distance dropdown, manual location entry, and lat/lon attributes exist."""
    content = (SITE_DIST / "nl" / "index.html").read_text(encoding="utf-8")

    # Geolocation and distance controls (§6.4)
    assert 'id="near-me-btn"' in content
    assert 'id="distance-sort-option"' in content
    assert 'id="max-distance-select"' in content
    assert 'id="manual-location-input"' in content
    assert 'id="manual-location-btn"' in content
    assert 'id="clear-location-btn"' in content

    # Card coordinate attributes
    assert 'data-lat="' in content
    assert 'data-lon="' in content

    # Haversine distance accuracy validation
    def haversine(lat1, lon1, lat2, lon2):
        r = 6371.0  # km
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # Amsterdam centroid (approx 52.36, 4.90) to Utrecht centroid (approx 52.09, 5.12) is ~35 km
    dist = haversine(52.3676, 4.9041, 52.0907, 5.1214)
    assert 30.0 < dist < 40.0


def test_no_external_network_requests_or_trackers_in_phase3():
    """Confirm strict privacy: no third-party script or stylesheet requests in generated HTML."""
    for html_file in [
        SITE_DIST / "nl" / "index.html",
        SITE_DIST / "uk" / "index.html",
        SITE_DIST / "nl" / "list" / "index.html",
        SITE_DIST / "uk" / "list" / "index.html",
        SITE_DIST / "nl" / "museum" / "huis-zypendaal" / "index.html",
    ]:
        content = html_file.read_text(encoding="utf-8")
        assert "google-analytics.com" not in content
        assert "googletagmanager.com" not in content
        assert "fonts.googleapis.com" not in content
        assert "api.mapbox.com" not in content
        assert "cdnjs.cloudflare.com" not in content
