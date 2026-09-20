import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from .config import SOURCE_BASE_URL, SUPPORTED_LOCALES

logger = logging.getLogger(__name__)

# Strict Dutch postal code pattern: 4 digits (1000-9999) + 2 uppercase letters (e.g. 1071 DJ)
POSTCODE_PATTERN = re.compile(r"\b([1-9]\d{3})\s*([A-Z]{2})\b")
# Fallback pattern for occasional 3-digit typos in source (e.g. '297 BP' in Den Haag)
POSTCODE_FALLBACK_PATTERN = re.compile(r"\b(\d{3,4})\s*([A-Z]{2})\b")


class ParsedMuseumRaw(BaseModel):
    """Whitelisted factual fields extracted from source. All creative content is discarded."""
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    province: str
    street: Optional[str] = None
    postcode: Optional[str] = None
    city: Optional[str] = None
    museum_website: Optional[str] = None
    source_date_raw: Optional[str] = None
    official_url: str
    official_urls: Dict[str, str]
    programmes: List[str] = Field(default_factory=lambda: ["welkom-in-het-museum"])


def build_official_urls(slug: str) -> Tuple[str, Dict[str, str]]:
    """Build localized official museum URLs for supported locales."""
    official_urls = {
        locale: f"{SOURCE_BASE_URL}/{locale}/musea/{slug}/"
        for locale in SUPPORTED_LOCALES
    }
    canonical_url = official_urls["nl"]
    return canonical_url, official_urls


def extract_paragraphs_and_links(blocks: List[Dict[str, Any]]) -> List[Tuple[str, List[str]]]:
    """Extract plain text lines and external links per paragraph, discarding styling and images."""
    paragraphs: List[Tuple[str, List[str]]] = []

    def _traverse(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "paragraph":
                p_text_parts: List[str] = []
                p_links: List[str] = []
                for child in node.get("content", []):
                    if child.get("type") == "text":
                        p_text_parts.append(child.get("text", ""))
                        for mark in child.get("marks", []):
                            if mark.get("type") == "link":
                                href = mark.get("attrs", {}).get("href")
                                if href:
                                    p_links.append(href)
                    elif child.get("type") == "hard_break":
                        p_text_parts.append("\n")
                paragraphs.append(("".join(p_text_parts), p_links))
            else:
                for v in node.values():
                    _traverse(v)
        elif isinstance(node, list):
            for item in node:
                _traverse(item)

    _traverse(blocks)
    return paragraphs


def is_external_museum_link(url: str) -> bool:
    """Filter out internal lottery, charity, or relative links."""
    if not url or url.startswith("/") or url.startswith("#"):
        return False
    lower = url.lower()
    excluded = ["vriendenloterij", "vluchtelingenwerk", "cultuurfonds", "postcodeloterij", "storyblok"]
    return not any(domain in lower for domain in excluded)


def clean_city_string(raw: str) -> str:
    """Clean extracted city string from artifacts like 'in Laren (Gelderland)' or trailing commas."""
    city = raw.strip(" ,.-")
    # Remove leading 'in ' (e.g. 'in Laren')
    if city.lower().startswith("in "):
        city = city[3:].strip()
    # If contains comma followed by province (e.g. 'Ammerzoden, Gelderland'), keep city name
    if "," in city:
        city = city.split(",")[0].strip()
    # Remove parenthetical province (e.g. 'Laren (Gelderland)')
    city = re.sub(r"\s*\([^)]*\)", "", city).strip()
    return city


def parse_contact_block(blocks: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Parse address (street, postcode, city) and museum website from detail blocks.
    Returns: (street, postcode, city, museum_website)
    """
    paragraphs = extract_paragraphs_and_links(blocks)
    street: Optional[str] = None
    postcode: Optional[str] = None
    city: Optional[str] = None
    museum_website: Optional[str] = None

    # Collect all candidate external links across all paragraphs
    all_ext_links: List[str] = []
    for _, links in paragraphs:
        for link in links:
            if is_external_museum_link(link) and link not in all_ext_links:
                all_ext_links.append(link)

    # Search for contact paragraph containing postal code
    for p_text, p_links in paragraphs:
        lines = [line.strip() for line in p_text.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            # Check postal code pattern
            m = POSTCODE_PATTERN.search(line) or POSTCODE_FALLBACK_PATTERN.search(line)
            if m:
                # Format: 4-digit (or 3-digit) + uppercase letters
                num_part = m.group(1)
                letter_part = m.group(2).upper()
                postcode = f"{num_part} {letter_part}"

                # City is the remaining text on the same line after the postcode, or on the next line
                city_raw = line[m.end():].strip()
                if city_raw:
                    city = clean_city_string(city_raw)
                elif idx + 1 < len(lines) and not is_external_museum_link(lines[idx + 1]):
                    # Check next line for city if not a URL
                    city = clean_city_string(lines[idx + 1])

                # Street is either before postcode on the same line or on preceding line
                before_pc = line[:m.start()].strip()
                if before_pc and any(c.isdigit() for c in before_pc):
                    street = before_pc
                elif idx > 0:
                    cand_street = lines[idx - 1]
                    # Make sure the candidate street isn't just the word 'Contact'
                    if cand_street.lower() != "contact":
                        street = cand_street

                # Look for link in this paragraph first
                for link in p_links:
                    if is_external_museum_link(link):
                        museum_website = link
                        break
                break

        if postcode:
            break

    # If no website found in contact paragraph, use first external link found in story
    if not museum_website and all_ext_links:
        museum_website = all_ext_links[0]

    return street, postcode, city, museum_website


def parse_museum_story(story: Dict[str, Any]) -> ParsedMuseumRaw:
    """
    Parse a single museum story (from list or detail) into a whitelisted factual record.
    All creative descriptions, teasers, and images are completely omitted.
    """
    slug = story["slug"]
    name = story.get("name", "").strip()

    # Extract province from tags
    content = story.get("content", {})
    tags = content.get("tags", [])
    province = ""
    if tags and isinstance(tags, list):
        tag_obj = tags[0]
        if isinstance(tag_obj, dict):
            province = tag_obj.get("name", "").strip()

    # Raw publication / creation timestamp
    source_date_raw = story.get("first_published_at") or story.get("created_at")

    official_url, official_urls = build_official_urls(slug)

    # Extract address and website from blocks
    blocks = content.get("blocks", [])
    street, postcode, city, museum_website = parse_contact_block(blocks)

    return ParsedMuseumRaw(
        slug=slug,
        name=name,
        province=province,
        street=street,
        postcode=postcode,
        city=city,
        museum_website=museum_website,
        source_date_raw=source_date_raw,
        official_url=official_url,
        official_urls=official_urls,
        programmes=["welkom-in-het-museum"],
    )
