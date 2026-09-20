import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import yaml

from .config import OVERRIDES_PATH

logger = logging.getLogger(__name__)


def load_overrides(overrides_path: Path = OVERRIDES_PATH) -> Dict[str, Dict[str, Any]]:
    """Load manual overrides from YAML."""
    if not overrides_path.exists():
        return {}
    try:
        with open(overrides_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Failed to load overrides from {overrides_path}: {e}")
        return {}


def apply_overrides(
    museum_dict: Dict[str, Any],
    overrides: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], bool]:
    """
    Apply manual overrides to a museum dictionary by slug.
    Checks if the source data already matches the override (source fixed), logging a warning.
    Returns (updated_record, source_matches_override).
    """
    slug = museum_dict.get("slug")
    if not slug or slug not in overrides:
        return museum_dict, False

    entry = overrides[slug]
    override_fields = entry.get("override", entry)

    # Check if source already matches the override (i.e. source fixed)
    matches_source = True
    for key, val in override_fields.items():
        if key == "address" and isinstance(val, dict):
            curr_addr = museum_dict.get("address", {})
            for a_key, a_val in val.items():
                if curr_addr.get(a_key) != a_val:
                    matches_source = False
                    break
        else:
            if museum_dict.get(key) != val:
                matches_source = False
                break

    if matches_source:
        logger.warning(
            f"Override for '{slug}' matches current source data! "
            f"The upstream site may have fixed this error; consider removing this entry from overrides.yaml."
        )

    updated = dict(museum_dict)
    for key, value in override_fields.items():
        if key == "address" and isinstance(value, dict) and isinstance(updated.get("address"), dict):
            updated_address = dict(updated["address"])
            updated_address.update(value)
            updated["address"] = updated_address
            if "city" in value:
                updated["city"] = value["city"]
        else:
            updated[key] = value

    return updated, matches_source
