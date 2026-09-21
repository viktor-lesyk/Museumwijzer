"""Agentic function-calling runner for museum enrichment."""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from enrich.fetch import PoliteFetcher
from enrich.jobs.base import JobDefinition
from enrich.tools import AGENT_TOOLS, execute_fetch_page, execute_web_search

logger = logging.getLogger("enrich.agent")

MAX_TOOL_CALLS = 8


def build_system_prompt(job: JobDefinition, museum: Dict[str, Any]) -> str:
    return f"""You are an autonomous museum data research agent.
Your mission is to find the official admission price for:
Museum: {museum.get('name')}
City: {museum.get('city')}
Website: {museum.get('museum_website')}

OBJECTIVE:
Extract the {job.title}.
{job.description_en}

STRICT CONSTRAINTS:
1. Standard single-entry adult ticket for the museum itself ONLY.
2. NEVER select combo, combi, duo, or joint tickets with other attractions.
   If only combo tickets exist, record status="combo_only".
3. Free admission: status="free" requires an explicit quote stating admission is free for everyone.
   Free-for-children does NOT qualify as free admission.
4. Paid admission: primary_adult_eur must be between 1.00 and 45.00 EUR.
5. Quote: Must be a literal verbatim substring from the fetched page, MAXIMUM 15 words.
6. Calibrated confidence:
   - "high": Single clearly labelled adult ticket price found directly on official static ticket/pricing page.
   - "medium": Multi-tier pricing (castle vs garden, peak/off-peak, online vs desk), secondary subpage, or complex options.
   - "low": Uncertain or inferred.
7. Audiences with free admission (free_for): Select only applicable groups from:
   ["children_under_4", "children_under_12", "children_under_18", "youth", "students", "seniors", "museumkaart", "vriendenloterij_vip_kaart", "icom", "rembrandtkaart", "everyone", "other"]
8. Tools available:
   - fetch_page(url): Fetch and read the webpage.
   - web_search(query): Find candidate ticket URLs. Pointers only; evidence must come from fetch_page!
9. When finished, output ONLY a JSON object formatted exactly as:
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
(Allowed status values: "paid", "free", "closed", "combo_only", "blocked_by_bot_protection", "not_found", "unknown".)
"""


def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from markdown or raw text and clean dictionary-wrapped fields."""
    text = text.strip()
    data = None
    # Check for ```json ... ``` blocks
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
        except Exception:
            pass

    if not data:
        # Find outermost curly braces
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except Exception:
                pass

    if isinstance(data, dict):
        for k in ["status", "confidence"]:
            v = data.get(k)
            if isinstance(v, dict):
                val = v.get("value") or v.get("type") or (v.get("enum") and v.get("enum")[0])
                data[k] = str(val) if val else "unknown"
            elif v is not None:
                data[k] = str(v)

        val = data.get("primary_adult_eur")
        if val is None:
            val = data.get("adult_eur")
        if isinstance(val, dict):
            val = val.get("value")
        if val is not None:
            try:
                data["primary_adult_eur"] = float(val)
            except (ValueError, TypeError):
                data["primary_adult_eur"] = None
        else:
            data["primary_adult_eur"] = None
        # Keep adult_eur in sync for backward compatibility
        data["adult_eur"] = data["primary_adult_eur"]

        if "free_for" not in data or not isinstance(data.get("free_for"), list):
            data["free_for"] = []
        if "offerings" not in data or not isinstance(data.get("offerings"), list):
            data["offerings"] = []
        if "combo_available" not in data:
            data["combo_available"] = None

        return data

    return None


def run_agentic_research(
    client: Any,
    model: str,
    job: JobDefinition,
    museum: Dict[str, Any],
    fetcher: PoliteFetcher,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
    """
    Run agentic loop with tool calling up to MAX_TOOL_CALLS.
    Returns (extracted_record, trace_messages, total_tool_calls).
    """
    system_prompt = build_system_prompt(job, museum)
    website = museum.get("museum_website")

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Please research the admission price for {museum.get('name')} in {museum.get('city')}. Official website is {website or 'unknown'}. Start by inspecting the website or searching.",
        },
    ]

    tool_call_count = 0
    max_steps = 10

    for step in range(max_steps):
        logger.info(f"Agent step {step+1} for {museum.get('slug')} (tool calls so far: {tool_call_count})...")
        msg = client.chat_with_tools(
            model=model,
            messages=messages,
            tools=AGENT_TOOLS,
            temperature=0.0,
        )
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            # Model responded with final text, attempt JSON parsing
            content = msg.get("content", "")
            data = extract_json_payload(content)
            if data and "status" in data and "admission" in data:
                data["entered_by"] = "agent"
                return data, messages, tool_call_count
            else:
                # Ask model to format final answer as JSON
                messages.append({
                    "role": "user",
                    "content": "Please output the final result as a valid JSON object matching the required schema.",
                })
                continue

        # Execute tool calls
        for tc in tool_calls:
            tool_call_count += 1
            func = tc.get("function", {})
            name = func.get("name")
            tc_id = tc.get("id", f"call_{tool_call_count}")

            try:
                args = json.loads(func.get("arguments", "{}"))
            except Exception:
                args = {}

            if name == "fetch_page":
                url = args.get("url", "")
                result = execute_fetch_page(url, fetcher)
            elif name == "web_search":
                query = args.get("query", "")
                result = execute_web_search(query)
            else:
                result = {"error": f"Unknown tool: {name}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": json.dumps(result, ensure_ascii=False),
            })

            if tool_call_count >= MAX_TOOL_CALLS:
                logger.warning(f"Reached max tool calls limit ({MAX_TOOL_CALLS}) for {museum.get('slug')}.")
                break

        if tool_call_count >= MAX_TOOL_CALLS:
            messages.append({
                "role": "user",
                "content": "Tool call budget reached. Please synthesize your findings and return the final JSON object.",
            })

    # Final attempt to get JSON
    final_text = client.chat_completion(model=model, messages=messages, temperature=0.0)
    data = extract_json_payload(final_text)
    if data:
        data["entered_by"] = "agent"
        return data, messages, tool_call_count

    return {
        "status": "unknown",
        "admission": "unknown",
        "adult_eur": None,
        "quote": None,
        "source_url": None,
        "reason": "Agent did not produce valid JSON response after execution.",
        "confidence": "low",
        "entered_by": "agent",
    }, messages, tool_call_count
