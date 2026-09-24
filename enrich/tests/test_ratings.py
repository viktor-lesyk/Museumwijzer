"""Unit and build verification tests for review ratings and UI layout."""

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RATINGS_PATH = REPO_ROOT / "data" / "enrichment" / "ratings.json"
MUSEUMS_PATH = REPO_ROOT / "data" / "museums.json"
DIST_DIR = REPO_ROOT / "site" / "dist"


def test_ratings_data_file_validity():
    assert RATINGS_PATH.exists(), "ratings.json should exist"
    with open(RATINGS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("version") == 1
    museums = data.get("museums", [])
    assert len(museums) >= 190, "Should have enriched ratings for all museums"

    with open(MUSEUMS_PATH, "r", encoding="utf-8") as f:
        official_data = json.load(f)
    valid_slugs = {m["slug"] for m in official_data.get("museums", [])}

    for item in museums:
        assert item["slug"] in valid_slugs, f"Invalid slug {item['slug']} in ratings.json"
        rating = item.get("rating")
        if rating is not None:
            assert isinstance(rating, (int, float))
            assert 1.0 <= rating <= 5.0, f"Rating {rating} out of range for {item['slug']}"
        reviews_count = item.get("reviews_count", 0)
        assert isinstance(reviews_count, int)
        assert reviews_count >= 0


def test_rijksmuseum_rating_sample():
    with open(RATINGS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    rijks = next((m for m in data["museums"] if m["slug"] == "rijksmuseum"), None)
    assert rijks is not None
    assert rijks["rating"] >= 4.5
    assert rijks["reviews_count"] > 50000


def test_build_contains_card_media_and_pills():
    nl_index = DIST_DIR / "nl" / "index.html"
    assert nl_index.exists(), "nl/index.html should exist"
    content = nl_index.read_text(encoding="utf-8")

    # Sticky filter bar & Category pills
    assert 'class="sticky-filter-wrapper"' in content
    assert 'class="category-pills-bar"' in content
    assert 'id="pill-all"' in content
    assert 'id="pill-kunst"' in content
    assert 'id="pill-geschiedenis"' in content
    assert 'id="pill-kastelen"' in content
    assert 'id="pill-wetenschap"' in content
    assert 'id="pill-natuur"' in content
    assert 'id="pill-familie"' in content

    # Card media, ratings, and body
    assert 'class="card-media"' in content
    assert 'class="card-rating-tag"' in content
    assert 'class="card-body"' in content

    # Hero overhaul: no old bulky banner, compact catalog hero with ticket pill
    assert 'class="catalog-hero"' in content
    assert 'class="btn-ticket-pill"' in content
    assert 'class="hero-section"' not in content


def test_build_detail_page_rating_and_no_duplicate_btn():
    rijks_html = DIST_DIR / "nl" / "museum" / "rijksmuseum" / "index.html"
    assert rijks_html.exists()
    content = rijks_html.read_text(encoding="utf-8")

    # Has numerical rating badge
    assert 'class="detail-rating-badge"' in content
    assert "reviews op Google" in content

    # No duplicate Google reviews button
    assert "btn-map-google" not in content


def test_build_contains_visited_feature():
    nl_index = DIST_DIR / "nl" / "index.html"
    assert nl_index.exists()
    content = nl_index.read_text(encoding="utf-8")

    # Toolbar toggle button
    assert 'id="toggle-hide-visited-btn"' in content
    assert 'class="btn-toggle-visited"' in content
    assert "Verberg bezocht" in content

    # Card media actions and visited button
    assert 'class="card-media-actions"' in content
    assert 'class="card-visited-btn"' in content
    assert 'class="card-visited-badge"' in content

    # Detail page visited toggle button
    rijks_html = DIST_DIR / "nl" / "museum" / "rijksmuseum" / "index.html"
    assert rijks_html.exists()
    detail_content = rijks_html.read_text(encoding="utf-8")
    assert 'id="detail-visited-toggle-btn"' in detail_content
    assert 'class="btn-detail-action btn-visited-toggle"' in detail_content

