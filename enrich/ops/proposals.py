"""Proposal storage manager for identity and metadata fixes.

CRITICAL GUARANTEE:
Identity discovery and address checks NEVER modify data/overrides.yaml directly.
All discovered corrections and website additions are stored strictly in
data/enrichment/proposals.json for user inspection and bulk approval.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("enrich.proposals")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "enrichment"
PROPOSALS_PATH = DATA_DIR / "proposals.json"


def load_proposals() -> List[Dict[str, Any]]:
    """Load pending proposals from proposals.json."""
    if PROPOSALS_PATH.exists():
        try:
            with open(PROPOSALS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "proposals" in data:
                    return data["proposals"]
        except Exception as e:
            logger.warning(f"Error loading proposals from {PROPOSALS_PATH}: {e}")
    return []


def save_proposals(proposals: List[Dict[str, Any]]) -> None:
    """Save proposals strictly to data/enrichment/proposals.json."""
    PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
        json.dump(proposals, f, indent=2, ensure_ascii=False)
        f.write("\n")


def record_proposals(new_proposals: List[Dict[str, Any]]) -> int:
    """Record or update proposals keyed by (slug, field).

    Returns total number of active proposals stored.
    """
    existing = load_proposals()
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {
        (p["slug"], p["field"]): p for p in existing if "slug" in p and "field" in p
    }

    for p in new_proposals:
        slug = p.get("slug")
        field = p.get("field")
        if slug and field:
            by_key[(slug, field)] = p

    sorted_proposals = sorted(list(by_key.values()), key=lambda x: (x.get("field", ""), x.get("slug", "")))
    save_proposals(sorted_proposals)
    return len(sorted_proposals)


def clear_proposals(slug: Optional[str] = None, field: Optional[str] = None) -> int:
    """Remove approved or rejected proposals."""
    existing = load_proposals()
    remaining = []
    removed = 0
    for p in existing:
        match_slug = (slug is None or p.get("slug") == slug)
        match_field = (field is None or p.get("field") == field)
        if match_slug and match_field:
            removed += 1
        else:
            remaining.append(p)
    if removed > 0:
        save_proposals(remaining)
    return removed
