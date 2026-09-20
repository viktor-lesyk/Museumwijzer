"""Allowlisted tool: web_search. Returns search result pointers (title, url, snippet).

SEARCH RESULTS ARE POINTERS ONLY; ALL EVIDENCE MUST COME FROM fetch_page.
Never exposes any sensitive MCP or personal tools.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

WEB_SEARCH_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for museum ticket pages or visiting information. "
            "Returns a list of candidate URLs and snippets. "
            "NOTE: Search snippets are pointers only and do NOT count as evidence; "
            "you MUST use fetch_page to read the actual museum page."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'Rijksmuseum Amsterdam tickets prijzen'."
                }
            },
            "required": ["query"]
        }
    }
}


def _search_tavily(query: str, api_key: str) -> List[Dict[str, str]]:
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": 5, "search_depth": "basic"},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:300],
                }
                for r in data.get("results", [])
            ]
        else:
            logger.warning(f"Tavily search HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Tavily search error: {e}")
    return []


def _search_brave(query: str, api_key: str) -> List[Dict[str, str]]:
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for r in data.get("web", {}).get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", "")[:300],
                })
            return results
        else:
            logger.warning(f"Brave search HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Brave search error: {e}")
    return []


def execute_web_search(query: str) -> Dict[str, Any]:
    """Execute search across configured provider (Tavily, Brave, or fallback)."""
    # 1. Check Tavily
    tavily_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_key:
        tavily_url = os.environ.get("TAVILY_MCP_URL", "")
        m = re.search(r"tavilyApiKey=([a-zA-Z0-9_-]+)", tavily_url)
        if m:
            tavily_key = m.group(1)

    if tavily_key:
        results = _search_tavily(query, tavily_key)
        if results:
            return {
                "query": query,
                "provider": "tavily",
                "results": results,
                "note": "POINTERS ONLY: You must fetch the actual URL using fetch_page before citing any evidence.",
            }

    # 2. Check Brave
    brave_key = os.environ.get("BRAVE_API_KEY")
    if brave_key:
        results = _search_brave(query, brave_key)
        if results:
            return {
                "query": query,
                "provider": "brave",
                "results": results,
                "note": "POINTERS ONLY: You must fetch the actual URL using fetch_page before citing any evidence.",
            }

    # 3. Fallback when no search API key configured
    return {
        "query": query,
        "provider": "none",
        "results": [],
        "note": "Web search provider not configured or returned no results. Use fetch_page directly on the museum website.",
    }
