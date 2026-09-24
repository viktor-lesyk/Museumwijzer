"""Unit tests for description, highlight, and visual enrichment pipeline."""

import json
from unittest.mock import MagicMock, patch
import pytest
from enrich.descriptions import clean_html, parse_json_from_llm, fetch_commons_image_info, synthesize_description


def test_clean_html():
    raw = '<a href="https://example.com"><b>Marco de Swart</b></a> &amp; Co'
    cleaned = clean_html(raw)
    assert cleaned == "Marco de Swart & Co"
    assert clean_html("") == ""
    assert clean_html(None) == ""


def test_parse_json_from_llm_direct():
    payload = '{"summary": {"nl": "Test"}, "why_visit": {"nl": ["Punt 1"]}, "tags": ["kunst"]}'
    data = parse_json_from_llm(payload)
    assert data is not None
    assert data["summary"]["nl"] == "Test"
    assert data["tags"] == ["kunst"]


def test_parse_json_from_llm_with_markdown_fences():
    payload = '```json\n{"summary": {"nl": "Fenced"}, "tags": ["historie"]}\n```'
    data = parse_json_from_llm(payload)
    assert data is not None
    assert data["summary"]["nl"] == "Fenced"


def test_parse_json_from_llm_with_trailing_garbage():
    payload = '{"summary": {"nl": "Valid"}, "tags": ["natuur"]}\nExtra trailing text here!'
    data = parse_json_from_llm(payload)
    assert data is not None
    assert data["summary"]["nl"] == "Valid"


def test_fetch_commons_image_info_mock():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "query": {
            "pages": {
                "123": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/original.jpg",
                            "thumburl": "https://thumb.wikimedia.org/960px-test.jpg",
                            "extmetadata": {
                                "Artist": {"value": '<a href="...">John Doe</a>'},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                            },
                        }
                    ]
                }
            }
        }
    }
    with patch("requests.get", return_value=mock_resp):
        info = fetch_commons_image_info("test.jpg", None)
        assert info is not None
        assert info["author"] == "John Doe"
        assert info["license"] == "CC BY-SA 4.0"
        assert info["url"] == "https://thumb.wikimedia.org/960px-test.jpg"


def test_allowed_categories():
    from enrich.descriptions import ALLOWED_CATEGORIES
    expected = {"kunst", "geschiedenis", "kastelen", "wetenschap", "natuur", "familie"}
    assert set(ALLOWED_CATEGORIES) == expected


def test_gallery_and_category_markup_in_build():
    from pathlib import Path
    dist_dir = Path(__file__).resolve().parent.parent.parent / "site" / "dist"
    
    # Detail page check (Rijksmuseum has enriched images)
    rijks_html = dist_dir / "nl" / "museum" / "rijksmuseum" / "index.html"
    if rijks_html.exists():
        content = rijks_html.read_text(encoding="utf-8")
        assert "detail-gallery-wrapper" in content
        assert "gallery-slider" in content
        assert "detail-rating-badge" in content
        assert "Google Maps" in content

    # Index page check for category filter
    index_html = dist_dir / "nl" / "index.html"
    if index_html.exists():
        content = index_html.read_text(encoding="utf-8")
        assert 'id="category-filter-select"' in content
        assert 'data-categories=' in content
        assert "card-category-badge" in content

