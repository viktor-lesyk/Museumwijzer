"""Tests for identity discovery jobs and proposals handling."""

import hashlib
import json
from pathlib import Path
import pytest

from enrich.identity import is_aggregator_url, discover_museum_website, check_museum_address
from enrich.ops.proposals import load_proposals, record_proposals, save_proposals, clear_proposals, PROPOSALS_PATH
from enrich.fetch import PoliteFetcher

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OVERRIDES_PATH = REPO_ROOT / "data" / "overrides.yaml"


def test_aggregator_url_filtering():
    """Verify that aggregators, directories, and social media portals are rejected."""
    bad_urls = [
        "https://www.tripadvisor.com/Attraction_Review-g188590-Amsterdam.html",
        "https://nl.wikipedia.org/wiki/Rijksmuseum_Amsterdam",
        "https://www.museum.nl/nl/rijksmuseum",
        "https://whichmuseum.nl/nederland/amsterdam/rijksmuseum",
        "https://www.facebook.com/rijksmuseum",
        "https://www.instagram.com/rijksmuseum",
        "https://twitter.com/rijksmuseum",
        "https://www.visitholland.com/en/amsterdam",
        "https://www.dagjeweg.nl/museum/rijksmuseum",
        "https://welkominhetmuseum.vriendenloterij.nl/nl/musea/rijksmuseum",
        "https://www.booking.com/hotel/nl/amsterdam.html",
        "https://www.anwb.nl/eropuit/dagje-uit/museum",
    ]
    for url in bad_urls:
        assert is_aggregator_url(url) is True, f"Failed to reject aggregator: {url}"

    valid_urls = [
        "https://www.rijksmuseum.nl/",
        "https://www.hartmuseum.nl/",
        "https://textielmuseum.nl/",
        "https://www.madurodam.nl/nl",
        "https://www.spoorwegmuseum.nl/bezoek",
    ]
    for url in valid_urls:
        assert is_aggregator_url(url) is False, f"Erroneously flagged valid museum site: {url}"


def test_proposals_storage_and_overrides_isolation(tmp_path):
    """Verify that identity proposals write strictly to proposals.json and NEVER modify overrides.yaml."""
    overrides_before = OVERRIDES_PATH.read_bytes()
    overrides_hash_before = hashlib.sha256(overrides_before).hexdigest()

    test_proposals = [
        {
            "slug": "test-museum-1",
            "field": "museum_website",
            "current_value": None,
            "proposed_value": "https://www.testmuseum.nl/",
            "evidence_url": "https://www.testmuseum.nl/",
            "quote": "Test Museum Amsterdam",
            "confidence": "high",
            "reason": "Found official homepage",
            "checked_on": "2026-09-21",
        },
        {
            "slug": "test-museum-2",
            "field": "address",
            "current_value": {"street": "Old Street 1", "postcode": "1000 AA", "city": "Amsterdam"},
            "proposed_value": {"street": "New Street 2", "postcode": "1000 BB", "city": "Amsterdam"},
            "evidence_url": "https://www.testmuseum.nl/contact",
            "quote": "New Street 2 1000 BB Amsterdam",
            "confidence": "high",
            "reason": "Contact page correction",
            "checked_on": "2026-09-21",
        }
    ]

    # Record proposals
    total = record_proposals(test_proposals)
    assert total >= 2

    # Verify proposals.json exists and contains our entries
    assert PROPOSALS_PATH.exists()
    loaded = load_proposals()
    slugs = [p["slug"] for p in loaded]
    assert "test-museum-1" in slugs
    assert "test-museum-2" in slugs

    # CRITICAL: Verify data/overrides.yaml was NOT modified
    overrides_after = OVERRIDES_PATH.read_bytes()
    overrides_hash_after = hashlib.sha256(overrides_after).hexdigest()
    assert overrides_hash_before == overrides_hash_after, "data/overrides.yaml was modified by identity proposal workflow!"

    # Clean up test proposals
    clear_proposals(slug="test-museum-1")
    clear_proposals(slug="test-museum-2")
