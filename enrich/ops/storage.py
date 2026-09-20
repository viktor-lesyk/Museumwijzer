"""Storage manager for accepted prices and needs_review records."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("enrich.storage")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "enrichment"
PRICES_PATH = DATA_DIR / "prices.json"
NEEDS_REVIEW_PATH = DATA_DIR / "needs_review.json"


def load_json(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading {path}: {e}")
    return {}


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def record_results(results: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Split results into accepted vs needs_review.
    Preserves existing manual entries (entered_by == 'manual').
    Returns (accepted_count, needs_review_count).
    """
    current_prices = load_json(PRICES_PATH)
    current_needs = load_json(NEEDS_REVIEW_PATH)

    prices_by_slug = {m["slug"]: m for m in current_prices.get("museums", []) if "slug" in m}
    needs_by_slug = {m["slug"]: m for m in current_needs.get("records", []) if "slug" in m}

    new_accepted_count = 0
    new_review_count = 0

    for r in results:
        slug = r["slug"]
        existing = prices_by_slug.get(slug)
        # Never overwrite a manually entered price automatically unless entered_by is manual
        if existing and existing.get("price", {}).get("entered_by") == "manual" and r["price"].get("entered_by") != "manual":
            logger.info(f"Preserving manual price entry for {slug}.")
            continue

        if r["is_accepted"]:
            prices_by_slug[slug] = {
                "slug": slug,
                "name": r["name"],
                "price": r["price"],
            }
            # If it was in needs_review, clear it
            if slug in needs_by_slug:
                del needs_by_slug[slug]
            new_accepted_count += 1
        else:
            needs_by_slug[slug] = {
                "slug": slug,
                "name": r["name"],
                "price": r["price"],
                "gate_failures": r.get("gate_failures", []),
                "verifier_verdict": r.get("verifier_verdict"),
                "verifier_justification": r.get("verifier_justification"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            new_review_count += 1

    # Save prices.json
    prices_payload = {
        "version": "1.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_museums": len(prices_by_slug),
        "museums": sorted(list(prices_by_slug.values()), key=lambda x: x["slug"]),
    }
    save_json(PRICES_PATH, prices_payload)

    # Save needs_review.json
    review_payload = {
        "version": "1.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_needs_review": len(needs_by_slug),
        "records": sorted(list(needs_by_slug.values()), key=lambda x: x["slug"]),
    }
    save_json(NEEDS_REVIEW_PATH, review_payload)

    return new_accepted_count, new_review_count
