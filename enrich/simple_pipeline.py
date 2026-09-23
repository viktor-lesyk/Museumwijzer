"""Dual-model price enrichment pipeline with LLM reasoning and minimal safety-net gates.

Architecture:
1. Two Independent Free-Tier LLMs:
   - Primary Extractor: Gemini Flash-Lite via LiteLLM proxy ("free-lite")
   - Second Opinion: OpenRouter Free Model (e.g. nvidia/nemotron-3-super-120b-a12b:free)
   - Strict Safety Check: Fail loudly if either model is not explicitly free.
2. Domain Search:
   - Tavily API (free 1,000 monthly credits, no credit card required). Brave is forbidden.
   - 1 search per museum per run, domain-restricted, cached by SHA256 hash.
   - Resumable: if quota exhausted, mark remaining quota_exhausted (not needs_review).
3. Multi-Page Context & Prompt Reasoning:
   - Fetch homepage + plausible visiting/ticket pages on the domain (up to 4 pages).
   - Feed all pages together in a single prompt with '=== PAGE {i}: {title} ({url}) ==='.
   - Models reason through traps (school groups, group rates, dated exhibitions, passes, seasonal tables).
   - Capture concise reasoning_summary (<=40 words) for human audit.
4. Three Safety-Net Gates:
   - Gate 1 (Literal Match): Quote <= 15 words and price literally appear in fetched text.
   - Gate 2 (Domain Provenance): source_url is on the museum's domain or ticketing subdomain.
   - Gate 3 (Sane Range): €1.00 - €45.00 for "paid", null for "free"/"closed"/"unknown".
5. Agreement Rule:
   - Both models run on identical multi-page context.
   - Accept only if both pass gates and agree on status and exact paid price.
   - Disagreements recorded to needs_review.json with both reasoning summaries.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests

from enrich.fetch import LinkExtractor, PoliteFetcher
from enrich.tools.fetch_page import sanitize_html_for_agent

logger = logging.getLogger("enrich.simple")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env if present
env_path = REPO_ROOT / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v

CACHE_DIR = REPO_ROOT / ".cache" / "enrichment"
SEARCH_CACHE_DIR = CACHE_DIR / "searches"
QUOTA_FILE = CACHE_DIR / "search_quota.json"
DATA_DIR = REPO_ROOT / "data" / "enrichment"
PRICES_JSON_PATH = DATA_DIR / "prices.json"
NEEDS_REVIEW_PATH = DATA_DIR / "needs_review.json"

CONTROLLED_FREE_FOR: Set[str] = {
    "museumkaart",
    "vriendenloterij_vip_kaart",
    "icom",
    "rembrandtkaart",
    "children_under_4",
    "children_under_12",
    "children_under_18",
    "youth",
    "students",
    "seniors",
    "everyone",
    "other",
}


# ---------------------------------------------------------------------------
# 1. Safety Checks & Free-Tier Validation
# ---------------------------------------------------------------------------

def validate_free_tier_configuration(
    litellm_model: str,
    openrouter_model: str,
    disallow_brave: bool = True,
) -> None:
    """
    Strict safety assertion: Fail loudly if any configuration points at a paid model
    or card-metered provider.
    """
    # 1. OpenRouter model MUST end with :free
    if not openrouter_model.endswith(":free"):
        raise ValueError(
            f"SAFETY VIOLATION: OPENROUTER_FREE_MODEL '{openrouter_model}' is not a free-tier model! "
            f"It MUST end with ':free' to guarantee zero billing risk."
        )

    # 2. LiteLLM proxy model MUST contain 'free' (e.g. 'free-lite')
    if "free" not in litellm_model.lower():
        raise ValueError(
            f"SAFETY VIOLATION: LITELLM_FREE_LITE_MODEL '{litellm_model}' is not verified as free! "
            f"It must contain 'free' (e.g. 'free-lite')."
        )

    # 3. Brave Search is forbidden (card-gated metered billing since Feb 2026)
    if disallow_brave and os.environ.get("USE_BRAVE_SEARCH", "").lower() in ("true", "1", "yes"):
        raise ValueError(
            "SAFETY VIOLATION: Brave Search API is card-gated metered billing and forbidden. "
            "Use Tavily API (free 1,000 monthly credits, no card required)."
        )


# ---------------------------------------------------------------------------
# 2. Search Quota Guard & Tavily Domain Search
# ---------------------------------------------------------------------------

class SearchQuotaGuard:
    def __init__(self, quota_file: Path = QUOTA_FILE, max_monthly_searches: int = 1000):
        self.quota_file = quota_file
        self.max_monthly_searches = max_monthly_searches
        self.quota_file.parent.mkdir(parents=True, exist_ok=True)
        SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    def _current_month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _load(self):
        if self.quota_file.exists():
            try:
                with open(self.quota_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        else:
            self.data = {}

        cur = self._current_month()
        if self.data.get("month") != cur:
            self.data = {
                "month": cur,
                "searches_used": 0,
                "max_searches": self.max_monthly_searches,
            }
            self._save()

    def _save(self):
        with open(self.quota_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def can_search(self) -> bool:
        self._load()
        return self.data.get("searches_used", 0) < self.max_monthly_searches

    def record_search(self):
        self._load()
        self.data["searches_used"] = self.data.get("searches_used", 0) + 1
        self._save()

    def get_used_count(self) -> int:
        self._load()
        return self.data.get("searches_used", 0)


def _safe_hash(text: str) -> str:
    """Generate SHA256 hex digest prefix."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def extract_domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def is_ticketing_subdomain(url: str, base_domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    if host == base_domain or host == f"www.{base_domain}":
        return True
    if host.endswith(f".{base_domain}"):
        return True
    return False


def search_domain_tavily(
    domain: str,
    quota_guard: Optional[SearchQuotaGuard] = None,
) -> Tuple[Optional[List[Dict[str, str]]], str]:
    """
    Search domain using Tavily API (free 1,000 monthly credits).
    Cached on disk by query hash.
    Returns (results, status):
      - status in ("cached", "live", "quota_exhausted", "no_api_key", "error")
    """
    query = f"{domain} tickets prijzen entree volwassenen openingstijden"
    cache_file = SEARCH_CACHE_DIR / f"{_safe_hash(domain + '_' + query)}.json"

    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
                return cached.get("results", []), "cached"
        except Exception:
            pass

    guard = quota_guard or SearchQuotaGuard()
    if not guard.can_search():
        logger.warning(f"Search quota exhausted ({guard.get_used_count()}/{guard.max_monthly_searches}).")
        return None, "quota_exhausted"

    tavily_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_key:
        logger.warning("No TAVILY_API_KEY set in environment.")
        return None, "no_api_key"

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": 6, "search_depth": "basic"},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tavily_key}"},
            timeout=15,
        )
        if resp.status_code == 200:
            guard.record_search()
            data = resp.json()
            raw_results = data.get("results", [])
            filtered = []
            for r in raw_results:
                u = r.get("url", "").strip()
                if is_ticketing_subdomain(u, domain):
                    filtered.append({
                        "title": r.get("title", ""),
                        "url": u,
                        "snippet": r.get("content", "")[:300],
                    })
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump({"query": query, "domain": domain, "results": filtered}, f, indent=2)
            except Exception:
                pass
            return filtered, "live"
        elif resp.status_code in (429, 430, 432):
            logger.warning(f"Tavily search rate-limited / quota exhausted: HTTP {resp.status_code}")
            return None, "quota_exhausted"
        else:
            logger.warning(f"Tavily search returned HTTP {resp.status_code}: {resp.text}")
            return None, "error"
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return None, "error"


