"""Audit CLI tool: samples accepted prices for manual spot-checking."""

import json
import logging
from pathlib import Path
import random
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRICES_PATH = REPO_ROOT / "data" / "enrichment" / "prices.json"


def run_spot_check_audit(sample_size: Optional[int] = None, paid_only: bool = False) -> List[Dict[str, Any]]:
    """Sample N random accepted rows for manual spot checking."""
    if not PRICES_PATH.exists():
        print(f"No prices data found at {PRICES_PATH}. Run enrichment first.")
        return []

    with open(PRICES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    museums = data.get("museums", [])
    if paid_only:
        museums = [
            m for m in museums
            if m.get("price", {}).get("status") == "paid"
            or (m.get("price", {}).get("primary_adult_eur") is not None and m.get("price", {}).get("primary_adult_eur", 0) > 0)
            or (m.get("price", {}).get("adult_eur") is not None and m.get("price", {}).get("adult_eur", 0) > 0)
        ]

    if not museums:
        print("No matching museum records in prices.json.")
        return []

    sample_n = sample_size if sample_size and sample_size < len(museums) else len(museums)
    sampled = random.sample(museums, sample_n)

    # Sort paid rows by primary_adult_eur (or sort free as 0)
    sampled.sort(key=lambda x: (
        0.0 if x.get("price", {}).get("status") == "free"
        else (x.get("price", {}).get("primary_adult_eur") or x.get("price", {}).get("adult_eur") or 9999.0)
    ))

    print("\n" + "=" * 95)
    row_type = "accepted paid records" if paid_only else "accepted records"
    print(f"=== MANUAL SPOT-CHECK AUDIT (Showing {len(sampled)} of {len(museums)} {row_type}) ===")
    print("=" * 95)
    print(f"{'#':<3} | {'Slug':<28} | {'Status':<7} | {'Price':<8} | {'Conf':<6} | {'Quote (<=15 words)'}")
    print("-" * 95)

    for i, m in enumerate(sampled, 1):
        slug = m.get("slug", "")
        price_obj = m.get("price") or {}
        status = price_obj.get("status", "unknown")
        adult_eur = price_obj.get("primary_adult_eur")
        if adult_eur is None:
            adult_eur = price_obj.get("adult_eur")
        price_str = f"€{adult_eur:.2f}" if adult_eur is not None else "null"
        conf = (price_obj.get("confidence") or "low")[:6]
        quote = price_obj.get("quote") or "(no quote)"
        url = price_obj.get("source_url") or "n/a"

        title = price_obj.get("page_title") or "(no title)"
        reasoning_summary = price_obj.get("reasoning_summary") or "(no reasoning summary)"
        print(f"{i:<3} | {slug:<28} | {status:<7} | {price_str:<8} | {conf:<6} | {quote}")
        print(f"    Title:     {title}")
        print(f"    URL:       {url}")
        
        extra_parts = []
        if price_obj.get("online_adult_eur") is not None:
            extra_parts.append(f"Online: €{price_obj['online_adult_eur']:.2f}")
        if price_obj.get("door_adult_eur") is not None:
            extra_parts.append(f"Door: €{price_obj['door_adult_eur']:.2f}")
        if price_obj.get("variants"):
            extra_parts.append(f"Variants: {price_obj['variants']}")
        if price_obj.get("cheapest_adult_eur") is not None:
            extra_parts.append(f"Cheapest (no tour): €{price_obj['cheapest_adult_eur']:.2f}")
        if price_obj.get("price_note"):
            extra_parts.append(f"Note: {price_obj['price_note']}")
        if extra_parts:
            print(f"    Pricing:   {' | '.join(extra_parts)}")
            
        print(f"    Reasoning: {reasoning_summary}\n")

    print("=" * 95)
    return sampled
