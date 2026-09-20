from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .config import CHANGELOG_JSON_PATH

logger = logging.getLogger(__name__)


def compute_diff(
    new_museums: List[Dict[str, Any]],
    old_dataset: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute added, removed, and retained museums between runs."""
    new_by_slug = {m["slug"]: m for m in new_museums if "slug" in m}
    new_slugs: Set[str] = set(new_by_slug.keys())

    old_slugs: Set[str] = set()
    old_first_seen: Dict[str, str] = {}
    if old_dataset and "museums" in old_dataset:
        for m in old_dataset["museums"]:
            s = m.get("slug")
            if s:
                old_slugs.add(s)
                if "first_seen" in m:
                    old_first_seen[s] = m["first_seen"]

    added = sorted(list(new_slugs - old_slugs))
    removed = sorted(list(old_slugs - new_slugs))
    retained = sorted(list(new_slugs & old_slugs))

    return {
        "added": added,
        "removed": removed,
        "retained": retained,
        "old_first_seen": old_first_seen,
    }


def update_changelog(
    diff_result: Dict[str, Any],
    total_count: int,
    changelog_path: Path = CHANGELOG_JSON_PATH,
) -> Dict[str, Any]:
    """Record changes in changelog.json."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    added = diff_result.get("added", [])
    removed = diff_result.get("removed", [])

    changelog_data: Dict[str, Any] = {"updated_at": now_iso, "history": []}
    if changelog_path.exists():
        try:
            with open(changelog_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    changelog_data = existing
        except Exception as e:
            logger.warning(f"Could not read existing changelog: {e}")

    # Only add an entry if there are changes or if this is the initial run
    history = changelog_data.get("history", [])
    entry = {
        "date": today,
        "timestamp": now_iso,
        "added": added,
        "removed": removed,
        "total_count": total_count,
    }
    history.insert(0, entry)
    changelog_data["history"] = history
    changelog_data["updated_at"] = now_iso

    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(changelog_path, "w", encoding="utf-8") as f:
            json.dump(changelog_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write changelog: {e}")

    return entry
