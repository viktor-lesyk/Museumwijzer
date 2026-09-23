"""Non-agentic snippet fallback runner.

Used when the model does not support tool calling or when running in --mode fallback.
Fetches the museum homepage and candidate pricing subpages, bundles their text with
injection delimiters, and makes a single extraction call.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from enrich.fetch import PoliteFetcher
from enrich.jobs.base import JobDefinition
from enrich.runner.agent import extract_json_payload
from enrich.tools.fetch_page import TextAndLinksParser, sanitize_html_for_agent

logger = logging.getLogger("enrich.fallback")


def find_candidate_urls(html: str, base_url: str, max_urls: int = 4) -> List[str]:
    parser = TextAndLinksParser(base_url)
    try:
        parser.feed(html)
    except Exception:
        pass

    candidates = []
    seen = set()
    base_netloc = urlparse(base_url).netloc.lower()
    keywords = ["ticket", "kaart", "toegang", "tarief", "prijzen", "prijs", "admission", "bezoek", "plan", "praktisch"]

    for href, link_text in parser.links:
        parsed = urlparse(href)
        if parsed.netloc.lower() != base_netloc and not parsed.netloc.lower().endswith("." + base_netloc):
            continue

        combo = f"{href} {link_text}".lower()
        if any(k in combo for k in keywords):
            if not any(ex in href.lower() for ex in [".jpg", ".png", ".pdf", "privacy", "cookie", "login", "vacature", "agenda", "nieuws"]):
                clean = href.split("#")[0]
                if clean not in seen and clean != base_url:
                    seen.add(clean)
                    candidates.append(clean)
                    if len(candidates) >= max_urls:
                        break

    return candidates


def run_fallback_extraction(
    client: Any,
    model: str,
    job: JobDefinition,
    museum: Dict[str, Any],
    fetcher: PoliteFetcher,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
    """
    Non-agentic targeted fetch + single extraction call.
    Returns (extracted_record, trace_messages, total_pages_fetched).
    """
    website = museum.get("museum_website")
    if not website:
        return {
            "status": "unknown",
            "primary_adult_eur": None,
            "adult_eur": None,
            "quote": None,
            "source_url": None,
            "reason": "Museum has no website configured.",
            "confidence": "low",
            "entered_by": "agent",
        }, [], 0

    # 1. Fetch homepage
    success, home_html, err = fetcher.fetch(website)
    pages_fetched = 1
    if not success or not home_html:
        status = "blocked_by_bot_protection" if err == "blocked_by_bot_protection" else ("blocked_by_robots" if err == "blocked_by_robots" else "unknown")
        confidence = status if status in ("blocked_by_bot_protection", "blocked_by_robots") else "low"
        return {
            "status": status,
            "primary_adult_eur": None,
            "adult_eur": None,
            "free_for": [],
            "offerings": [],
            "combo_available": None,
            "quote": None,
            "source_url": website,
            "reason": f"Homepage fetch failed: {err}",
            "confidence": confidence,
            "entered_by": "agent",
        }, [], pages_fetched

    # 2. Find candidate pricing pages
    candidates = find_candidate_urls(home_html, website)
    pages_content = []

    # Home page content
    home_sanitized = sanitize_html_for_agent(home_html, website, max_chars=8000)
    pages_content.append(f'<untrusted_web_content url="{website}">\n{home_sanitized["text"]}\n</untrusted_web_content>')

    for cand_url in candidates:
        succ, c_html, c_err = fetcher.fetch(cand_url)
        pages_fetched += 1
        if succ and c_html:
            sanitized = sanitize_html_for_agent(c_html, cand_url, max_chars=8000)
            pages_content.append(f'<untrusted_web_content url="{cand_url}">\n{sanitized["text"]}\n</untrusted_web_content>')

    combined_text = "\n\n".join(pages_content)

    prompt = f"""You are an expert museum data extractor.
Target Museum: {museum.get('name')} in {museum.get('city')}
Website: {website}

OBJECTIVE:
Extract the {job.title}.
{job.description_en}

RULES:
1. Standard single adult ticket for the museum itself ONLY.
2. NEVER select combo or duo tickets. If only combo tickets exist, status="combo_only".
3. Free admission: status="free" requires primary_adult_eur=null and an explicit quote stating admission is free for everyone.
4. Paid tickets: primary_adult_eur between 1.00 and 45.00 EUR.
5. Quote must appear verbatim in the text below, MAXIMUM 15 words.
6. Calibrated confidence: "high" (clearly labelled adult price on static page), "medium" (age-tier or multi-tier), "low" (uncertain).
7. Audiences with free admission (free_for): Select only applicable groups from:
   ["children_under_4", "children_under_12", "children_under_18", "youth", "students", "seniors", "museumkaart", "vriendenloterij_vip_kaart", "icom", "rembrandtkaart", "everyone", "other"]

=== RAW WEBPAGES ===
{combined_text}

Output ONLY a JSON object formatted exactly as:
{{
  "status": "paid",
  "primary_adult_eur": 15.00,
  "free_for": ["children_under_18", "museumkaart"],
  "combo_available": false,
  "offerings": [],
  "quote": "Exact quote from page",
  "source_url": "https://example.com/tickets",
  "reason": "Short reason",
  "confidence": "high"
}}
(Allowed status values: "paid", "free", "closed", "combo_only", "blocked_by_bot_protection", "not_found", "unknown". Note: For status="free", set primary_adult_eur: null.)
"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    try:
        resp = client.chat_completion(model=model, messages=messages, temperature=0.0, json_mode=True)
        data = extract_json_payload(resp)
        if data and "status" in data:
            data["entered_by"] = "agent"
            return data, messages, pages_fetched
    except Exception as e:
        logger.error(f"Fallback extraction call failed: {e}")

    return {
        "status": "unknown",
        "primary_adult_eur": None,
        "adult_eur": None,
        "quote": None,
        "source_url": website,
        "reason": "Model extraction failed or produced invalid format.",
        "confidence": "low",
        "entered_by": "agent",
    }, messages, pages_fetched
