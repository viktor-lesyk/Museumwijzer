import re
import unicodedata
from typing import Dict, Optional, Set
import yaml

from .config import CITY_ALIASES_PATH

DUTCH_PROVINCES: Set[str] = {
    "Drenthe",
    "Flevoland",
    "Friesland",
    "Gelderland",
    "Groningen",
    "Limburg",
    "Noord-Brabant",
    "Noord-Holland",
    "Overijssel",
    "Utrecht",
    "Zeeland",
    "Zuid-Holland",
}


def load_city_aliases(aliases_path=CITY_ALIASES_PATH) -> Dict[str, str]:
    """Load city aliases from YAML file."""
    if not aliases_path.exists():
        return {}
    try:
        with open(aliases_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


CITY_ALIASES = load_city_aliases()


def normalise_text(text: Optional[str]) -> Optional[str]:
    """Normalize text to NFC, collapse multiple whitespace, and strip leading/trailing spaces."""
    if text is None:
        return None
    # NFC Unicode normalization
    norm = unicodedata.normalize("NFC", text)
    # Collapse multiple whitespace characters into single space
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm if norm else None


def normalise_postcode(postcode: Optional[str]) -> Optional[str]:
    """Format Dutch postcode into standard 'NNNN AA' format."""
    if not postcode:
        return None
    cleaned = normalise_text(postcode)
    if not cleaned:
        return None
    # Remove any internal spaces and uppercase letters
    compact = re.sub(r"\s+", "", cleaned).upper()
    if len(compact) == 6 and compact[:4].isdigit() and compact[4:].isalpha():
        return f"{compact[:4]} {compact[4:]}"
    elif len(compact) == 5 and compact[:3].isdigit() and compact[3:].isalpha():
        # 3-digit typo fallback
        return f"{compact[:3]} {compact[3:]}"
    return cleaned


PROVINCE_ALIASES: Dict[str, str] = {
    "fryslân": "Friesland",
    "fryslan": "Friesland",
}


def normalise_province(province: Optional[str]) -> Optional[str]:
    """Validate and normalise province name against official 12 Dutch provinces (Friesland = Fryslân)."""
    if not province:
        return None
    cleaned = normalise_text(province)
    if not cleaned:
        return None
    lower = cleaned.lower()
    if lower in PROVINCE_ALIASES:
        return PROVINCE_ALIASES[lower]
    # Case-insensitive match against standard 12 provinces
    for standard in DUTCH_PROVINCES:
        if standard.lower() == lower:
            return standard
    return cleaned


def normalise_city(city: Optional[str], aliases: Dict[str, str] = CITY_ALIASES) -> Optional[str]:
    """Normalize city name, resolving aliases (e.g. 'Den Haag' -> ''s-Gravenhage')."""
    if not city:
        return None
    cleaned = normalise_text(city)
    if not cleaned:
        return None
    # Check alias dictionary (case-insensitive lookup)
    for alias, canonical in aliases.items():
        if alias.lower() == cleaned.lower():
            return canonical
    return cleaned
