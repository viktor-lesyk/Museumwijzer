"""Deterministic verification gates for museum adult ticket prices.

CODE-ONLY, DETERMINISTIC VALIDATION (NOT LLM):
1. Domain match / link provenance tracking from museum_website
2. Literal match of numeric price and quote (<=15 words) in fetched text
3. Museum identity (name/city) presence on page
4. Plausible price range (paid: 1.00 - 45.00 EUR; free: 0.00 EUR)
5. Combo / duo / joint ticket rejection
6. Year-over-Year price change check (>30% change flagged)
"""

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from enrich.fetch import PoliteFetcher

logger = logging.getLogger("enrich.gates")

DEFAULT_FORBIDDEN_KEYWORDS = ["combo", "combi", "duo", "gezamenlijk", "combiticket", "duoticket"]


def normalize_for_match(text: str) -> str:
    """Normalize text for whitespace, non-breaking spaces, and case."""
    text = text.replace("&nbsp;", " ").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def check_domain_and_provenance(
    source_url: str,
    museum_website: Optional[str],
    fetcher: Optional[PoliteFetcher] = None,
) -> Tuple[bool, Optional[str]]:
    """Gate 1: source_url domain matches museum's website, or was reached via links."""
    if not source_url:
        return False, "Empty source_url"
    if not museum_website:
        return True, None  # No baseline website to check against

    source_p = urlparse(source_url)
    museum_p = urlparse(museum_website)

    source_netloc = source_p.netloc.lower().split(":")[0]
    museum_netloc = museum_p.netloc.lower().split(":")[0]

    # Remove leading 'www.'
    def base_domain(host: str) -> str:
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    if base_domain(source_netloc) == base_domain(museum_netloc):
        return True, None

    # Check if target was reached by following links from museum_website
    if fetcher and fetcher.is_reached_from(source_url, museum_website):
        return True, None

    return False, f"source_url host '{source_netloc}' does not match museum_website '{museum_netloc}' and was not reached via links"


def check_literal_match(
    page_text: str,
    adult_eur: Optional[float],
    quote: Optional[str],
    status: str,
) -> Tuple[bool, Optional[str]]:
    """Gate 2: literal number and quote appear verbatim in the page text."""
    norm_page = normalize_for_match(page_text)

    # 1. Quote verification
    if quote:
        words = quote.split()
        if len(words) > 15:
            return False, f"Quote exceeds 15 words limit ({len(words)} words): '{quote}'"

        norm_quote = normalize_for_match(quote)
        if norm_quote not in norm_page:
            # Check for close punctuation or minor spacing variance
            clean_q = re.sub(r"[^\w\s]", "", norm_quote)
            clean_page = re.sub(r"[^\w\s]", "", norm_page)
            if clean_q not in clean_page:
                return False, f"Quote '{quote}' was not found verbatim in fetched page text"

    # 2. Free admission check
    if status == "free":
        free_keywords = ["gratis", "gratis toegang", "toegang is gratis", "vrije toegang", "kostenloos", "kostenlose"]
        if not quote or not any(k in quote.lower() for k in free_keywords):
            return False, "Free admission requires an explicit quote stating admission is free for everyone"
        # Check against false positives where only children are free
        q_lower = quote.lower()
        if any(c in q_lower for c in ["tot 18", "t/m 18", "kinderen gratis", "jeugd gratis", "tot en met 18"]):
            if not any(a in q_lower for a in ["volwassenen gratis", "iedereen gratis", "alle bezoekers gratis", "gratis toegang voor iedereen"]):
                return False, "Quote states free admission for youth/children, which is not free general adult admission"

    # 3. Numeric price verification for paid tickets
    if status == "paid" and adult_eur is not None:
        int_val = int(adult_eur)
        cents = int(round((adult_eur - int_val) * 100))
        patterns = [
            f"{adult_eur:.2f}".replace(".", ","),
            f"{adult_eur:.2f}",
            f"{adult_eur:g}".replace(".", ","),
            f"{adult_eur:g}",
        ]
        if cents == 0:
            patterns.extend([str(int_val), f"{int_val},-", f"{int_val}.00", f"{int_val},00"])

        # Number must appear in the page text
        num_found = False
        for pat in patterns:
            # Look for number with word boundary or euro symbol
            esc = re.escape(pat)
            if re.search(r"(?:€|eur|euro)?\s*" + esc + r"(?:\s*|-|€)?", norm_page):
                num_found = True
                break

        if not num_found:
            return False, f"Claimed price €{adult_eur} not found in page text"

    return True, None


