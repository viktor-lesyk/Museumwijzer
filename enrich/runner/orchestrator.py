"""Central orchestrator coordinating extraction, deterministic gates, verifier, and storage."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from enrich.fetch import PoliteFetcher
from enrich.gates.price_gates import calibrate_confidence, is_only_quote_length_failure, run_all_price_gates
from enrich.jobs.base import JobDefinition
from enrich.runner.agent import extract_json_payload, run_agentic_research
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
        escalation_model: Optional[str] = None,
        mode: str = "agentic",  # "agentic" or "fallback"
        force_different_families: bool = True,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.extractor_model = extractor_model
        self.verifier_model = verifier_model
        self.escalation_model = escalation_model
        self.job = job
        self.mode = mode

        if force_different_families:
            assert_different_model_families(extractor_model, verifier_model, role_a="Extractor", role_b="Verifier")
            if escalation_model:
                assert_different_model_families(escalation_model, verifier_model, role_a="Escalation", role_b="Verifier")

        self.client = OpenAICompatClient(base_url=self.base_url, api_key=self.api_key)
        self.fetcher = PoliteFetcher()
        self.verifier = IndependentVerifier(self.client, verifier_model=self.verifier_model)

    def _execute_research(
        self,
        model: str,
        museum: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
        slug = museum["slug"]
        if self.mode == "agentic":
            try:
                return run_agentic_research(
                    client=self.client,
                    model=model,
                    job=self.job,
                    museum=museum,
                    fetcher=self.fetcher,
                )
            except Exception as e:
                logger.warning(f"Agentic research failed for {slug} with model {model} ({e}). Falling back to static mode...")
                return run_fallback_extraction(
                    client=self.client,
                    model=model,
                    job=self.job,
                    museum=museum,
                    fetcher=self.fetcher,
                )
        else:
            return run_fallback_extraction(
                client=self.client,
                model=model,
                job=self.job,
                museum=museum,
                fetcher=self.fetcher,
            )

    def _retry_quote_length(
        self,
        model: str,
        extracted: Dict[str, Any],
        source_url: str,
        page_text: str,
    ) -> Optional[str]:
        """Ask model once to extract a shorter quote (<=15 words) when that was the only gate failure."""
        current_quote = extracted.get("quote", "")
        prompt = f"""You previously found ticket information on {source_url} with quote:
"{current_quote}"
However, this quote has {len(current_quote.split())} words. The strict maximum allowed is 15 words.
From the webpage content below, provide a concise verbatim quote of 15 words or fewer supporting the price/status.

=== WEBPAGE CONTENT ===
<untrusted_web_content url="{source_url}">
{page_text[:5000]}
</untrusted_web_content>

