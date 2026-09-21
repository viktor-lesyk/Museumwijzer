"""Unit and integration tests for adversarial verification."""

import os
import pytest
from enrich.verifier.adversarial_eval import (
    ADVERSARIAL_TEST_CASES,
    HOLD_OUT_TEST_CASES,
    ALL_TEST_CASES,
    wilson_score_interval,
)
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
    """Verify that all authentic positive controls in baseline and holdout suites pass deterministic gates."""
    fetcher = PoliteFetcher()

    for tc in ALL_TEST_CASES:
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


def test_holdout_semantic_wrong_claims_pass_gates():
    """Verify that hold-out wrong claims pass deterministic gates, proving they are pure semantic challenges."""
    fetcher = PoliteFetcher()

    for tc in HOLD_OUT_TEST_CASES:
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

        assert gates_passed is True, (
            f"Hold-out wrong claim {tc.id} ({tc.museum_name}) was caught by code gates ({failures}), "
            "but should be a purely semantic case requiring verifier reasoning."
        )


def test_wilson_score_interval_bounds():
    """Test mathematical correctness and bounds of Wilson score confidence interval."""
    # 0 out of 0
    assert wilson_score_interval(0, 0) == (0.0, 100.0)

    # 12 out of 12 (95% CI)
    low, high = wilson_score_interval(12, 12)
    assert high == 100.0
    assert 70.0 < low < 80.0  # Approx 75.8%

    # 17 out of 17 (95% CI)
    low, high = wilson_score_interval(17, 17)
    assert high == 100.0
    assert 80.0 < low < 85.0  # Approx 81.6%

    # 5 out of 10
    low, high = wilson_score_interval(5, 10)
    assert low < 50.0 < high