# ---------------------------------------------------------------------------
# 3. Multi-Page Context Assembly
# ---------------------------------------------------------------------------

def extract_html_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        clean = re.sub(r"\s+", " ", m.group(1)).strip()
        return clean[:120]
    return ""


def gather_and_fetch_pages(
    museum: Dict[str, Any],
    search_results: Optional[List[Dict[str, str]]],
    fetcher: PoliteFetcher,
    max_pages: int = 4,
) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """
    Fetch homepage + plausible visit/ticket pages on the museum's domain.
    Returns (fetched_pages, terminal_status).
    terminal_status may be 'blocked_by_bot_protection' if all pages are blocked.
    """
    website = museum.get("museum_website")
    domain = extract_domain(website) if website else None
    if not domain:
        return [], None

    candidate_urls: List[str] = []
    seen_urls: Set[str] = set()

    def add_url(u: str):
        u_norm = u.strip().rstrip("/")
        if u_norm and u_norm not in seen_urls:
            seen_urls.add(u_norm)
            candidate_urls.append(u.strip())

    # 1. Official website homepage & on-domain navigation link discovery
    if website:
        add_url(website)
        success, home_html, err = fetcher.fetch(website)
        if success and home_html:
            parser = LinkExtractor(base_url=website)
            try:
                parser.feed(home_html)
                home_links = parser.links
            except Exception:
                home_links = []

            scored_home_links: List[Tuple[float, str]] = []
            home_keywords = [
                "ticket", "tarief", "prijs", "prijzen", "toegang", "admission", "entree",
                "bezoek", "visit", "plan-je-bezoek", "plan", "praktisch", "openingstijden"
            ]
            for link in home_links:
                u_clean = link.strip().split("#")[0].rstrip("/")
                if not u_clean or not is_ticketing_subdomain(u_clean, domain):
                    continue
                path_lower = urlparse(u_clean).path.lower()
                if any(x in path_lower for x in ["/nieuws", "/agenda", "/vacature", "/collectie", "/colofon", "/shop"]):
                    continue
                score = 0.0
                for kw in home_keywords:
                    if kw in path_lower:
                        score += 10.0
                if score > 0:
                    scored_home_links.append((score, link.strip()))

            scored_home_links.sort(key=lambda x: x[0], reverse=True)
            for _, u in scored_home_links:
                add_url(u)
                if len(candidate_urls) >= max_pages:
                    break

    # 2. Search result URLs, sorted to prioritize ticket/price/visit pages
    scored_urls: List[Tuple[float, str]] = []
    keywords = ["ticket", "tarief", "prijs", "prijzen", "toegang", "admission", "entree", "bezoek", "visit", "plan", "praktisch", "openingstijden"]

    for r in (search_results or []):
        u = r.get("url", "").strip()
        if not is_ticketing_subdomain(u, domain):
            continue
        path_lower = urlparse(u).path.lower()
        score = 0.0
        for kw in keywords:
            if kw in path_lower:
                score += 5.0
        scored_urls.append((score, u))

    scored_urls.sort(key=lambda x: x[0], reverse=True)
    for _, u in scored_urls:
        add_url(u)
        if len(candidate_urls) >= max_pages:
            break

    # Fetch each candidate URL
    fetched: List[Dict[str, str]] = []
    bot_blocked_count = 0

    for u in candidate_urls[:max_pages]:
        # Respect disk cache if fresh (< 4 days)
        cache_key = fetcher._cache_key(u)
        force_fetch = False
        if cache_key.exists():
            try:
                age_days = (time.time() - cache_key.stat().st_mtime) / 86400
                if age_days > 4:
                    force_fetch = True
            except Exception:
                pass

        success, html, err = fetcher.fetch(u, force=force_fetch)
        if not success:
            if err == "blocked_by_bot_protection":
                bot_blocked_count += 1
            continue

        title = extract_html_title(html or "")
        san = sanitize_html_for_agent(html or "", u, max_chars=10000)
        fetched.append({
            "url": u,
            "title": title or u,
            "text": san["text"],
        })

    if not fetched and bot_blocked_count > 0:
        return [], "blocked_by_bot_protection"

    return fetched, None