Output ONLY a JSON object with:
{{
  "quote": "verbatim quote <= 15 words"
}}
"""
        try:
            resp = self.client.chat_completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
            )
            data = extract_json_payload(resp)
            if data and data.get("quote"):
                q = str(data["quote"]).strip()
                if len(q.split()) <= 15:
                    return q
        except Exception as e:
            logger.warning(f"Quote retry call failed: {e}")
        return None

    def process_museum(self, museum: Dict[str, Any]) -> Dict[str, Any]:
        slug = museum["slug"]
        name = museum["name"]
        city = museum.get("city")
        website = museum.get("museum_website")

        start_time = time.time()
        logger.info(f"Processing '{slug}' ({name}) in mode '{self.mode}'...")

        # 1. First Attempt with Extractor Model
        extracted, trace_msgs, tool_calls = self._execute_research(self.extractor_model, museum)

        source_url = extracted.get("source_url") or website
        page_text = ""
        if source_url:
            succ, html, _ = self.fetcher.fetch(source_url)
            if succ and html:
                parsed = sanitize_html_for_agent(html, source_url)
                page_text = parsed["text"]

        # Run Deterministic Gates
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

        # Quote Length Retry (only if quote length was the sole failure)
        if not gates_passed and is_only_quote_length_failure(gate_failures) and page_text and source_url:
            logger.info(f"Quote exceeded 15 words for {slug}. Retrying quote extraction once...")
            shorter_quote = self._retry_quote_length(self.extractor_model, extracted, source_url, page_text)
            if shorter_quote:
                extracted["quote"] = shorter_quote
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

        # Verifier Phase (only if gates passed)
        verifier_result: Dict[str, Any] = {"verdict": "skipped", "justification": "Gates failed"}
        if gates_passed:
            val = extracted.get("primary_adult_eur")
            if val is None:
                val = extracted.get("adult_eur")
            verifier_result = self.verifier.verify(
                museum_name=name,
                museum_website=website,
                source_url=source_url,
                claimed_value=val,
                status=extracted.get("status", "unknown"),
                fetcher=self.fetcher,
            )

        is_accepted = gates_passed and verifier_result.get("verdict") == "confirm"

        # 2. Escalation Ladder (if rejected and escalation model is configured)
        if not is_accepted and self.escalation_model and self.escalation_model != self.extractor_model:
            logger.info(f"Primary model extraction rejected for {slug}. Escalating to stronger model '{self.escalation_model}'...")
            esc_extracted, esc_trace, esc_tool_calls = self._execute_research(self.escalation_model, museum)
            tool_calls += esc_tool_calls
            trace_msgs.extend(esc_trace)

            esc_source_url = esc_extracted.get("source_url") or website
            esc_page_text = ""
            if esc_source_url:
                succ, html, _ = self.fetcher.fetch(esc_source_url)
                if succ and html:
                    parsed = sanitize_html_for_agent(html, esc_source_url)
                    esc_page_text = parsed["text"]

            esc_gates_passed, esc_gate_failures = run_all_price_gates(
                slug=slug,
                museum_name=name,
                city=city,
                museum_website=website,
                source_url=esc_source_url,
                page_text=esc_page_text,
                extracted_data=esc_extracted,
                fetcher=self.fetcher,
                previous_prices_path=PRICES_JSON_PATH,
            )

            # Retry quote on escalation if needed
            if not esc_gates_passed and is_only_quote_length_failure(esc_gate_failures) and esc_page_text and esc_source_url:
                logger.info(f"Escalation quote exceeded 15 words for {slug}. Retrying quote...")
                shorter_quote = self._retry_quote_length(self.escalation_model, esc_extracted, esc_source_url, esc_page_text)
                if shorter_quote:
                    esc_extracted["quote"] = shorter_quote
                    esc_gates_passed, esc_gate_failures = run_all_price_gates(
                        slug=slug,
                        museum_name=name,
                        city=city,
                        museum_website=website,
                        source_url=esc_source_url,
                        page_text=esc_page_text,
                        extracted_data=esc_extracted,
                        fetcher=self.fetcher,
                        previous_prices_path=PRICES_JSON_PATH,
                    )

            esc_verifier_result: Dict[str, Any] = {"verdict": "skipped", "justification": "Escalation gates failed"}
            if esc_gates_passed:
                val = esc_extracted.get("primary_adult_eur")
                if val is None:
                    val = esc_extracted.get("adult_eur")
                esc_verifier_result = self.verifier.verify(
                    museum_name=name,
                    museum_website=website,
                    source_url=esc_source_url,
                    claimed_value=val,
                    status=esc_extracted.get("status", "unknown"),
                    fetcher=self.fetcher,
                )

            if esc_gates_passed and esc_verifier_result.get("verdict") == "confirm":
                logger.info(f"Escalation model '{self.escalation_model}' SUCCEEDED for {slug}!")
                extracted = esc_extracted
                extracted["escalated"] = True
                extracted["extractor_model"] = self.escalation_model
                gates_passed = True
                gate_failures = []
                verifier_result = esc_verifier_result
                is_accepted = True
            else:
                gate_failures.extend([f"Escalation failed: {f}" for f in esc_gate_failures])

        # 3. Finalize metadata on extracted record
        if extracted.get("status") == "free":
            extracted["primary_adult_eur"] = None
            extracted["adult_eur"] = None

        extracted["mode"] = self.mode
        extracted["extractor_model"] = extracted.get("extractor_model") or self.extractor_model
        extracted["verifier_model"] = self.verifier_model
        extracted["checked_on"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        extracted["confidence"] = calibrate_confidence(
            status=extracted.get("status", "unknown"),
            quote=extracted.get("quote"),
            offerings=extracted.get("offerings"),
            raw_confidence=extracted.get("confidence"),
        )


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

        # 4. Save Trace
        trace_data = {
            "museum": museum,
            "extractor_model": extracted.get("extractor_model", self.extractor_model),
            "verifier_model": self.verifier_model,
            "escalation_model": self.escalation_model,
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
