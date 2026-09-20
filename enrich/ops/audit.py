"""Audit CLI tool: samples accepted prices for manual spot-checking."""

import json
import logging
from pathlib import Path
import random
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRICES_PATH = REPO_ROOT / "data" / "enrichment" / "prices.json"


def run_spot_check_audit(sample_size: Optional[int] = None) -> List[Dict[str, Any]]:
    """Sample N random accepted rows for manual spot checking."""
    if not PRICES_PATH.exists():
        print(f"No prices data found at {PRICES_PATH}. Run enrichment first.")
        return []

    with open(PRICES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    museums = data.get("museums", [])
    if not museums:
        print("No museum records in prices.json.")
        return []

    sample_n = sample_size if sample_size and sample_size < len(museums) else len(museums)
    sampled = random.sample(museums, sample_n)

    print("\n" + "=" * 95)
    print(f"=== MANUAL SPOT-CHECK AUDIT (Showing {len(sampled)} of {len(museums)} accepted records) ===")
    print("=" * 95)
    print(f"{'#':<3} | {'Slug':<28} | {'Adm':<5} | {'Price':<8} | {'Conf':<6} | {'Quote (<=15 words)'}")
    print("-" * 95)

    for i, m in enumerate(sampled, 1):
        slug = m.get("slug", "")
        price_obj = m.get("price") or {}
        admission = price_obj.get("admission", "unk")
        adult_eur = price_obj.get("adult_eur")
        price_str = f"€{adult_eur:.2f}" if adult_eur is not None else "null"
        conf = price_obj.get("confidence", "low")[:6]
        quote = price_obj.get("quote") or "(no quote)"
        url = price_obj.get("source_url") or "n/a"

        print(f"{i:<3} | {slug:<28} | {admission:<5} | {price_str:<8} | {conf:<6} | {quote}")
        print(f"    URL: {url}\n")

    print("=" * 95)
    return sampled