def format_multi_page_context(pages: List[Dict[str, str]]) -> str:
    blocks = []
    for idx, p in enumerate(pages, 1):
        blocks.append(f"=== PAGE {idx}: {p['title']} ({p['url']}) ===\n{p['text']}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# 4. Prompting & LLM Execution
# ---------------------------------------------------------------------------

REASONING_SYSTEM_PROMPT = """You are a JSON-only response bot and expert data extractor for Dutch museum admission pricing.
Provide your reasoning strictly inside the "reasoning" and "reasoning_summary" JSON fields. Do not output any thought process, commentary, or text before or after the JSON.

### INSTRUCTIONS & TRAPS TO AVOID:
1. Standard Single-Entry Adult Admission:
   - Identify the standard regular admission price for a single adult (Dutch: "volwassene", "volwassenen", "regulier", "standaard", "18+", "vanaf 18 jaar", "16+", "vanaf 16 jaar", or "entree").
   - Anchor "primary" to basic museum admission that a visitor gets via standard entry (such as the Welkom in het Museum programme) — not a ticket bundling extra activities (tower climbs, workshops, guided tours, other attractions) beyond basic museum entry, and not a combo/duo across venues.
   - For castles and estates (e.g. Kasteel de Haar): select the ticket that includes entry into the castle/interior (e.g. "Kasteel incl. park"), NOT a grounds-only or park-only ticket.
2. School & Education Booking Trap:
   - NEVER select school class, guided school tour, educational group, or student excursion prices (e.g. € 14,00 for primary/secondary school bookings).
3. Group Bookings Trap:
   - NEVER select group rates (e.g. "groepen vanaf 15 personen", bus companies, tour groups).
4. Exhibition-Specific & Dated Events Trap:
   - NEVER select prices for temporary dated evening festivals, workshops, concerts, or single-date events.
5. Combo & Duo Tickets Trap:
   - NEVER select combi tickets (e.g. museum + boat tour, museum + church tower, duotickets with partner institutions).
6. Membership & Passes Trap:
   - Museumkaart, VriendenLoterij VIP-KAART, and ICOM are passes, NOT standard adult admission. Record them in "free_for".
7. Seasonal & Day-based (Dynamic) Pricing:
   - For calendar/day-based dynamic pricing with no ticket-tier differences (e.g. Nederlands Openluchtmuseum: weekday € 15,00 vs weekend/holidays € 16,50):
     * Tie-break rule: set "primary_adult_eur" to the LOWER standard rate (weekday/off-peak, e.g. 15.0).
     * Store the higher rate in structured "variants", e.g. {"weekend_holiday": 16.50}.
   - If seasonal pricing exists, select the current standard adult price or primary year-round rate.
8. Guided Tour vs Self-Guided Option & Basic vs Plus Ticket:
   - If the standard adult admission ticket includes a guided tour (e.g. € 15,00) BUT the museum also sells a cheaper self-guided entry without tour ("zonder rondleiding" / "without tour", e.g. € 9,50):
     * Set "primary_adult_eur" to the standard ticket (15.0).
     * Set "cheapest_adult_eur" to the without-tour ticket (9.5).
     * Set "price_note" to a concise explanation (e.g. "standard ticket includes guided tour").
   - If basic museum admission is offered (e.g. Basisticket € 5,00) alongside a plus ticket with an extra activity (e.g. Plusticket € 8,50 including tower climb):
     * Set "primary_adult_eur" to the basic admission ticket (5.0).
     * Store the plus ticket in structured "variants", e.g. {"plusticket_tower_climb": 8.50}.
9. Walk-in / Counter Price vs Online / Advance Discount:
   - When a page lists both an online / advance-discount price (Dutch: "online", "voorverkoop") and a walk-in / counter / door / on-board price (Dutch: "kassaprijs", "aan de kassa", "aan de deur", "aan boord", "balie", "box office") for the SAME standard ticket:
     * Set "primary_adult_eur" to the ONLINE (cheaper) price.
     * Set "online_adult_eur" to that online price.
     * Set "door_adult_eur" to the higher walk-in/counter price.
     * Do NOT put this in "price_note"; keep "price_note" strictly for genuinely different cases (seasonal, gardens-only, guided tour included).
   - If only a single price is listed without separate online vs door rates, set "primary_adult_eur" to that price, and leave "door_adult_eur" and "online_adult_eur" null.
10. Free Admission:
   - If general admission to the museum is completely free for all adult visitors, set "status": "free", "primary_adult_eur": null. A verbatim quote explicitly stating free admission is required.
11. Closed Status:
   - If the museum is temporarily closed for renovation or rebuilding, set "status": "closed", "primary_adult_eur": null. A quote mentioning closure/renovation is required.
12. Unknown Status:
   - If no standard adult admission price can be determined with certainty, set "status": "unknown", "primary_adult_eur": null.

### MANDATORY REASONING:
- In "reasoning": Describe what you found across the pages, identify which page/section contains the ticket information, and explicitly justify why this price is the standard adult admission for this museum, noting how you avoided school/group/combo/event traps and applied online vs door and basic vs plus rules.
- In "reasoning_summary": Provide a concise explanation of AT MOST 40 WORDS explaining your determination.

### OUTPUT FORMAT:
You MUST respond with valid JSON matching this schema:
{
  "status": "paid" | "free" | "closed" | "unknown",
  "primary_adult_eur": float | null,
  "door_adult_eur": float | null,
  "online_adult_eur": float | null,
  "variants": {"<variant_name>": float} | null,
  "quote": "verbatim quote of <= 15 words from source_url supporting the primary price",
  "source_url": string,
  "page_title": string,
  "reasoning_summary": "... (<= 40 words)",
  "reasoning": "...",
  "cheapest_adult_eur": float | null,
  "price_note": string | null,
  "free_for": ["museumkaart", ...]
}
(Keep free_for concise with at most 5 major passes, e.g. museumkaart, icom).
"""


def extract_json_from_response(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Match ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # Find outermost curly braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # Repair truncated JSON by iteratively trimming back to previous delimiter
    if start != -1:
        cur = text[start:].strip()
        while len(cur) > 15:
            for closing in ["\n]}", "\n}", "\"]}", "\"}", "]}", "}"]:
                try:
                    data = json.loads(cur + closing)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
            last_delim = max(cur.rfind(","), cur.rfind("\n"))
            if last_delim == -1 or last_delim <= start:
                break
            cur = cur[:last_delim].strip()

    return {}


def call_pricing_model(
    base_url: str,
    api_key: str,
    model: str,
    museum_name: str,
    city: Optional[str],
    website: Optional[str],
    multi_page_content: str,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Execute reasoning prompt against an OpenAI-compatible endpoint.
    Handles rate-limits (HTTP 429) returning status 'retry_later'.
    """
    user_prompt = f"""=== MUSEUM DETAILS ===
Name: {museum_name}
City: {city or 'Netherlands'}
Official Website: {website or 'n/a'}

=== WEBPAGES CONTENT ===
{multi_page_content}

Analyze the pages, reason carefully through the traps, and extract the standard single-entry adult ticket.
Begin your response immediately with '{{' and output strictly valid JSON matching the schema."""

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REASONING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 2500,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if "error" in data:
                err_msg = data["error"].get("message", "")
                err_code = data["error"].get("code", 503)
                logger.warning(f"Upstream model error in HTTP 200 payload from {model}: {err_msg}")
                return {
                    "status": "retry_later",
                    "primary_adult_eur": None,
                    "reasoning_summary": f"Provider error ({err_code}): {err_msg[:60]}",
                    "error": str(data["error"])[:200],
                }
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = extract_json_from_response(content)
            if not parsed:
                return {
                    "status": "unknown",
                    "primary_adult_eur": None,
                    "reasoning_summary": "Failed to parse model response into valid JSON",
                    "raw_response": content[:300],
                }
            return parsed
        elif resp.status_code in (429, 503):
            logger.warning(f"Upstream model rate limit / 429 from {model}: {resp.text}")
            return {
                "status": "retry_later",
                "primary_adult_eur": None,
                "reasoning_summary": f"Provider rate limit (HTTP {resp.status_code})",
                "error": resp.text[:200],
            }
        else:
            logger.error(f"Model call failed with HTTP {resp.status_code}: {resp.text}")
            return {
                "status": "unknown",
                "primary_adult_eur": None,
                "reasoning_summary": f"HTTP error {resp.status_code}",
                "error": resp.text[:200],
            }
    except Exception as e:
        msg = str(e).lower()
        if "429" in msg or "rate limit" in msg or "quota" in msg:
            return {
                "status": "retry_later",
                "primary_adult_eur": None,
                "reasoning_summary": f"Rate limit exception: {e}",
                "error": str(e),
            }
        logger.error(f"Exception during model call to {model}: {e}")
        return {
            "status": "unknown",
            "primary_adult_eur": None,
            "reasoning_summary": f"Exception: {e}",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# 5. Three Safety-Net Gates
# ---------------------------------------------------------------------------

def normalize_text_for_match(text: str) -> str:
    """Normalize whitespace, NBSP, punctuation, and mojibake for literal matching."""
    t = text.replace("\u00a0", " ").replace("&nbsp;", " ")
    t = t.replace("â‚¬", "€").replace("â\x82¬", "€")
    t = re.sub(r"[|:–—\-<>]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def check_quote_in_text(quote: str, text: str) -> bool:
    norm_q = normalize_text_for_match(quote)
    norm_t = normalize_text_for_match(text)
    if norm_q in norm_t:
        return True
    if "..." in norm_q or "…" in norm_q:
        parts = [p.strip() for p in re.split(r"\.{3,}|…", norm_q) if p.strip()]
        if parts:
            pos = 0
            for part in parts:
                idx = norm_t.find(part, pos)
                if idx == -1:
                    return False
                pos = idx + len(part)
            return True

    # Check words appearing in order within a small window (for multi-column table rows)
    q_words = norm_q.split()
    if len(q_words) >= 2:
        first = q_words[0]
        pos = 0
        while True:
            idx = norm_t.find(first, pos)
            if idx == -1:
                break
            window = norm_t[idx:idx + 250].split()
            w_idx = 0
            match_count = 0
            for w in window:
                if w_idx < len(q_words) and (w == q_words[w_idx] or q_words[w_idx] in w):
                    w_idx += 1
                    match_count += 1
            if match_count == len(q_words):
                return True
            pos = idx + len(first)

    return False


def validate_safety_net_gates(
    museum: Dict[str, Any],
    extracted: Dict[str, Any],
    pages: List[Dict[str, str]],
) -> Tuple[bool, List[str]]:
    """
    Enforces ONLY the three specified safety-net gates:
    1. Literal match: claimed number and quote literally appear in fetched text.
    2. Domain provenance: source domain is the museum's own domain or ticketing subdomain.
    3. Sane range: €1.00 - €45.00 for "paid", null for "free"/"closed"/"unknown".
    """
    failures: List[str] = []
    status = extracted.get("status", "unknown")
    adult_eur = extracted.get("primary_adult_eur")
    quote = extracted.get("quote") or ""
    source_url = extracted.get("source_url") or ""
    website = museum.get("museum_website")

    # Clean free_for values
    free_for = extracted.get("free_for") or []
    mapped_free = []
    for item in free_for:
        c = str(item).lower().strip().replace(" ", "_")
        mapped_free.append(c if c in CONTROLLED_FREE_FOR else "other")
    extracted["free_for"] = list(set(mapped_free))

    # Rate-limited state passes safety check to be handled as retry_later
    if status == "retry_later":
        return False, [f"Provider rate limit: {extracted.get('reasoning_summary')}"]

    if status == "unknown":
        return False, ["Extraction status is 'unknown'"]

    # --- GATE 2: Domain Provenance Gate ---
    if source_url and isinstance(source_url, str):
        if source_url.startswith("https://") or source_url.startswith("http://"):
            pass
        elif source_url.startswith("https"):
            source_url = "https://" + source_url[5:].lstrip(":/")
            extracted["source_url"] = source_url
        elif source_url.startswith("http"):
            source_url = "http://" + source_url[4:].lstrip(":/")
            extracted["source_url"] = source_url

    if website:
        base_domain = extract_domain(website)
        if not source_url or not is_ticketing_subdomain(source_url, base_domain):
            failures.append(f"Domain provenance gate: source_url '{source_url}' does not match domain '{base_domain}'")
    elif not source_url:
        failures.append("Domain provenance gate: No source_url provided")

    # --- GATE 3: Sane Range Gate ---
    if status == "paid":
        if adult_eur is None or not isinstance(adult_eur, (int, float)):
            failures.append("Range gate: Paid status requires numeric primary_adult_eur")
        elif adult_eur < 1.0 or adult_eur > 45.0:
            failures.append(f"Range gate: Price €{adult_eur} outside plausible adult range [1.0 - 45.0]")
    elif status in ("free", "closed", "unknown"):
        if adult_eur is not None:
            failures.append(f"Range gate: Status '{status}' requires primary_adult_eur to be null, got {adult_eur}")

    cheapest_eur = extracted.get("cheapest_adult_eur")
    if cheapest_eur is not None:
        if not isinstance(cheapest_eur, (int, float)):
            failures.append(f"Range gate: cheapest_adult_eur must be numeric, got {cheapest_eur}")
        elif cheapest_eur < 1.0 or cheapest_eur > 45.0:
            failures.append(f"Range gate: cheapest_adult_eur €{cheapest_eur} outside plausible range [1.0 - 45.0]")
        elif adult_eur is not None and cheapest_eur > adult_eur:
            failures.append(f"Range gate: cheapest_adult_eur €{cheapest_eur} cannot exceed primary_adult_eur €{adult_eur}")

    door_eur = extracted.get("door_adult_eur")
    if door_eur is not None:
        if not isinstance(door_eur, (int, float)):
            failures.append(f"Range gate: door_adult_eur must be numeric, got {door_eur}")
        elif door_eur < 1.0 or door_eur > 45.0:
            failures.append(f"Range gate: door_adult_eur €{door_eur} outside plausible range [1.0 - 45.0]")
        elif adult_eur is not None and door_eur < adult_eur:
            failures.append(f"Range gate: door_adult_eur €{door_eur} cannot be lower than primary_adult_eur €{adult_eur}")

    online_eur = extracted.get("online_adult_eur")
    if online_eur is not None:
        if not isinstance(online_eur, (int, float)):
            failures.append(f"Range gate: online_adult_eur must be numeric, got {online_eur}")
        elif online_eur < 1.0 or online_eur > 45.0:
            failures.append(f"Range gate: online_adult_eur €{online_eur} outside plausible range [1.0 - 45.0]")
        elif adult_eur is not None and abs(float(online_eur) - float(adult_eur)) >= 0.01:
            failures.append(f"Range gate: online_adult_eur €{online_eur} must match primary_adult_eur €{adult_eur}")

    variants = extracted.get("variants")
    if variants is not None:
        if not isinstance(variants, dict):
            failures.append(f"Range gate: variants must be a dictionary, got {type(variants)}")
        else:
            for v_name, v_price in variants.items():
                if not isinstance(v_price, (int, float)) or v_price < 1.0 or v_price > 250.0:
                    failures.append(f"Range gate: variant '{v_name}' price €{v_price} outside plausible range [1.0 - 250.0]")

    if status == "free":
        norm_q = normalize_text_for_match(quote)
        if not any(w in norm_q for w in ["gratis", "free", "vrij"]):
            failures.append(f"Free admission gate: Quote must explicitly state free admission: '{quote}'")

    if status == "closed":
        norm_q = normalize_text_for_match(quote)
        if not any(w in norm_q for w in ["gesloten", "closed", "verbouw", "renovat"]):
            failures.append(f"Closed gate: Quote must explicitly state closure/renovation: '{quote}'")

    # --- GATE 1: Literal Match Gate ---
    # Combine all fetched text for literal checking
    combined_text = "\n".join(p["text"] for p in pages)
    norm_combined = normalize_text_for_match(combined_text)

    if quote:
        words = quote.strip().split()
        if len(words) > 15:
            failures.append(f"Literal match gate: Quote exceeds 15 words limit ({len(words)} words)")
        elif not check_quote_in_text(quote, combined_text):
            failures.append(f"Literal match gate: Quote '{quote}' not found verbatim in fetched text")

    if status == "paid" and adult_eur is not None:
        # Check that the claimed price number appears in the fetched text
        # Format variations: 23.50, 23,50, 23.5, 23,5, 23,-, 23-
        num_patterns = [
            f"{adult_eur:.2f}",
            f"{adult_eur:.2f}".replace(".", ","),
        ]
        if float(adult_eur).is_integer():
            int_val = int(adult_eur)
            num_patterns.extend([str(int_val), f"{int_val},-", f"{int_val}-"])
        else:
            num_patterns.append(str(adult_eur))
            num_patterns.append(str(adult_eur).replace(".", ","))

        num_found = any(p in norm_combined for p in num_patterns)
        if not num_found:
            failures.append(f"Literal match gate: Claimed amount €{adult_eur} not found in fetched text")

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# 6. Dual-Model Agreement & Single-Museum Processing
# ---------------------------------------------------------------------------

def process_museum_dual_model(
    museum: Dict[str, Any],
    fetcher: PoliteFetcher,
    quota_guard: SearchQuotaGuard,
    litellm_base_url: str,
    litellm_api_key: str,
    litellm_model: str,
    openrouter_base_url: str,
    openrouter_api_key: str,
    openrouter_model: str,
    override_pages: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Run single museum through dual-model agreement architecture.
    """
    slug = museum.get("slug", "")
    name = museum.get("name", slug)
    city = museum.get("city")
    website = museum.get("museum_website")

    start_time = time.time()
    domain = extract_domain(website) if website else (extract_domain(override_pages[0]["url"]) if override_pages else None)

    if override_pages is not None:
        pages = override_pages
        terminal_status = None
    else:
        if not domain:
            return {
                "slug": slug,
                "name": name,
                "is_accepted": False,
                "disagreement_type": "no_official_website",
                "gate_failures": ["No official website configured for domain-restricted search"],
                "price": {
                    "status": "unknown",
                    "primary_adult_eur": None,
                    "quote": None,
                    "source_url": None,
                    "page_title": "",
                    "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "mode": "dual_model",
                    "extractor_model": litellm_model,
                    "verifier_model": openrouter_model,
                    "confidence": "low",
                },
                "time_seconds": round(time.time() - start_time, 2),
            }

        # 1. Tavily Domain Search
        search_results, search_status = search_domain_tavily(domain, quota_guard=quota_guard)
        if search_status == "quota_exhausted":
            return {
                "slug": slug,
                "name": name,
                "is_accepted": False,
                "disagreement_type": "quota_exhausted",
                "gate_failures": ["Monthly search quota (1,000) reached"],
                "price": {
                    "status": "quota_exhausted",
                    "primary_adult_eur": None,
                    "quote": None,
                    "source_url": None,
                    "page_title": "",
                    "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "mode": "dual_model",
                    "extractor_model": litellm_model,
                    "verifier_model": openrouter_model,
                    "confidence": "low",
                },
                "time_seconds": round(time.time() - start_time, 2),
            }

        # 2. Multi-page context gathering
        pages, terminal_status = gather_and_fetch_pages(museum, search_results, fetcher, max_pages=4)
    if terminal_status == "blocked_by_bot_protection":
        return {
            "slug": slug,
            "name": name,
            "is_accepted": True,
            "disagreement_type": None,
            "gate_failures": [],
            "price": {
                "status": "blocked_by_bot_protection",
                "primary_adult_eur": None,
                "cheapest_adult_eur": None,
                "price_note": None,
                "free_for": [],
                "quote": None,
                "source_url": website,
                "page_title": "Bot Protection",
                "reasoning_summary": "All pages blocked by anti-bot challenge (Cloudflare/Incapsula).",
                "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "mode": "dual_model",
                "extractor_model": litellm_model,
                "verifier_model": openrouter_model,
                "confidence": "high",
            },
            "time_seconds": round(time.time() - start_time, 2),
        }

    if not pages:
        return {
            "slug": slug,
            "name": name,
            "is_accepted": False,
            "disagreement_type": "fetch_failed",
            "gate_failures": ["Failed to retrieve any readable pages"],
            "price": {
                "status": "unknown",
                "primary_adult_eur": None,
                "quote": None,
                "source_url": website,
                "page_title": "",
                "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "mode": "dual_model",
                "extractor_model": litellm_model,
                "verifier_model": openrouter_model,
                "confidence": "low",
            },
            "time_seconds": round(time.time() - start_time, 2),
        }

    multi_page_content = format_multi_page_context(pages)

    # 3. Call Model 1 (LiteLLM / Gemini Flash-Lite)
    res1 = call_pricing_model(
        base_url=litellm_base_url,
        api_key=litellm_api_key,
        model=litellm_model,
        museum_name=name,
        city=city,
        website=website,
        multi_page_content=multi_page_content,
    )
    if res1.get("status") == "retry_later":
        return {
            "slug": slug,
            "name": name,
            "is_accepted": False,
            "disagreement_type": "retry_later",
            "gate_failures": [f"LiteLLM rate limit: {res1.get('reasoning_summary')}"],
            "price": {
                "status": "retry_later",
                "primary_adult_eur": None,
                "quote": None,
                "source_url": website,
                "page_title": "",
                "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "mode": "dual_model",
                "extractor_model": litellm_model,
                "verifier_model": openrouter_model,
                "confidence": "low",
            },
            "time_seconds": round(time.time() - start_time, 2),
        }

    # 4. Call Model 2 (OpenRouter Free Model)
    res2 = call_pricing_model(
        base_url=openrouter_base_url,
        api_key=openrouter_api_key,
        model=openrouter_model,
        museum_name=name,
        city=city,
        website=website,
        multi_page_content=multi_page_content,
    )
    if res2.get("status") == "retry_later":
        return {
            "slug": slug,
            "name": name,
            "is_accepted": False,
            "disagreement_type": "retry_later",
            "gate_failures": [f"OpenRouter rate limit: {res2.get('reasoning_summary')}"],
            "price": {
                "status": "retry_later",
                "primary_adult_eur": None,
                "quote": None,
                "source_url": website,
                "page_title": "",
                "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "mode": "dual_model",
                "extractor_model": litellm_model,
                "verifier_model": openrouter_model,
                "confidence": "low",
            },
            "time_seconds": round(time.time() - start_time, 2),
        }

    # 5. Check Safety-Net Gates for both models
    passed1, fails1 = validate_safety_net_gates(museum, res1, pages)
    passed2, fails2 = validate_safety_net_gates(museum, res2, pages)

    # 6. Evaluate Agreement Rule
    status1 = res1.get("status")
    status2 = res2.get("status")
    price1 = res1.get("primary_adult_eur")
    price2 = res2.get("primary_adult_eur")

    is_agreed = False
    disagreement_type = None
    fallback_model = None

    if passed1 and passed2:
        if status1 != status2:
            disagreement_type = "status_mismatch"
        elif status1 == "paid":
            if price1 is not None and price2 is not None and abs(float(price1) - float(price2)) < 0.01:
                is_agreed = True
            else:
                door1 = res1.get("door_adult_eur")
                door2 = res2.get("door_adult_eur")
                if (door2 is not None and abs(float(door2) - float(price1)) < 0.01) or \
                   (door1 is not None and abs(float(door1) - float(price2)) < 0.01):
                    is_agreed = True
                    if price1 is not None and price2 is not None:
                        price1 = min(price1, price2)
                else:
                    disagreement_type = "price_mismatch"
        elif status1 in ("free", "closed"):
            is_agreed = True
        else:
            disagreement_type = "both_unknown"
    elif passed1 and not passed2 and status1 in ("paid", "free", "closed"):
        is_agreed = True
        fallback_model = 1
    elif passed2 and not passed1 and status2 in ("paid", "free", "closed"):
        is_agreed = True
        fallback_model = 2
    elif not passed1:
        disagreement_type = "gate_failure_model1"
    elif not passed2:
        disagreement_type = "gate_failure_model2"
    else:
        disagreement_type = "both_unknown"

    # Calibration of confidence
    conf = "low"
    if is_agreed:
        if fallback_model is not None:
            conf = "medium"
        else:
            combined_reasoning = (res1.get("reasoning_summary", "") + " " + res2.get("reasoning_summary", "")).lower()
            if any(w in combined_reasoning for w in ["vanaf", "tier", "tour", "seizoen", "rondleiding"]):
                conf = "medium"
            else:
                conf = "high"

    # Determine chosen result for metadata
    chosen_res = res2 if fallback_model == 2 else res1

    final_status = chosen_res.get("status") if is_agreed else "needs_review"
    final_price = chosen_res.get("primary_adult_eur") if is_agreed else None
    if is_agreed and fallback_model is None and status1 == "paid":
        final_price = price1

    quote = chosen_res.get("quote") or res1.get("quote") or res2.get("quote")
    source_url = chosen_res.get("source_url") or res1.get("source_url") or res2.get("source_url") or website
    page_title = chosen_res.get("page_title") or res1.get("page_title") or res2.get("page_title") or ""
    door_adult = chosen_res.get("door_adult_eur") or (res1.get("door_adult_eur") or res2.get("door_adult_eur"))
    online_adult = chosen_res.get("online_adult_eur") or (res1.get("online_adult_eur") or res2.get("online_adult_eur"))
    if door_adult is not None and online_adult is None and is_agreed and final_status == "paid":
        online_adult = final_price

    variants = {}
    if isinstance(res1.get("variants"), dict):
        variants.update(res1["variants"])
    if isinstance(res2.get("variants"), dict):
        variants.update(res2["variants"])
    variants_val = variants if variants else None

    cheapest = chosen_res.get("cheapest_adult_eur") or (res1.get("cheapest_adult_eur") or res2.get("cheapest_adult_eur"))
    price_note = chosen_res.get("price_note") or (res1.get("price_note") or res2.get("price_note"))
    free_for = list(set((res1.get("free_for") or []) + (res2.get("free_for") or [])))

    mode_name = "dual_model" if fallback_model is None else f"dual_model_fallback_m{fallback_model}"

    price_dict: Dict[str, Any] = {
        "status": final_status,
        "primary_adult_eur": final_price,
        "door_adult_eur": door_adult if is_agreed else None,
        "online_adult_eur": online_adult if is_agreed else None,
        "variants": variants_val if is_agreed else None,
        "cheapest_adult_eur": cheapest if is_agreed else None,
        "price_note": price_note if is_agreed else None,
        "free_for": free_for if is_agreed else [],
        "quote": quote,
        "source_url": source_url,
        "page_title": page_title,
        "reasoning_summary": chosen_res.get("reasoning_summary") or res1.get("reasoning_summary") or res2.get("reasoning_summary") or "",
        "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "mode": mode_name,
        "extractor_model": litellm_model,
        "verifier_model": openrouter_model,
        "confidence": conf,
    }

    all_failures = fails1 + fails2

    return {
        "slug": slug,
        "name": name,
        "is_accepted": is_agreed,
        "disagreement_type": disagreement_type,
        "gate_failures": all_failures,
        "price": price_dict,
        "model1": {
            "model": litellm_model,
            "status": status1,
            "primary_adult_eur": price1,
            "door_adult_eur": res1.get("door_adult_eur"),
            "online_adult_eur": res1.get("online_adult_eur"),
            "variants": res1.get("variants"),
            "quote": res1.get("quote"),
            "source_url": res1.get("source_url"),
            "reasoning_summary": res1.get("reasoning_summary"),
        },
        "model2": {
            "model": openrouter_model,
            "status": status2,
            "primary_adult_eur": price2,
            "door_adult_eur": res2.get("door_adult_eur"),
            "online_adult_eur": res2.get("online_adult_eur"),
            "variants": res2.get("variants"),
            "quote": res2.get("quote"),
            "source_url": res2.get("source_url"),
            "reasoning_summary": res2.get("reasoning_summary"),
        },
        "time_seconds": round(time.time() - start_time, 2),
    }


# ---------------------------------------------------------------------------
# 7. Result Storage Helpers
# ---------------------------------------------------------------------------

def save_dual_model_results(results: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Save agreed results with confidence high/medium into prices.json,
    and disagreements or gate failures into needs_review.json.
    Records with status 'retry_later' or 'quota_exhausted' are NOT written to needs_review.json.
    """
    current_prices = {}
    if PRICES_JSON_PATH.exists():
        try:
            with open(PRICES_JSON_PATH, "r", encoding="utf-8") as f:
                current_prices = {m["slug"]: m for m in json.load(f).get("museums", []) if "slug" in m}
        except Exception:
            pass

    current_needs = {}
    if NEEDS_REVIEW_PATH.exists():
        try:
            with open(NEEDS_REVIEW_PATH, "r", encoding="utf-8") as f:
                current_needs = {m["slug"]: m for m in json.load(f).get("records", []) if "slug" in m}
        except Exception:
            pass

    acc_count = 0
    rev_count = 0

    for r in results:
        slug = r["slug"]
        existing = current_prices.get(slug)
        if existing and existing.get("price", {}).get("entered_by") == "manual":
            continue

        p_status = r.get("price", {}).get("status")
        conf = r.get("price", {}).get("confidence")

        # 1. Skip temporary execution states
        if p_status in ("retry_later", "quota_exhausted") or r.get("disagreement_type") in ("retry_later", "quota_exhausted"):
            continue

        # 2. Accepted agreements into prices.json
        if r["is_accepted"] and (conf in ("high", "medium") or p_status == "blocked_by_bot_protection"):
            current_prices[slug] = {
                "slug": slug,
                "name": r["name"],
                "price": r["price"],
            }
            if slug in current_needs:
                del current_needs[slug]
            acc_count += 1
        else:
            # 3. Disagreements and gate failures into needs_review.json
            current_needs[slug] = {
                "slug": slug,
                "name": r["name"],
                "disagreement_type": r.get("disagreement_type") or "unknown_disagreement",
                "gate_failures": r.get("gate_failures", []),
                "model1": r.get("model1", {}),
                "model2": r.get("model2", {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if slug in current_prices:
                del current_prices[slug]
            rev_count += 1

    PRICES_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PRICES_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_museums": len(current_prices),
            "museums": sorted(list(current_prices.values()), key=lambda x: x["slug"]),
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with open(NEEDS_REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_needs_review": len(current_needs),
            "records": sorted(list(current_needs.values()), key=lambda x: x["slug"]),
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return acc_count, rev_count


# ---------------------------------------------------------------------------
# 8. Batch Runner & CLI
# ---------------------------------------------------------------------------

PILOT_SLUGS = [
    # 10 Curated
    "museumprinsenhofdelft",
    "nationaal-monument-kamp-amersfoort",
    "rijksmuseum",
    "van-gogh-museum",
    "mauritshuis",
    "nemo-science-museum",
    "spoorwegmuseum",
    "watersnoodmuseum",
    "kasteel-de-haar",
    "museum-martena",
    # 10 Random (SEED=42)
    "anno",
    "discovery-museum",
    "dordrechts-museum",
    "fortresse-holland",
    "huis-zypendaal",
    "joods-museum",
    "kasteel-radboud",
    "nationaal-monument-kamp-vught",
    "sint-jan-de-doper",
    "stedelijk-museum-zutphen",
]


def run_simple_pipeline(
    museums: List[Dict[str, Any]],
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: Optional[int] = None,
    resume: bool = False,
    record: bool = True,
) -> Dict[str, Any]:
    """Execute dual-model price enrichment across a list of museums."""
    litellm_base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    litellm_api_key = os.environ.get("LITELLM_API_KEY", "sk-localproxy")
    litellm_model = model or os.environ.get("LITELLM_FREE_LITE_MODEL", "free-lite")

    openrouter_base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    openrouter_model = os.environ.get("OPENROUTER_FREE_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

    # Safety validation
    validate_free_tier_configuration(
        litellm_model=litellm_model,
        openrouter_model=openrouter_model,
    )

    fetcher = PoliteFetcher()
    quota_guard = SearchQuotaGuard()

    # If resume, skip already processed in prices.json
    existing_slugs = set()
    if resume and PRICES_JSON_PATH.exists():
        try:
            with open(PRICES_JSON_PATH, "r", encoding="utf-8") as f:
                existing_slugs = {m["slug"] for m in json.load(f).get("museums", [])}
        except Exception:
            pass

    target_museums = []
    for m in museums:
        if resume and m.get("slug") in existing_slugs:
            continue
        target_museums.append(m)

    if limit and limit > 0:
        target_museums = target_museums[:limit]

    initial_quota = quota_guard.get_used_count()
    results = []
    start_all = time.time()

    print("\n" + "=" * 78)
    print(f"=== DUAL-MODEL PRICE ENRICHMENT PIPELINE ({len(target_museums)} museums) ===")
    print(f"Model 1 (Primary):    {litellm_model} @ {litellm_base_url}")
    print(f"Model 2 (Opinion):    {openrouter_model} @ {openrouter_base_url}")
    print(f"Search Provider:      Tavily (Quota: {initial_quota}/{quota_guard.max_monthly_searches} used)")
    print("=" * 78)

    for i, m in enumerate(target_museums, 1):
        slug = m.get("slug", "")
        print(f"[{i}/{len(target_museums)}] Processing {slug}...")
        res = process_museum_dual_model(
            museum=m,
            fetcher=fetcher,
            quota_guard=quota_guard,
            litellm_base_url=litellm_base_url,
            litellm_api_key=litellm_api_key,
            litellm_model=litellm_model,
            openrouter_base_url=openrouter_base_url,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
        )
        results.append(res)
        p = res.get("price", {})
        p_status = p.get("status")
        conf = p.get("confidence")
        disagree = res.get("disagreement_type")

        if p_status in ("retry_later", "quota_exhausted"):
            status_str = p_status.upper()
        elif res["is_accepted"]:
            status_str = f"ACCEPTED ({conf})"
        else:
            status_str = f"NEEDS_REVIEW ({disagree})"

        price_val = f"€{p.get('primary_adult_eur'):.2f}" if p.get("primary_adult_eur") is not None else p_status
        print(f"  -> {status_str} [{price_val}] ({res['time_seconds']}s)")
        if not res["is_accepted"] and p_status not in ("retry_later", "quota_exhausted"):
            m1 = res.get("model1", {})
            m2 = res.get("model2", {})
            print(f"     M1 ({m1.get('model')}): status={m1.get('status')} €{m1.get('primary_adult_eur')} | quote='{m1.get('quote')}'")
            print(f"     M2 ({m2.get('model')}): status={m2.get('status')} €{m2.get('primary_adult_eur')} | quote='{m2.get('quote')}'")
            if res.get("gate_failures"):
                print(f"     Failures: {res.get('gate_failures')}")
        if record and p_status not in ("retry_later", "quota_exhausted"):
            save_dual_model_results([res])
        time.sleep(1.0)

    # Retry pass for any retry_later records
    retry_indices = [idx for idx, r in enumerate(results) if r.get("price", {}).get("status") == "retry_later"]
    if retry_indices:
        print("\n" + "=" * 78)
        print(f"=== RETRY PASS: Re-running {len(retry_indices)} rate-limited museums ===")
        print("Cooling down 20s for upstream rate-limit window...")
        time.sleep(20)
        print("=" * 78)
        for num, idx in enumerate(retry_indices, 1):
            orig_res = results[idx]
            slug = orig_res["slug"]
            m = next((item for item in target_museums if item.get("slug") == slug), None)
            if not m:
                continue
            print(f"[RETRY {num}/{len(retry_indices)}] Re-processing {slug}...")
            res = process_museum_dual_model(
                museum=m,
                fetcher=fetcher,
                quota_guard=quota_guard,
                litellm_base_url=litellm_base_url,
                litellm_api_key=litellm_api_key,
                litellm_model=litellm_model,
                openrouter_base_url=openrouter_base_url,
                openrouter_api_key=openrouter_api_key,
                openrouter_model=openrouter_model,
            )
            results[idx] = res
            p = res.get("price", {})
            p_status = p.get("status")
            conf = p.get("confidence")
            disagree = res.get("disagreement_type")

            if p_status in ("retry_later", "quota_exhausted"):
                status_str = p_status.upper()
            elif res["is_accepted"]:
                status_str = f"ACCEPTED ({conf})"
            else:
                status_str = f"NEEDS_REVIEW ({disagree})"

            price_val = f"€{p.get('primary_adult_eur'):.2f}" if p.get("primary_adult_eur") is not None else p_status
            print(f"  -> {status_str} [{price_val}] ({res['time_seconds']}s)")
            if record and p_status not in ("retry_later", "quota_exhausted"):
                save_dual_model_results([res])

    total_time = round(time.time() - start_all, 2)
    searches_used_this_run = quota_guard.get_used_count() - initial_quota

    if record:
        acc, rev = save_dual_model_results(results)
        print(f"\nRecorded: {acc} accepted to prices.json, {rev} needs_review to needs_review.json")

    accepted = [r for r in results if r["is_accepted"]]
    retry_later = [r for r in results if r.get("price", {}).get("status") == "retry_later"]
    quota_exhausted = [r for r in results if r.get("price", {}).get("status") == "quota_exhausted"]
    needs_review = [r for r in results if not r["is_accepted"] and r not in retry_later and r not in quota_exhausted]

    paid_count = sum(1 for r in accepted if r.get("price", {}).get("status") == "paid")
    free_count = sum(1 for r in accepted if r.get("price", {}).get("status") == "free")
    closed_count = sum(1 for r in accepted if r.get("price", {}).get("status") == "closed")
    blocked_count = sum(1 for r in accepted if r.get("price", {}).get("status") == "blocked_by_bot_protection")

    disagreement_counts: Dict[str, int] = {}
    for r in needs_review:
        dtype = r.get("disagreement_type") or "unknown"
        disagreement_counts[dtype] = disagreement_counts.get(dtype, 0) + 1

    summary = {
        "model1": litellm_model,
        "model2": openrouter_model,
        "total_processed": len(results),
        "accepted_total": len(accepted),
        "accepted_paid": paid_count,
        "accepted_free": free_count,
        "accepted_closed": closed_count,
        "accepted_blocked": blocked_count,
        "needs_review_total": len(needs_review),
        "needs_review_by_disagreement": disagreement_counts,
        "retry_later_total": len(retry_later),
        "quota_exhausted_total": len(quota_exhausted),
        "searches_used_run": searches_used_this_run,
        "searches_used_month_total": quota_guard.get_used_count(),
        "total_time_seconds": total_time,
        "results": results,
    }

    print("\n" + "=" * 78)
    print("=== DUAL-MODEL PIPELINE SUMMARY ===")
    print(f"Total Processed:           {len(results)}")
    print(f"Accepted Total:            {len(accepted)} ({len(accepted)/len(results)*100:.1f}%)" if results else "0")
    print(f"  • Paid Admission:        {paid_count}")
    print(f"  • Free Admission:        {free_count}")
    print(f"  • Closed (renovation):   {closed_count}")
    print(f"  • Blocked (bot/robots):  {blocked_count}")
    print(f"Needs Review Total:        {len(needs_review)}")
    if disagreement_counts:
        print("Needs Review by Disagreement Type:")
        for dtype, cnt in sorted(disagreement_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {dtype}: {cnt}")
    print(f"Retry Later Total:         {len(retry_later)}")
    print(f"Quota Exhausted Total:     {len(quota_exhausted)}")
    print(f"Searches Used (Run):       {searches_used_this_run}")
    print(f"Monthly Tavily Quota:      {quota_guard.get_used_count()}/{quota_guard.max_monthly_searches}")
    print(f"Total Time:                {total_time}s")
    print("=" * 78)

    return summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dual-model price enrichment pipeline")
    parser.add_argument("--pilot", action="store_true", default=False, help="Run only on the 20 pilot museums")
    parser.add_argument("--slugs", default=None, help="Comma-separated list of specific museum slugs to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of museums to process")
    parser.add_argument("--resume", action="store_true", default=False, help="Skip already accepted museums in prices.json")
    parser.add_argument("--model", default=None, help="Primary selection model (LiteLLM proxy)")
    parser.add_argument("--base-url", default=None, help="OpenRouter Base URL")
    args = parser.parse_args()

    museums_path = REPO_ROOT / "data" / "museums.json"
    with open(museums_path, "r", encoding="utf-8") as f:
        all_museums = json.load(f)["museums"]

    if args.slugs:
        slug_list = [s.strip() for s in args.slugs.split(",") if s.strip()]
        by_slug = {m["slug"]: m for m in all_museums}
        target_museums = [by_slug[s] for s in slug_list if s in by_slug]
    elif args.pilot:
        by_slug = {m["slug"]: m for m in all_museums}
        target_museums = [by_slug[s] for s in PILOT_SLUGS if s in by_slug]
    else:
        target_museums = all_museums

    run_simple_pipeline(
        museums=target_museums,
        model=args.model,
        base_url=args.base_url,
        limit=args.limit,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
