import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field

from .config import (
    EXPECTED_BASELINE_COUNT,
    MAX_COUNT_CHANGE_PERCENT,
    MAX_TURNOVER_PERCENT,
    MIN_COMPLETE_GEO_PERCENT,
    MIN_MUSEUM_COUNT,
    NL_LAT_MAX,
    NL_LAT_MIN,
    NL_LON_MAX,
    NL_LON_MIN,
    SOURCE_HOST,
)

logger = logging.getLogger(__name__)

WHITELISTED_SHARED_WEBSITES = {
    frozenset(["huygens-museum-hofwijck", "huygens-museum-notarishuis"]),
    frozenset(["museumstoomtram", "museumstoomtram-hoorn-medemblik"]),
}

WHITELISTED_SHARED_ADDRESSES = {
    frozenset(["domunder", "paleis-lofen"]),
    frozenset(["forum-groningen", "storyworld"]),
    frozenset(["fotomuseum-den-haag", "km21"]),
    frozenset(["kunstlinie", "kunstlinie-kunsthal"]),
    frozenset(["museum-henriette-polak", "stedelijk-museum-zutphen"]),
    frozenset(["museumstoomtram", "museumstoomtram-hoorn-medemblik"]),
}


def check_shared_resources(museums: List[Dict[str, Any]]) -> List[str]:
    """
    Audit museum dataset for shared websites or physical addresses across different slugs.
    Logs and returns warnings for any unexpected duplicate resources outside documented whitelists.
    """
    warnings: List[str] = []
    by_site: Dict[str, List[str]] = {}
    by_addr: Dict[Tuple[str, str, str], List[str]] = {}

    for m in museums:
        if m.get("status", "active") == "removed":
            continue
        slug = m.get("slug", "")
        site = m.get("museum_website")
        if site:
            p = urlparse(site)
            norm_site = (p.netloc + p.path).rstrip("/").lower()
            if norm_site:
                by_site.setdefault(norm_site, []).append(slug)

        addr = m.get("address", {})
        street = (addr.get("street") or "").strip().lower()
        postcode = (addr.get("postcode") or "").replace(" ", "").upper()
        city = (addr.get("city") or "").strip().lower()
        if street and postcode:
            by_addr.setdefault((street, postcode, city), []).append(slug)

    for site, slugs in by_site.items():
        if len(slugs) > 1:
            slug_set = frozenset(slugs)
            if slug_set not in WHITELISTED_SHARED_WEBSITES:
                msg = f"Unexpected shared museum_website '{site}' across slugs: {sorted(slugs)}"
                logger.warning(msg)
                warnings.append(msg)

    for (street, postcode, city), slugs in by_addr.items():
        if len(slugs) > 1:
            slug_set = frozenset(slugs)
            if slug_set not in WHITELISTED_SHARED_ADDRESSES:
                msg = f"Unexpected shared address '{street}, {postcode} {city}' across slugs: {sorted(slugs)}"
                logger.warning(msg)
                warnings.append(msg)

    return warnings


class AddressModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    street: str = ""
    postcode: str = ""
    city: str = ""


class MuseumModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1)
    name: str = Field(min_length=1)
    province: str = Field(min_length=1)
    city: Optional[str] = None
    pdok_woonplaats: Optional[str] = None
    municipality: Optional[str] = None
    address: AddressModel
    lat: Optional[float] = None
    lon: Optional[float] = None
    official_url: str
    official_urls: Dict[str, str]
    museum_website: Optional[str] = None
    source_date_raw: Optional[str] = None
    first_seen: str
    programmes: List[str] = Field(default_factory=lambda: ["welkom-in-het-museum"])
    status: str = "active"
    consecutive_missing: int = 0


class MuseumsDataFileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Dict[str, str]
    museums: List[MuseumModel]


def validate_single_museum(m: Dict[str, Any]) -> List[str]:
    """Validate a single museum record against sanity rules."""
    errors = []
    slug = m.get("slug", "")
    if not slug:
        errors.append("Empty slug")

    name = m.get("name", "")
    if not name:
        errors.append(f"Empty name for slug '{slug}'")

    # Validate official URL host
    official_url = m.get("official_url", "")
    if not official_url:
        errors.append(f"Missing official_url for '{slug}'")
    else:
        parsed = urlparse(official_url)
        if parsed.netloc != SOURCE_HOST:
            errors.append(f"Invalid official_url host '{parsed.netloc}' for '{slug}' (expected '{SOURCE_HOST}')")

    # Validate localized official_urls
    official_urls = m.get("official_urls", {})
    for loc in ["nl", "en", "uk"]:
        if loc not in official_urls:
            errors.append(f"Missing official_urls['{loc}'] for '{slug}'")
        else:
            loc_parsed = urlparse(official_urls[loc])
            if loc_parsed.netloc != SOURCE_HOST:
                errors.append(f"Invalid official_urls['{loc}'] host for '{slug}'")

    # Validate coordinates if present
    lat = m.get("lat")
    lon = m.get("lon")
    if lat is not None and lon is not None:
        if not (NL_LAT_MIN <= lat <= NL_LAT_MAX and NL_LON_MIN <= lon <= NL_LON_MAX):
            errors.append(f"Coordinates ({lat}, {lon}) outside Netherlands bounds for '{slug}'")

    # Validate programmes
    programmes = m.get("programmes")
    if not isinstance(programmes, list) or not programmes or not all(isinstance(p, str) and p for p in programmes):
        errors.append(f"Missing or invalid programmes array for '{slug}'")

    return errors


