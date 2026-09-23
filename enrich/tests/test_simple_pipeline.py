"""Unit tests for the dual-model price enrichment pipeline."""

import json
from pathlib import Path
import pytest

from enrich.simple_pipeline import (
    SearchQuotaGuard,
    extract_domain,
    extract_json_from_response,
    is_ticketing_subdomain,
    normalize_text_for_match,
    save_dual_model_results,
    validate_free_tier_configuration,
    validate_safety_net_gates,
)


def test_free_tier_validation():
    # 1. Valid free configurations should pass
    validate_free_tier_configuration(
        litellm_model="free-lite",
        openrouter_model="nvidia/nemotron-3-super-120b-a12b:free",
        disallow_brave=True,
    )

    # 2. OpenRouter model without :free must fail loudly
    with pytest.raises(ValueError, match="OPENROUTER_FREE_MODEL"):
        validate_free_tier_configuration(
            litellm_model="free-lite",
            openrouter_model="openai/gpt-4o",
            disallow_brave=True,
        )

    # 3. LiteLLM model without 'free' must fail loudly
    with pytest.raises(ValueError, match="LITELLM_FREE_LITE_MODEL"):
        validate_free_tier_configuration(
            litellm_model="gpt-4o-mini",
            openrouter_model="meta-llama/llama-3.3-70b-instruct:free",
            disallow_brave=True,
        )


def test_search_quota_guard(tmp_path):
    quota_file = tmp_path / "quota.json"
    guard = SearchQuotaGuard(quota_file=quota_file, max_monthly_searches=3)

    assert guard.can_search() is True
    assert guard.get_used_count() == 0

    guard.record_search()
    guard.record_search()
    assert guard.get_used_count() == 2
    assert guard.can_search() is True

    guard.record_search()
    assert guard.get_used_count() == 3
    assert guard.can_search() is False


def test_domain_provenance():
    assert extract_domain("https://www.rijksmuseum.nl/nl/tickets") == "rijksmuseum.nl"
    assert extract_domain("https://kasteeldehaar.nl/bezoek") == "kasteeldehaar.nl"

    assert is_ticketing_subdomain("https://tickets.rijksmuseum.nl/nl/tickets", "rijksmuseum.nl") is True
    assert is_ticketing_subdomain("https://www.rijksmuseum.nl/nl", "rijksmuseum.nl") is True
    assert is_ticketing_subdomain("https://rijksmuseum.nl/", "rijksmuseum.nl") is True
    assert is_ticketing_subdomain("https://amsterdam.nl/tickets", "rijksmuseum.nl") is False


def test_json_extractor():
    # Direct JSON
    assert extract_json_from_response('{"status": "paid", "primary_adult_eur": 17.5}') == {
        "status": "paid",
        "primary_adult_eur": 17.5,
    }

    # Markdown block
    md = 'Here is the result:\n```json\n{"status": "free", "primary_adult_eur": null}\n```\n'
    assert extract_json_from_response(md) == {"status": "free", "primary_adult_eur": None}

    # Embedded in thoughts
    embedded = 'Let me think. Based on the page:\n{"status": "paid", "primary_adult_eur": 21.5}\nThat concludes it.'
    assert extract_json_from_response(embedded) == {"status": "paid", "primary_adult_eur": 21.5}


def test_safety_net_gates_literal_match():
    museum = {
        "slug": "rijksmuseum",
        "name": "Rijksmuseum",
        "museum_website": "https://www.rijksmuseum.nl/",
    }
    pages = [
        {
            "url": "https://www.rijksmuseum.nl/nl/tickets",
            "title": "Tickets",
            "text": "Welkom! Volwassenen betalen € 25,00 voor een ticket. Jeugd t/m 18 jaar is gratis.",
        }
    ]

    # 1. Valid match passes
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "paid",
            "primary_adult_eur": 25.0,
            "quote": "Volwassenen betalen € 25,00",
            "source_url": "https://www.rijksmuseum.nl/nl/tickets",
            "free_for": ["youth"],
        },
        pages,
    )
    assert ok is True
    assert len(fails) == 0

    # 2. Quote exceeding 15 words fails
    long_quote = "Volwassenen betalen 25 euro voor toegang tot het hele museum inclusief alle permanente collecties en tijdelijke exposities vandaag"
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "paid",
            "primary_adult_eur": 25.0,
            "quote": long_quote,
            "source_url": "https://www.rijksmuseum.nl/nl/tickets",
        },
        pages,
    )
    assert ok is False
    assert any("exceeds 15 words" in f for f in fails)

    # 3. Fabricated quote fails
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "paid",
            "primary_adult_eur": 25.0,
            "quote": "Entree volwassenen kost dertig euro",
            "source_url": "https://www.rijksmuseum.nl/nl/tickets",
        },
        pages,
    )
    assert ok is False
    assert any("not found verbatim" in f for f in fails)

    # 4. Fabricated price amount fails literal match
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "paid",
            "primary_adult_eur": 19.5,
            "quote": "Volwassenen betalen € 25,00",
            "source_url": "https://www.rijksmuseum.nl/nl/tickets",
        },
        pages,
    )
    assert ok is False
    assert any("Claimed amount €19.5 not found" in f for f in fails)


