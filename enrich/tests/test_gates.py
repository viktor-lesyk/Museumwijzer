"""Unit tests for deterministic pricing gates."""

import json
from pathlib import Path
from enrich.gates.price_gates import (
    check_combo_rejection,
    check_domain_and_provenance,
    check_identity_presence,
    check_literal_match,
    check_plausible_range,
    check_yoy_change,
)


def test_gate_domain_and_provenance():
    # 1. Matching domain
    ok, _ = check_domain_and_provenance("https://rijksmuseum.nl/nl/tickets", "https://www.rijksmuseum.nl/")
    assert ok is True

    # 2. Subdomain match
    ok, _ = check_domain_and_provenance("https://tickets.nemosciencemuseum.nl/nl/tickets", "https://www.nemosciencemuseum.nl/")
    assert ok is True

    # 3. Completely foreign domain without provenance link
    ok, err = check_domain_and_provenance("https://unrelated-tickets.com/buy", "https://vanabbemuseum.nl/")
    assert ok is False
    assert "does not match" in err


def test_gate_literal_match_paid():
    page_text = "Openingstijden en tarieven. Volwassenen betalen € 17,50 per persoon. Museumkaart is gratis."

    # Valid literal match
    ok, err = check_literal_match(
        page_text=page_text,
        adult_eur=17.50,
        quote="Volwassenen betalen € 17,50",
        status="paid",
        admission="paid",
    )
    assert ok is True, f"Failed: {err}"

    # Price number missing from text
    ok, err = check_literal_match(
        page_text=page_text,
        adult_eur=25.00,
        quote="Volwassenen betalen € 17,50",
        status="paid",
        admission="paid",
    )
    assert ok is False
    assert "not found in page text" in err

    # Quote missing from text
    ok, err = check_literal_match(
        page_text=page_text,
        adult_eur=17.50,
        quote="Non existent quote text",
        status="paid",
        admission="paid",
    )
    assert ok is False
    assert "was not found verbatim" in err

    # Quote exceeding 15 words
    long_quote = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    ok, err = check_literal_match(
        page_text=page_text + " " + long_quote,
        adult_eur=17.50,
        quote=long_quote,
        status="paid",
        admission="paid",
    )
    assert ok is False
    assert "exceeds 15 words" in err


def test_gate_literal_match_free():
    page_text = "Welkom in onze kerk. De toegang is gratis voor iedereen. Donaties welkom."

    # Genuine free admission with explicit quote
    ok, err = check_literal_match(
        page_text=page_text,
        adult_eur=0.0,
        quote="toegang is gratis voor iedereen",
        status="free",
        admission="free",
    )
    assert ok is True, f"Failed: {err}"

    # False positive: children free, but adults not free
    page_text_child = "Tarieven: Volwassenen € 15. Kinderen tot 18 jaar gratis."
    ok, err = check_literal_match(
        page_text=page_text_child,
        adult_eur=0.0,
        quote="Kinderen tot 18 jaar gratis",
        status="free",
        admission="free",
    )
    assert ok is False
    assert "youth/children" in err


def test_gate_plausible_range():
    # Valid paid range [1.0, 45.0]
    ok, _ = check_plausible_range(adult_eur=15.0, status="paid", admission="paid")
    assert ok is True

    # Price below 1.00 EUR for paid
    ok, err = check_plausible_range(adult_eur=0.50, status="paid", admission="paid")
    assert ok is False
    assert "outside plausible adult range" in err

    # Price above 45.00 EUR for paid
    ok, err = check_plausible_range(adult_eur=55.0, status="paid", admission="paid")
    assert ok is False
    assert "outside plausible adult range" in err

    # Free with adult_eur > 0
    ok, err = check_plausible_range(adult_eur=10.0, status="free", admission="free")
    assert ok is False
    assert "cannot have adult_eur" in err


