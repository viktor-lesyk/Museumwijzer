"""Unit tests for runner orchestration, consensus routing, and storage."""

import json
from enrich.jobs.base import JobDefinition
from enrich.ops.storage import record_results
from enrich.runner.orchestrator import EnrichmentOrchestrator


def test_orchestrator_consensus_accepted(tmp_path, monkeypatch):
    job = JobDefinition.load("price_adult")

    class MockClient:
        def chat_with_tools(self, model, messages, tools, temperature):
            return {
                "role": "assistant",
                "content": json.dumps({
                    "admission": "paid",
                    "status": "paid",
                    "adult_eur": 18.00,
                    "quote": "Toegang volwassenen € 18,00",
                    "source_url": "https://testmuseum.nl/tickets",
                    "reason": "Clear ticket price on tickets page",
                    "confidence": "high",
                })
            }

        def chat_completion(self, model, messages, temperature, json_mode=False):
            return json.dumps({
                "verdict": "confirm",
                "justification": "Confirmed € 18 adult ticket on tickets page"
            })

    class MockFetcher:
        def fetch(self, url):
            return True, "<h1>Test Museum</h1><p>Toegang volwassenen € 18,00</p>", None

        def is_reached_from(self, target, origin):
            return True

    orchestrator = EnrichmentOrchestrator(
        base_url="http://mock",
        api_key="mock",
        extractor_model="qwen3.5:9b",
        verifier_model="deepseek-r1:1.5b",
        job=job,
        mode="agentic",
        force_different_families=True,
    )
    orchestrator.client = MockClient()
    orchestrator.fetcher = MockFetcher()
    orchestrator.verifier.client = MockClient()
    orchestrator.verifier.verifier_model = "deepseek-r1:1.5b"

    museum = {
        "slug": "test-museum",
        "name": "Test Museum",
        "city": "Utrecht",
        "museum_website": "https://testmuseum.nl/",
    }

    res = orchestrator.process_museum(museum)
    assert res["is_accepted"] is True
    assert res["gates_passed"] is True
    assert res["verifier_verdict"] == "confirm"
    assert res["price"]["adult_eur"] == 18.00


def test_orchestrator_gate_failure_rejected(tmp_path):
    job = JobDefinition.load("price_adult")

    class MockClient:
        def chat_with_tools(self, model, messages, tools, temperature):
            return {
                "role": "assistant",
                "content": json.dumps({
                    "admission": "paid",
                    "status": "paid",
                    "adult_eur": 20.00,
                    "quote": "Duoticket kasteel € 20",  # Combo keyword rejected!
                    "source_url": "https://testmuseum.nl/tickets",
                    "reason": "Combo ticket",
                    "confidence": "high",
                })
            }

        def chat_completion(self, model, messages, temperature, json_mode=False):
            return json.dumps({"verdict": "confirm", "justification": "ok"})

    class MockFetcher:
        def fetch(self, url):
            return True, "<h1>Test Museum</h1><p>Duoticket kasteel € 20</p>", None

        def is_reached_from(self, target, origin):
            return True

    orchestrator = EnrichmentOrchestrator(
        base_url="http://mock",
        api_key="mock",
        extractor_model="qwen3.5:9b",
        verifier_model="deepseek-r1:1.5b",
        job=job,
        mode="agentic",
    )
    orchestrator.client = MockClient()
    orchestrator.fetcher = MockFetcher()

    museum = {
        "slug": "test-museum",
        "name": "Test Museum",
        "city": "Utrecht",
        "museum_website": "https://testmuseum.nl/",
    }

    res = orchestrator.process_museum(museum)
    assert res["is_accepted"] is False
    assert res["gates_passed"] is False
    assert any("Combo rejection" in f for f in res["gate_failures"])


def test_storage_preserves_manual(tmp_path, monkeypatch):
    test_prices = tmp_path / "prices.json"
    test_review = tmp_path / "needs_review.json"
    monkeypatch.setattr("enrich.ops.storage.PRICES_PATH", test_prices)
    monkeypatch.setattr("enrich.ops.storage.NEEDS_REVIEW_PATH", test_review)

    # Pre-populate with manual price
    test_prices.write_text(json.dumps({
        "museums": [
            {
                "slug": "manual-museum",
                "name": "Manual Museum",
                "price": {"adult_eur": 12.50, "entered_by": "manual"}
            }
        ]
    }))

    # Try to overwrite with agent result
    agent_result = [{
        "slug": "manual-museum",
        "name": "Manual Museum",
        "is_accepted": True,
        "price": {"adult_eur": 14.00, "entered_by": "agent"}
    }]

    record_results(agent_result)

    with open(test_prices) as f:
        data = json.load(f)
    rec = next(m for m in data["museums"] if m["slug"] == "manual-museum")
    assert rec["price"]["adult_eur"] == 12.50
    assert rec["price"]["entered_by"] == "manual"