def test_safety_net_gates_domain_and_range():
    museum = {
        "slug": "rijksmuseum",
        "name": "Rijksmuseum",
        "museum_website": "https://www.rijksmuseum.nl/",
    }
    pages = [
        {
            "url": "https://tickets.rijksmuseum.nl/tickets",
            "title": "Tickets",
            "text": "Volwassenen: € 22,50",
        }
    ]

    # Foreign domain fails
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "paid",
            "primary_adult_eur": 22.5,
            "quote": "Volwassenen: € 22,50",
            "source_url": "https://thirdparty.com/rijks",
        },
        pages,
    )
    assert ok is False
    assert any("Domain provenance gate" in f for f in fails)

    # Out of range price fails
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "paid",
            "primary_adult_eur": 75.0,
            "quote": "Volwassenen: € 22,50",
            "source_url": "https://tickets.rijksmuseum.nl/tickets",
        },
        pages,
    )
    assert ok is False
    assert any("outside plausible adult range" in f for f in fails)

    # Free status requires explicit free quote
    ok, fails = validate_safety_net_gates(
        museum,
        {
            "status": "free",
            "primary_adult_eur": None,
            "quote": "Openingstijden van het museum",
            "source_url": "https://tickets.rijksmuseum.nl/tickets",
        },
        pages,
    )
    assert ok is False
    assert any("explicitly state free admission" in f for f in fails)


def test_storage_and_agreement_separation(tmp_path, monkeypatch):
    test_prices_path = tmp_path / "prices.json"
    test_needs_path = tmp_path / "needs_review.json"
    import enrich.simple_pipeline as sp
    monkeypatch.setattr(sp, "PRICES_JSON_PATH", test_prices_path)
    monkeypatch.setattr(sp, "NEEDS_REVIEW_PATH", test_needs_path)

    results = [
        # 1. Agreed result -> prices.json
        {
            "slug": "museum-a",
            "name": "Museum A",
            "is_accepted": True,
            "disagreement_type": None,
            "gate_failures": [],
            "price": {
                "status": "paid",
                "primary_adult_eur": 15.0,
                "confidence": "high",
                "reasoning_summary": "Standard walk-in admission agreed",
            },
        },
        # 2. Disagreement (price mismatch) -> needs_review.json
        {
            "slug": "museum-b",
            "name": "Museum B",
            "is_accepted": False,
            "disagreement_type": "price_mismatch",
            "gate_failures": [],
            "model1": {"model": "m1", "status": "paid", "primary_adult_eur": 15.0, "reasoning_summary": "M1 reason"},
            "model2": {"model": "m2", "status": "paid", "primary_adult_eur": 17.5, "reasoning_summary": "M2 reason"},
            "price": {"status": "needs_review", "confidence": "low"},
        },
        # 3. retry_later -> omitted from needs_review
        {
            "slug": "museum-c",
            "name": "Museum C",
            "is_accepted": False,
            "disagreement_type": "retry_later",
            "gate_failures": ["429 rate limit"],
            "price": {"status": "retry_later", "confidence": "low"},
        },
        # 4. quota_exhausted -> omitted from needs_review
        {
            "slug": "museum-d",
            "name": "Museum D",
            "is_accepted": False,
            "disagreement_type": "quota_exhausted",
            "gate_failures": ["quota reached"],
            "price": {"status": "quota_exhausted", "confidence": "low"},
        },
    ]

    acc, rev = save_dual_model_results(results)
    assert acc == 1
    assert rev == 1

    with open(test_prices_path, "r") as f:
        p_data = json.load(f)
        slugs_in_prices = [m["slug"] for m in p_data["museums"]]
        assert slugs_in_prices == ["museum-a"]

    with open(test_needs_path, "r") as f:
        n_data = json.load(f)
        slugs_in_needs = [m["slug"] for m in n_data["records"]]
        assert slugs_in_needs == ["museum-b"]
        rec = n_data["records"][0]
        assert rec["disagreement_type"] == "price_mismatch"
        assert rec["model1"]["reasoning_summary"] == "M1 reason"
        assert rec["model2"]["reasoning_summary"] == "M2 reason"


def test_quote_mojibake_normalization():
    from enrich.simple_pipeline import check_quote_in_text

    text = "<tr><td>Volwassenen</td><td>â‚¬ 12,00</td></tr>"
    assert check_quote_in_text("Volwassenen € 12,00", text) is True

    text_mojibake2 = "<div>Adults: â\x82¬ 13,00</div>"
    assert check_quote_in_text("Adults: € 13,00", text_mojibake2) is True


def test_single_model_fallback(monkeypatch):
    from enrich.simple_pipeline import process_museum_dual_model

    museum = {
        "slug": "test-fallback-museum",
        "name": "Test Fallback Museum",
        "museum_website": "https://testmuseum.nl/",
    }
    pages = [
        {
            "url": "https://testmuseum.nl/tickets",
            "title": "Tickets",
            "text": "Volwassenen entree: € 14,50 per persoon.",
        }
    ]

    # Monkeypatch call_pricing_model so M1 passes and M2 fails to parse (returns status=unknown)
    def mock_call_pricing_model(base_url, api_key, model, museum_name, city, website, multi_page_content, timeout=45):
        if "free-lite" in model or "m1" in model:
            return {
                "status": "paid",
                "primary_adult_eur": 14.5,
                "quote": "Volwassenen entree: € 14,50",
                "source_url": "https://testmuseum.nl/tickets",
                "reasoning_summary": "Extracted valid ticket price",
            }
        else:
            return {
                "status": "unknown",
                "primary_adult_eur": None,
                "reasoning_summary": "Failed to parse model response into valid JSON",
            }

    import enrich.simple_pipeline as sp
    monkeypatch.setattr(sp, "call_pricing_model", mock_call_pricing_model)

    res = process_museum_dual_model(
        museum=museum,
        fetcher=None,
        quota_guard=None,
        litellm_base_url="http://localhost:4000/v1",
        litellm_api_key="mock",
        litellm_model="free-lite",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_api_key="mock",
        openrouter_model="nemotron:free",
        override_pages=pages,
    )

    assert res["is_accepted"] is True
    assert res["price"]["primary_adult_eur"] == 14.5
    assert res["price"]["confidence"] == "medium"
    assert "fallback_m1" in res["price"]["mode"]