def test_gate_combo_rejection():
    # Single museum ticket
    ok, _ = check_combo_rejection(quote="Entree volwassenen € 15", page_text="")
    assert ok is True

    # Duo ticket
    ok, err = check_combo_rejection(quote="Duoticket Joods Museum + Portugese Synagoge € 20", page_text="")
    assert ok is False
    assert "forbidden combo/duo keyword" in err

    # Combi ticket
    ok, err = check_combo_rejection(quote="Combiticket kasteel en museum € 22", page_text="")
    assert ok is False
    assert "forbidden combo/duo keyword" in err


def test_gate_identity_presence():
    page_text = "Welkom bij Museum Martena in Franeker. Ontdek de Friese adel."
    ok, _ = check_identity_presence(page_text, "Museum Martena", "Franeker")
    assert ok is True

    # Unrelated page
    ok, err = check_identity_presence("Welkom bij het Scheepvaartmuseum in Amsterdam", "Museum Martena", "Franeker")
    assert ok is False
    assert "Neither museum name tokens" in err


def test_gate_yoy_change(tmp_path):
    prev_file = tmp_path / "prices.json"
    prev_file.write_text(json.dumps({
        "museums": [
            {"slug": "test-museum", "price": {"adult_eur": 10.00}}
        ]
    }))

    # 20% increase (ok)
    ok, _ = check_yoy_change("test-museum", 12.00, prev_file)
    assert ok is True

    # 40% increase (>30% jump)
    ok, err = check_yoy_change("test-museum", 14.50, prev_file)
    assert ok is False
    assert "Price changed by 45.0%" in err


def test_gate_free_for_vocabulary():
    from enrich.gates.price_gates import check_free_for_vocabulary

    # Valid vocabulary
    ok, _ = check_free_for_vocabulary(["children_under_18", "museumkaart"])
    assert ok is True

    # Empty list is fine
    ok, _ = check_free_for_vocabulary([])
    assert ok is True

    # Invalid vocabulary entry
    ok, err = check_free_for_vocabulary(["children_under_18", "free_hotdogs"])
    assert ok is False
    assert "not in controlled vocabulary" in err


def test_gate_offerings():
    from enrich.gates.price_gates import check_offerings_gates

    # Valid offerings
    valid_offerings = [
        {"audience": "adult", "amount_eur": 20.0, "label": "Volwassenen", "conditions": None},
        {"audience": "child", "amount_eur": 10.0, "label": "Kinderen 4-12 jaar", "conditions": "4-12"},
    ]
    ok, _ = check_offerings_gates(valid_offerings, "paid")
    assert ok is True

    # Invalid audience
    bad_audience = [
        {"audience": "aliens", "amount_eur": 20.0, "label": "Aliens", "conditions": None},
    ]
    ok, err = check_offerings_gates(bad_audience, "paid")
    assert ok is False
    assert "invalid audience" in err

    # Label exceeding 8 words
    bad_label = [
        {"audience": "adult", "amount_eur": 20.0, "label": "Dit is een veel te lang ticket label met meer dan acht woorden", "conditions": None},
    ]
    ok, err = check_offerings_gates(bad_label, "paid")
    assert ok is False
    assert "exceeds 8 words limit" in err

    # Out of bounds price (>45)
    bad_price = [
        {"audience": "adult", "amount_eur": 99.0, "label": "Super VIP ticket", "conditions": None},
    ]
    ok, err = check_offerings_gates(bad_price, "paid")
    assert ok is False
    assert "outside plausible range" in err


def test_is_only_quote_length_failure():
    from enrich.gates.price_gates import is_only_quote_length_failure

    # Single failure with quote length exceeded -> True
    assert is_only_quote_length_failure(["Literal match gate: Quote exceeds 15 words limit (18 words)"]) is True

    # Multiple failures -> False
    assert is_only_quote_length_failure([
        "Literal match gate: Quote exceeds 15 words limit (18 words)",
        "Range gate: Price out of bounds",
    ]) is False

    # Single failure but not quote length -> False
    assert is_only_quote_length_failure(["Domain gate: source_url mismatch"]) is False