def check_identity_presence(
    page_text: str,
    museum_name: str,
    city: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """Gate 3: museum name or city appears on the page."""
    from enrich.audit_identity import get_distinctive_tokens
    tokens = get_distinctive_tokens(museum_name, city)
    if not tokens:
        return True, None

    norm_page = normalize_for_match(page_text)
    hits = [t for t in tokens if t in norm_page]
    if not hits:
        return False, f"Neither museum name tokens {sorted(tokens)} nor city appear on the fetched page"
    return True, None


def check_plausible_range(
    adult_eur: Optional[float],
    status: str,
    min_paid: float = 1.0,
    max_paid: float = 45.0,
) -> Tuple[bool, Optional[str]]:
    """Gate 4: plausible price range check."""
    if status == "paid":
        if adult_eur is None:
            return False, "Paid status requires a numeric primary_adult_eur value"
        if not (min_paid <= adult_eur <= max_paid):
            return False, f"Price €{adult_eur} is outside plausible adult range [€{min_paid:.2f} - €{max_paid:.2f}]"
    elif status == "free":
        if adult_eur is not None:
            return False, f"Status 'free' requires primary_adult_eur to be null, got {adult_eur}"
    else:
        # non-priced states (closed, combo_only, blocked_by_bot_protection, not_found, unknown)
        if adult_eur is not None:
            return False, f"Status '{status}' should have primary_adult_eur=null, got {adult_eur}"

    return True, None


CONTROLLED_FREE_FOR_VOCABULARY = {
    "children_under_4",
    "children_under_12",
    "children_under_18",
    "youth",
    "students",
    "seniors",
    "museumkaart",
    "vriendenloterij_vip_kaart",
    "icom",
    "rembrandtkaart",
    "everyone",
    "other",
}


def check_free_for_vocabulary(free_for: Optional[List[str]]) -> Tuple[bool, Optional[str]]:
    """Validate free_for entries against controlled vocabulary."""
    if not free_for:
        return True, None
    invalid = [f for f in free_for if f not in CONTROLLED_FREE_FOR_VOCABULARY]
    if invalid:
        return False, f"free_for items {invalid} are not in controlled vocabulary: {sorted(CONTROLLED_FREE_FOR_VOCABULARY)}"
    return True, None


def check_offerings_gates(offerings: Optional[List[Dict[str, Any]]], status: str) -> Tuple[bool, Optional[str]]:
    """Gate: validate ticket offerings schema and bounds."""
    if not offerings:
        return True, None
    valid_audiences = {"adult", "youth", "child", "student", "senior", "family", "group", "other"}
    for idx, off in enumerate(offerings):
        if not isinstance(off, dict):
            return False, f"Offering #{idx} must be an object, got {type(off).__name__}"
        aud = off.get("audience")
        if aud not in valid_audiences:
            return False, f"Offering #{idx} invalid audience '{aud}', must be one of {sorted(valid_audiences)}"
        label = off.get("label") or ""
        if len(label.split()) > 8:
            return False, f"Offering #{idx} label '{label}' exceeds 8 words limit ({len(label.split())} words)"
        amt = off.get("amount_eur")
        if amt is not None:
            if not isinstance(amt, (int, float)):
                return False, f"Offering #{idx} amount_eur must be numeric or null, got {amt}"
            if amt < 0.0 or amt > 45.0:
                return False, f"Offering #{idx} amount_eur €{amt} outside plausible range [0.0 - 45.0]"
    return True, None


def is_only_quote_length_failure(failures: List[str]) -> bool:
    """Helper: returns True if the ONLY gate failure is quote length > 15 words."""
    return len(failures) == 1 and "exceeds 15 words limit" in failures[0]


def check_combo_rejection(
    quote: Optional[str],
    page_text: str,
    forbidden_keywords: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """Gate 5: combo / duo / combi ticket rejection."""
    keywords = forbidden_keywords or DEFAULT_FORBIDDEN_KEYWORDS
    if quote:
        q_lower = quote.lower()
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", q_lower):
                return False, f"Quote contains forbidden combo/duo keyword '{kw}': '{quote}'"

    return True, None


def check_yoy_change(
    slug: str,
    new_adult_eur: Optional[float],
    previous_prices_path: Optional[Path] = None,
    max_pct_change: float = 30.0,
) -> Tuple[bool, Optional[str]]:
    """Gate 6: flag for review if price changed by >30% compared to previous run."""
    if new_adult_eur is None or not previous_prices_path or not previous_prices_path.exists():
        return True, None

    try:
        with open(previous_prices_path, "r", encoding="utf-8") as f:
            prev_data = json.load(f)
        prev_by_slug = {m["slug"]: m for m in prev_data.get("museums", []) if "slug" in m}
        prev_rec = prev_by_slug.get(slug)
        if not prev_rec:
            return True, None

        prev_price = prev_rec.get("price", {})
        prev_val = prev_price.get("adult_eur")
        if prev_val is not None and prev_val > 0:
            pct_change = abs(new_adult_eur - prev_val) / prev_val * 100.0
            if pct_change > max_pct_change:
                return False, f"Price changed by {pct_change:.1f}% (€{prev_val:.2f} -> €{new_adult_eur:.2f}), exceeding {max_pct_change}% threshold"
    except Exception as e:
        logger.warning(f"Error checking YoY change for {slug}: {e}")

    return True, None


def calibrate_confidence(
    status: str,
    quote: Optional[str],
    offerings: Optional[List[Dict[str, Any]]] = None,
    raw_confidence: Optional[str] = None,
) -> str:
    """
    Calibrate confidence level:
    - 'high': ONLY for a clearly labelled adult price on a static page (e.g. 'Volwassenen', 'Adults').
    - 'medium': age-tier prices (e.g. 'vanaf 13 jaar') and multi-tier pages/offerings.
    - 'blocked_by_bot_protection' / 'blocked_by_robots': for protected/blocked hosts.
    - 'low': inferred, unknown, or uncertain.
    """
    if status in ("blocked_by_bot_protection", "blocked_by_robots"):
        return status

    if status in ("unknown", "not_found", "closed"):
        return "low" if status == "unknown" else ("high" if quote else "medium")

    if not quote:
        return "low"

    q_lower = quote.lower()

    # Age-tier check: if it says 'vanaf X jaar', '13+', '18+' or other age brackets rather than adult
    is_age_tier = any(ind in q_lower for ind in ["vanaf", "13 jaar", "12 jaar", "14 jaar", "15 jaar", "16 jaar", "17 jaar", "18 jaar", "13+", "18+", "tot 18", "t/m 18", "leeftijd"])

    # Multi-tier offerings check
    is_multi_tier = offerings is not None and len(offerings) > 1

    if is_age_tier or is_multi_tier:
        return "medium"

    # Clearly labelled adult keywords
    is_clearly_adult = any(w in q_lower for w in ["volwassenen", "volwassene", "adults", "adult", "normaal tarief", "regulier tarief", "regulier entreetarief", "toegang is gratis", "gratis"])

    if is_clearly_adult and status in ("paid", "free"):
        return "high"

    return "medium" if raw_confidence == "high" else (raw_confidence or "medium")


def run_all_price_gates(
    slug: str,
    museum_name: str,
    city: Optional[str],
    museum_website: Optional[str],
    source_url: Optional[str],
    page_text: str,
    extracted_data: Dict[str, Any],
    fetcher: Optional[PoliteFetcher] = None,
    previous_prices_path: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """
    Run all deterministic gates in sequence.
    Returns (passed_all, list_of_failure_reasons).
    """
    failures: List[str] = []

    status = extracted_data.get("status", "unknown")
    adult_eur = extracted_data.get("primary_adult_eur")
    if adult_eur is None:
        adult_eur = extracted_data.get("adult_eur")
    quote = extracted_data.get("quote")
    free_for = extracted_data.get("free_for")
    offerings = extracted_data.get("offerings")

    # If blocked by bot protection or robots, non-content gates apply
    if status in ("blocked_by_bot_protection", "blocked_by_robots"):
        return True, []

    # 1. Domain & Provenance
    if source_url:
        ok, reason = check_domain_and_provenance(source_url, museum_website, fetcher)
        if not ok and reason:
            failures.append(f"Domain gate: {reason}")

    # 2. Literal Match
    if page_text:
        ok, reason = check_literal_match(page_text, adult_eur, quote, status)
        if not ok and reason:
            failures.append(f"Literal match gate: {reason}")

    # 3. Identity Presence
    if page_text:
        ok, reason = check_identity_presence(page_text, museum_name, city)
        if not ok and reason:
            failures.append(f"Identity gate: {reason}")

    # 4. Plausible Range
    ok, reason = check_plausible_range(adult_eur, status)
    if not ok and reason:
        failures.append(f"Range gate: {reason}")

    # 5. Combo Rejection
    ok, reason = check_combo_rejection(quote, page_text)
    if not ok and reason:
        failures.append(f"Combo rejection gate: {reason}")

    # 6. YoY Price Change
    ok, reason = check_yoy_change(slug, adult_eur, previous_prices_path)
    if not ok and reason:
        failures.append(f"YoY change gate: {reason}")

    # 7. Free_for vocabulary
    if free_for:
        ok, reason = check_free_for_vocabulary(free_for)
        if not ok and reason:
            failures.append(f"Free_for gate: {reason}")

    # 8. Offerings bounds and labels
    if offerings:
        ok, reason = check_offerings_gates(offerings, status)
        if not ok and reason:
            failures.append(f"Offerings gate: {reason}")

    return len(failures) == 0, failures

