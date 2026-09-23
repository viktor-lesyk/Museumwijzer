"""Unit tests for independent verifier and model family segregation."""

import pytest
from enrich.verifier.verifier import (
    IndependentVerifier,
    assert_different_model_families,
    get_model_family,
)


def test_get_model_family():
    assert get_model_family("qwen3.5:9b") == "qwen"
    assert get_model_family("meta-llama/llama-3.3-70b-instruct:free") == "llama"
    assert get_model_family("deepseek-r1:1.5b") == "deepseek"
    assert get_model_family("google/gemini-2.0-flash-exp:free") == "gemini"
    assert get_model_family("mistralai/mixtral-8x7b") == "mistral"


def test_different_families_required():
    # Different families: allowed
    assert_different_model_families("qwen3.5:9b", "deepseek-r1:1.5b")
    assert_different_model_families("meta-llama/llama-3.3-70b-instruct:free", "google/gemini-2.0-flash-exp:free")

    # Same family: strictly rejected
    with pytest.raises(ValueError) as exc:
        assert_different_model_families("qwen3.5:9b", "qwen3:4b")
    assert "same model family" in str(exc.value)

    with pytest.raises(ValueError) as exc2:
        assert_different_model_families("llama-3.1-8b", "meta-llama/llama-3.3-70b-instruct:free")
    assert "same model family" in str(exc2.value)


def test_verifier_execution_confirm():
    class DummyClient:
        def chat_completion(self, model, messages, temperature, json_mode):
            return '{"verdict": "confirm", "justification": "Price matches the static schedule."}'

    class DummyFetcher:
        def fetch(self, url):
            return True, "<h1>Rijksmuseum</h1><p>Volwassenen € 25,00</p>", None

    verifier = IndependentVerifier(client=DummyClient(), verifier_model="deepseek-r1:1.5b")
    result = verifier.verify(
        museum_name="Rijksmuseum",
        museum_website="https://www.rijksmuseum.nl/",
        source_url="https://www.rijksmuseum.nl/nl/tickets",
        claimed_value=25.0,
        status="paid",
        fetcher=DummyFetcher(),
    )
    assert result["verdict"] == "confirm"
    assert "Price matches" in result["justification"]


def test_verifier_execution_reject():
    class DummyClient:
        def chat_completion(self, model, messages, temperature, json_mode):
            return '{"verdict": "reject", "justification": "This is a duo ticket covering multiple museums."}'

    class DummyFetcher:
        def fetch(self, url):
            return True, "<h1>Tickets</h1><p>Duoticket € 20</p>", None

    verifier = IndependentVerifier(client=DummyClient(), verifier_model="deepseek-r1:1.5b")
    result = verifier.verify(
        museum_name="Joods Museum",
        museum_website="https://jck.nl/",
        source_url="https://jck.nl/tickets",
        claimed_value=20.0,
        status="paid",
        fetcher=DummyFetcher(),
    )
    assert result["verdict"] == "reject"
    assert "duo ticket" in result["justification"]
