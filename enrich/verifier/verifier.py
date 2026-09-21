"""Independent second-model verifier for museum price extraction.

ISOLATION GUARANTEES:
1. Receives ONLY: {museum_name, website, claimed_value, source_url, admission}
2. Never sees the extractor's thoughts or reasoning
3. Uses a completely different model family from the extractor model (enforced at startup)
4. Returns strictly: confirm | reject | unsure
"""

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from enrich.fetch import PoliteFetcher
from enrich.tools.fetch_page import sanitize_html_for_agent

logger = logging.getLogger("enrich.verifier")


def get_model_family(model_name: str) -> str:
    """Identify the fundamental model family to prevent correlated self-confirmation."""
    clean = model_name.lower()
    for fam in ["qwen", "llama", "deepseek", "mistral", "mixtral", "gemini", "claude", "gpt", "gemma", "phi", "liquid", "nemotron"]:
        if fam in clean:
            return fam if fam != "mixtral" else "mistral"
    # Fallback to provider or model prefix
    parts = clean.split("/")[-1].split(":")[0].split("-")[0]
    return parts or "unknown"


def assert_different_model_families(model_a: str, model_b: str, role_a: str = "Extractor", role_b: str = "Verifier") -> None:
    fam_a = get_model_family(model_a)
    fam_b = get_model_family(model_b)

    if fam_a == fam_b and fam_a != "unknown":
        raise ValueError(
            f"{role_a} model '{model_a}' and {role_b} model '{model_b}' "
            f"belong to the same model family ('{fam_a}'). "
            "Independent verification strictly requires two different model families to avoid correlated hallucinations."
        )


VERIFIER_SYSTEM_PROMPT = """You are an independent verification auditor for museum admission pricing data.
Your job is to independently verify a claimed admission price against raw webpage content.

CRITICAL RULES:
1. You must ONLY answer based on the provided page content.
2. The claimed price must be the STANDARD single-entry adult ticket for the museum itself.
3. If the page shows combo tickets, duo tickets, or tours only, you must REJECT or mark UNSURE.
4. If the page does not explicitly substantiate the exact claimed price or free admission, REJECT or mark UNSURE.
5. Return ONLY a valid JSON object in this exact schema:
{
  "verdict": "confirm" | "reject" | "unsure",
  "justification": "One sentence explaining why you confirmed, rejected, or are unsure."
}
"""


def format_verifier_user_prompt(
    museum_name: str,
    museum_website: Optional[str],
    source_url: str,
    claimed_value: Optional[float],
    status: str,
    page_text: str,
    admission: Optional[str] = None,
) -> str:
    claimed_desc = f"€{claimed_value:.2f}" if claimed_value is not None else f"status '{status}'"

    prompt = f"""=== VERIFICATION TARGET ===
Museum Name: {museum_name}
Official Website: {museum_website or 'None'}
Source URL: {source_url}
Claimed Status: {status}
Claimed Ticket Price: {claimed_desc}

=== WEBPAGE CONTENT ===
<untrusted_web_content url="{source_url}">
{page_text}
</untrusted_web_content>

Does the webpage content explicitly confirm that standard adult admission for {museum_name} is {claimed_desc}?
Answer in JSON with "verdict" ('confirm', 'reject', or 'unsure') and "justification".
"""
    return prompt


class IndependentVerifier:
    def __init__(self, client: Any, verifier_model: str):
        self.client = client
        self.verifier_model = verifier_model

    def verify(
        self,
        museum_name: str,
        museum_website: Optional[str],
        source_url: Optional[str],
        claimed_value: Optional[float],
        status: str,
        fetcher: PoliteFetcher,
        admission: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute independent verification on the claimed value."""
        # Non-priced states like bot protection or robots block don't require LLM page reading
        if status in ("blocked_by_bot_protection", "blocked_by_robots"):
            return {
                "verdict": "confirm",
                "justification": f"Host is unreachable due to {status}.",
                "model": self.verifier_model,
            }

        if not source_url:
            return {
                "verdict": "reject",
                "justification": "No source_url provided to verify.",
                "model": self.verifier_model,
            }

        # Fetch page independently
        success, html, err = fetcher.fetch(source_url)
        if not success or not html:
            return {
                "verdict": "reject",
                "justification": f"Failed to fetch {source_url}: {err}",
                "model": self.verifier_model,
            }

        parsed = sanitize_html_for_agent(html, source_url, max_chars=12000)
        user_prompt = format_verifier_user_prompt(
            museum_name=museum_name,
            museum_website=museum_website,
            source_url=source_url,
            claimed_value=claimed_value,
            admission=admission,
            status=status,
            page_text=parsed["text"],
        )

        messages = [
            {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            resp_content = self.client.chat_completion(
                model=self.verifier_model,
                messages=messages,
                temperature=0.0,
                json_mode=True,
            )
            # Parse JSON from response
            cleaned_json = re.sub(r"^```json\s*", "", resp_content.strip())
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)
            data = json.loads(cleaned_json)

            verdict = data.get("verdict", "unsure").lower()
            if verdict not in ("confirm", "reject", "unsure"):
                verdict = "unsure"

            return {
                "verdict": verdict,
                "justification": data.get("justification", "No justification provided"),
                "model": self.verifier_model,
            }
        except Exception as e:
            logger.error(f"Verifier LLM call failed: {e}")
            return {
                "verdict": "unsure",
                "justification": f"Verifier LLM call exception: {e}",
                "model": self.verifier_model,
            }