def validate_dataset(
    museums: List[Dict[str, Any]],
    previous_dataset: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str]]:
    """
    Validate full dataset against §8.2 validation rules:
    - Count at least MIN_MUSEUM_COUNT (100) and within ±20% of previous run (or baseline 195)
    - Slugs unique and non-empty
    - At least 95% of museums have city and valid coordinates inside NL
    - No more than 10% added or removed compared to previous run
    """
    errors: List[str] = []
    # Validation operates only on active museums; removed ones are preserved but ignored
    active_museums = [m for m in museums if m.get("status", "active") != "removed"]
    count = len(active_museums)

    # 1. Total count checks
    if count < MIN_MUSEUM_COUNT:
        errors.append(f"Active museum count {count} is below minimum required {MIN_MUSEUM_COUNT}")

    base_count = EXPECTED_BASELINE_COUNT
    if previous_dataset and "museums" in previous_dataset:
        prev_active = [m for m in previous_dataset["museums"] if m.get("status", "active") != "removed"]
        prev_count = len(prev_active)
        if prev_count > 0:
            base_count = prev_count

    count_diff_pct = abs(count - base_count) / base_count * 100.0
    if count_diff_pct > MAX_COUNT_CHANGE_PERCENT:
        errors.append(
            f"Active museum count changed by {count_diff_pct:.1f}% ({count} vs baseline {base_count}), "
            f"exceeding max allowed {MAX_COUNT_CHANGE_PERCENT}%"
        )

    # 2. Slugs uniqueness (across all museums including removed, to prevent re-use)
    slugs_seen: Set[str] = set()
    duplicate_slugs: Set[str] = set()
    for m in museums:
        s = m.get("slug")
        if not s or s in slugs_seen:
            duplicate_slugs.add(s)
        else:
            slugs_seen.add(s)

    if duplicate_slugs:
        errors.append(f"Duplicate or empty slugs found: {duplicate_slugs}")

    # 3. Individual record validation (active only)
    for m in active_museums:
        rec_errors = validate_single_museum(m)
        errors.extend(rec_errors)

    # 4. Geocoding and city completeness (≥95%, active only)
    complete_geo_count = sum(
        1 for m in active_museums
        if m.get("city") and m.get("lat") is not None and m.get("lon") is not None
    )
    complete_geo_pct = (complete_geo_count / count * 100.0) if count > 0 else 0.0

    if complete_geo_pct < MIN_COMPLETE_GEO_PERCENT:
        errors.append(
            f"Only {complete_geo_count}/{count} ({complete_geo_pct:.1f}%) active museums have valid city and coordinates "
            f"(minimum required: {MIN_COMPLETE_GEO_PERCENT}%)"
        )

    # 5. Turnover checks on active slugs only (if previous dataset available)
    if previous_dataset and "museums" in previous_dataset:
        prev_active_slugs = set(
            pm.get("slug") for pm in previous_dataset["museums"]
            if pm.get("slug") and pm.get("status", "active") != "removed"
        )
        curr_active_slugs = set(m.get("slug") for m in active_museums if m.get("slug"))

        added = curr_active_slugs - prev_active_slugs
        removed = prev_active_slugs - curr_active_slugs

        turnover_added_pct = (len(added) / len(prev_active_slugs) * 100.0) if prev_active_slugs else 0.0
        turnover_removed_pct = (len(removed) / len(prev_active_slugs) * 100.0) if prev_active_slugs else 0.0

        if turnover_added_pct > MAX_TURNOVER_PERCENT:
            errors.append(
                f"Turnover: {len(added)} museums added ({turnover_added_pct:.1f}%), exceeding {MAX_TURNOVER_PERCENT}% limit"
            )
        if turnover_removed_pct > MAX_TURNOVER_PERCENT:
            errors.append(
                f"Turnover: {len(removed)} museums removed ({turnover_removed_pct:.1f}%), exceeding {MAX_TURNOVER_PERCENT}% limit"
            )

    # 6. Shared resources audit (warnings only, non-blocking)
    check_shared_resources(museums)

    is_valid = len(errors) == 0
    return is_valid, errors
