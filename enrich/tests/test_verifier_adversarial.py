"""Unit and integration tests for adversarial verification."""

import os
import pytest
from enrich.verifier.adversarial_eval import ADVERSARIAL_TEST_CASES
from enrich.gates.price_gates import run_all_price_gates
from enrich.fetch import PoliteFetcher
from enrich.tools.fetch_page import sanitize_html_for_agent


def test_adversarial_deterministic_gates_coverage():
    """Verify that deterministic gates catch non-semantic syntax/range/keyword errors."""
    fetcher = PoliteFetcher()

    gate_caught_ids = set()
    for tc in ADVERSARIAL_TEST_CASES:
        if tc.category != "wrong":
            continue

        succ, html, _ = fetcher.fetch(tc.source_url)
        page_text = ""
        if succ and html:
            sanitized = sanitize_html_for_agent(html, tc.source_url)
            page_text = sanitized["text"]

        extracted_data = {
            "status": tc.status,
            "primary_adult_eur": tc.claimed_price,
            "quote": tc.quote,
            "source_url": tc.source_url,
        }

        gates_passed, failures = run_all_price_gates(
            slug=tc.id.lower(),
            museum_name=tc.museum_name,
            city=None,
            museum_website=tc.museum_website,
            source_url=tc.source_url,
            page_text=page_text,
            extracted_data=extracted_data,
            fetcher=fetcher,
        )

        if not gates_passed:
            gate_caught_ids.add(tc.id)

    # Gates must catch invented numbers (W5), free-for-children quotes (W1/W8), combi keywords (W3), out-of-bounds (W11), domain mismatch (W2/W12)
    assert "W3" in gate_caught_ids  # combo keyword
    assert "W5" in gate_caught_ids  # invented number
    assert "W11" in gate_caught_ids  # out of bounds range
    assert "W12" in gate_caught_ids  # foreign museum identity/domain


def test_positive_controls_pass_gates():
    """Verify that all authentic positive controls pass deterministic gates."""
    fetcher = PoliteFetcher()

    for tc in ADVERSARIAL_TEST_CASES:
        if tc.category != "correct":
            continue

        succ, html, _ = fetcher.fetch(tc.source_url)
        page_text = ""
        if succ and html:
            sanitized = sanitize_html_for_agent(html, tc.source_url)
            page_text = sanitized["text"]

        extracted_data = {
            "status": tc.status,
            "primary_adult_eur": tc.claimed_price,
            "quote": tc.quote,
            "source_url": tc.source_url,
        }

        gates_passed, failures = run_all_price_gates(
            slug=tc.id.lower(),
            museum_name=tc.museum_name,
            city=None,
            museum_website=tc.museum_website,
            source_url=tc.source_url,
            page_text=page_text,
            extracted_data=extracted_data,
            fetcher=fetcher,
        )

        assert gates_passed is True, f"Positive control {tc.id} ({tc.museum_name}) failed gates: {failures}"
