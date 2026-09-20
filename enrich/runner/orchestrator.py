"""Central orchestrator coordinating extraction, deterministic gates, verifier, and storage."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from enrich.fetch import PoliteFetcher
from enrich.gates.price_gates import run_all_price_gates
from enrich.jobs.base import JobDefinition
from enrich.runner.agent import run_agentic_research
from enrich.runner.client import OpenAICompatClient
from enrich.runner.fallback import run_fallback_extraction
from enrich.runner.traces import save_trace
from enrich.tools.fetch_page import sanitize_html_for_agent
from enrich.verifier.verifier import IndependentVerifier, assert_different_model_families

logger = logging.getLogger("enrich.orchestrator")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "enrichment"
PRICES_JSON_PATH = DATA_DIR / "prices.json"
NEEDS_REVIEW_PATH = DATA_DIR / "needs_review.json"


class EnrichmentOrchestrator:
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str],
        extractor_model: str,
        verifier_model: str,
        job: JobDefinition,
        mode: str = "agentic",  # "agentic" or "fallback"
        force_different_families: bool = True,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.extractor_model = extractor_model
        self.verifier_model = verifier_model
        self.job = job
        self.mode = mode

        if force_different_families:
            assert_different_model_families(extractor_model, verifier_model)

        self.client = OpenAICompatClient(base_url=self.base_url, api_key=self.api_key)
        self.fetcher = PoliteFetcher()
        self.verifier = IndependentVerifier(self.client, verifier_model=self.verifier_model)

    def process_museum(self, museum: Dict[str, Any]) -> Dict[str, Any]:
        slug = museum["slug"]
        name = museum["name"]
        city = museum.get("city")
        website = museum.get("museum_website")

        start_time = time.time()
        logger.info(f"Processing '{slug}' ({name}) in mode '{self.mode}'...")

        # 1. Extraction phase
        tool_calls = 0
        trace_msgs: List[Dict[str, Any]] = []
        try:
            if self.mode == "agentic":
                extracted, trace_msgs, tool_calls = run_agentic_research(
                    client=self.client,
                    model=self.extractor_model,
                    job=self.job,
                    museum=museum,
                    fetcher=self.fetcher,
                )
            else:
                extracted, trace_msgs, tool_calls = run_fallback_extraction(
                    client=self.client,
                    model=self.extractor_model,
                    job=self.job,
                    museum=museum,
                    fetcher=self.fetcher,
                )
        except Exception as e:
            logger.warning(f"Agentic mode failed for {slug} ({e}). Attempting fallback mode...")
            extracted, trace_msgs, tool_calls = run_fallback_extraction(
                client=self.client,
                model=self.extractor_model,
                job=self.job,
                museum=museum,
                fetcher=self.fetcher,
            )

        extracted["checked_on"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        source_url = extracted.get("source_url") or website

        # Fetch page text of source_url for deterministic gates
        page_text = ""
        if source_url:
            succ, html, _ = self.fetcher.fetch(source_url)
            if succ and html:
                parsed = sanitize_html_for_agent(html, source_url)
                page_text = parsed["text"]

        # 2. Deterministic Gates phase
        gates_passed, gate_failures = run_all_price_gates(
            slug=slug,
            museum_name=name,
            city=city,
            museum_website=website,
            source_url=source_url,
            page_text=page_text,
            extracted_data=extracted,
            fetcher=self.fetcher,
            previous_prices_path=PRICES_JSON_PATH,
        )

        # 3. Independent Verifier phase (only if gates passed or blocked)
        verifier_result: Dict[str, Any] = {"verdict": "skipped", "justification": "Gates failed"}
        if gates_passed:
            verifier_result = self.verifier.verify(
                museum_name=name,
                museum_website=website,
                source_url=source_url,
                claimed_value=extracted.get("adult_eur"),
                admission=extracted.get("admission", "unknown"),
                status=extracted.get("status", "unknown"),
                fetcher=self.fetcher,
            )

        # 4. Consensus Decision
        # Consensual publication REQUIRES:
        # - Deterministic gates passed
        # - Verifier verdict == 'confirm'
        is_accepted = gates_passed and verifier_result.get("verdict") == "confirm"
        elapsed = round(time.time() - start_time, 2)

        result_record = {
            "slug": slug,
            "name": name,
            "price": extracted,
            "mode": self.mode,
            "tool_calls": tool_calls,
            "time_seconds": elapsed,
            "gates_passed": gates_passed,
            "gate_failures": gate_failures,
            "verifier_verdict": verifier_result.get("verdict"),
            "verifier_justification": verifier_result.get("justification"),
            "is_accepted": is_accepted,
        }

        # 5. Save Trace
        trace_data = {
            "museum": museum,
            "extractor_model": self.extractor_model,
            "verifier_model": self.verifier_model,
            "mode": self.mode,
            "extraction": extracted,
            "tool_calls": tool_calls,
            "time_seconds": elapsed,
            "gate_failures": gate_failures,
            "verifier": verifier_result,
            "is_accepted": is_accepted,
            "trace_messages": trace_msgs,
        }
        save_trace(slug, trace_data)

        return result_record
