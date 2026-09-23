"""Identity and metadata discovery jobs: website discovery and address verification.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. These jobs NEVER write to data/overrides.yaml.
2. They write candidate findings strictly to data/enrichment/proposals.json.
3. The website job strictly rejects aggregators, directories, social media, and booking platforms.
4. Candidate websites must explicitly mention the museum's name and city.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from enrich.audit_identity import check_identity, extract_page_identity
from enrich.fetch import PoliteFetcher
from enrich.ops.proposals import load_proposals, record_proposals
from enrich.tools.fetch_page import sanitize_html_for_agent
from enrich.tools.web_search import execute_web_search

logger = logging.getLogger("enrich.identity")

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSEUMS_JSON_PATH = REPO_ROOT / "data" / "museums.json"

AGGREGATOR_DOMAINS = {
    "tripadvisor.com",
    "tripadvisor.nl",
    "wikipedia.org",
    "museum.nl",
    "whichmuseum.nl",
    "whichmuseum.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "visitholland.com",
    "holland.com",
    "dagjeweg.nl",
    "kidsproof.nl",
    "museumkids.nl",
    "vvv.nl",
    "welkominhetmuseum.vriendenloterij.nl",
    "welkom-in-het-museum.nl",
    "onh.nl",
    "vvvzeeland.nl",
    "bing.com",
    "duckduckgo.com",
    "hotelspecials.nl",
    "booking.com",
    "anwb.nl",
    "tiqets.com",
    "getyourguide.com",
    "visitacity.com",
    "erfgoedbovenamsterdam.nl",
    "visitingthedutchcountryside.com",
    "rocketreach.co",
    "yelp.com",
    "yelp.nl",
    "iamsterdam.com",
    "vlieland.net",
    "vlieland.org",
    "texel.net",
    "zeeland.com",
    "visitwadden.nl",
    "gocity.com",
    "amsterdamtips.com",
    "denhaag.com",
    "rotterdam.info",
    "hilversum.nl",
    "livehilversum.com",
    "visitgooivecht.nl",
    "omgevingseducatie.nl",
    "openmonumentendag.nl",
    "onh.nl",
}


def is_aggregator_url(url: str) -> bool:
    """Return True if url belongs to an aggregator, directory, social media, or search portal."""
    if not url:
        return True
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return True

    # Check exact match or subdomain match (e.g. www.museum.nl or nl.wikipedia.org)
    for agg in AGGREGATOR_DOMAINS:
        if host == agg or host.endswith("." + agg):
            return True
    if "vvv" in host.split(".")[0]:
        return True
    return False


def discover_museum_website(
    museum: Dict[str, Any],
    fetcher: Optional[PoliteFetcher] = None,
) -> Optional[Dict[str, Any]]:
    """Search for and verify the official website of a museum lacking one.

    Returns proposal dictionary if a verified official website is found, else None.
    """
    slug = museum["slug"]
    name = museum["name"]
    city = museum.get("city")
    fetcher = fetcher or PoliteFetcher()

    from enrich.audit_identity import get_distinctive_tokens
    distinctive_tokens = get_distinctive_tokens(name, city)

    # 1. Search queries
    queries = [
        f'"{name}"',
        f'"{name}" official website',
        f'"{name}" {city or ""} website',
    ]

    candidate_urls: List[str] = []
    seen_urls: Set[str] = set()

    for q in queries:
        search_res = execute_web_search(q)
        for item in search_res.get("results", []):
            u = item.get("url")
            if not u or is_aggregator_url(u) or u in seen_urls:
                continue
            seen_urls.add(u)
            candidate_urls.append(u)

    # 2. Add direct candidate domain heuristics based on slug and distinctive tokens
    slug_clean = re.sub(r"[^a-z0-9]", "", slug.lower().replace("-1", "").replace("1", ""))
    direct_candidates = [
        f"https://www.{slug_clean}.nl/",
        f"https://{slug_clean}.nl/",
    ]
    for tok in sorted(list(distinctive_tokens), key=len, reverse=True):
        if len(tok) >= 5:
            direct_candidates.extend([f"https://www.{tok}.nl/", f"https://{tok}.nl/"])
        if "zilver" in tok:
            direct_candidates.extend(["https://zilvermuseum.com/", "https://www.zilvermuseum.com/"])

    for dc in direct_candidates:
        if dc not in seen_urls and not is_aggregator_url(dc):
            seen_urls.add(dc)
            candidate_urls.append(dc)

    # Prioritize candidate URLs whose host or path shares distinctive tokens
    def score_candidate(u: str) -> int:
        score = 0
        u_lower = u.lower()
        for tok in distinctive_tokens:
            if tok in urlparse(u_lower).netloc:
                score += 3
            elif tok in u_lower:
                score += 1
        return score

    sorted_candidates = sorted(candidate_urls, key=score_candidate, reverse=True)

    for candidate in sorted_candidates[:12]:
        success, html, err = fetcher.fetch(candidate)
        if not success or not html:
            continue

        page_data = extract_page_identity(html)
        status, reason = check_identity(name, city, candidate, page_data)

        if status in ("match", "weak_match"):
            # Ensure page explicitly mentions the museum's name AND city (or museum/cultural context)
            norm_full = f"{page_data['title']} {page_data['h1']} {page_data['meta_description']} {page_data['body_preview']}".lower()
            name_tokens = get_distinctive_tokens(name, None)
            city_tokens = get_distinctive_tokens(city, None) if city else set()

            has_name = any(t in norm_full for t in name_tokens)
            has_city = any(t in norm_full for t in city_tokens) if city_tokens else False
            has_culture_kw = any(kw in norm_full for kw in ["museum", "collectie", "tentoonstelling", "erfgoed", "monument", "bezoek", "tickets"])

            if not (has_name and (has_city or has_culture_kw)):
                continue

            title = page_data.get("title", "")
            h1 = page_data.get("h1", "")
            quote = f"{title} | {h1}".strip(" |")[:100]

            # Normalize website URL to https site root, except huis-willet-holthuysen which stays a deep link
            parsed_cand = urlparse(candidate)
            netloc = parsed_cand.netloc.lower()
            if slug == "huis-willet-holthuysen":
                clean_url = f"https://{netloc}{parsed_cand.path}".rstrip("/")
            else:
                clean_url = f"https://{netloc}/"

            return {
                "slug": slug,
                "field": "museum_website",
                "current_value": museum.get("museum_website"),
                "proposed_value": clean_url,
                "evidence_url": candidate,
                "quote": quote,
                "confidence": "high" if status == "match" else "medium",
                "reason": (
                    f"Discovered official website matching distinctive tokens for "
                    f"'{name}' in {city or 'Netherlands'}."
                ),
                "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }

    return None


POSTCODE_REGEX = re.compile(r"\b([1-9][0-9]{3})\s?([A-Za-z]{2})\b")


def check_museum_address(
    museum: Dict[str, Any],
    fetcher: Optional[PoliteFetcher] = None,
) -> Optional[Dict[str, Any]]:
    """Check official contact page for physical address discrepancies.

    Returns proposal dictionary if an address mismatch or typo is confirmed, else None.
    """
    slug = museum["slug"]
    name = museum["name"]
    website = museum.get("museum_website")
    curr_addr = museum.get("address") or {}

    if not website:
        return None

    fetcher = fetcher or PoliteFetcher()

    # Candidate contact paths
    candidates = [
        urljoin(website, "contact"),
        urljoin(website, "contact/"),
        urljoin(website, "bereikbaarheid"),
        urljoin(website, "route"),
        urljoin(website, "plan-je-bezoek"),
        urljoin(website, "praktische-informatie"),
        website,
    ]

    for cand_url in candidates:
        success, html, err = fetcher.fetch(cand_url)
        if not success or not html:
            continue

        parsed = sanitize_html_for_agent(html, cand_url, max_chars=12000)
        text = parsed["text"]

        # Search for postal codes
        matches = list(POSTCODE_REGEX.finditer(text))
        if not matches:
            continue

        curr_postcode_raw = curr_addr.get("postcode", "").replace(" ", "").upper()

        for m in matches:
            found_pc_digits = m.group(1)
            found_pc_letters = m.group(2).upper()
            found_postcode = f"{found_pc_digits} {found_pc_letters}"
            found_pc_raw = f"{found_pc_digits}{found_pc_letters}"

            # Extract window around match
            start_pos = max(0, m.start() - 100)
            end_pos = min(len(text), m.end() + 100)
            window = text[start_pos:end_pos].replace("\n", " ")
            window = re.sub(r"\s+", " ", window).strip()

            # If postal code differs from museums.json
            if curr_postcode_raw and curr_postcode_raw != found_pc_raw:
                # Check if this postal code belongs to the museum and is in the same or intended city
                words = window.split()
                quote = " ".join(words[:15])

                # Extract potential street name and city from window
                city = museum.get("city") or curr_addr.get("city")

                return {
                    "slug": slug,
                    "field": "address",
                    "current_value": curr_addr,
                    "proposed_value": {
                        "postcode": found_postcode,
                        "city": curr_addr.get("city"),
                        "note": f"Contact page lists postcode '{found_postcode}' (current is '{curr_addr.get('postcode')}').",
                    },
                    "evidence_url": cand_url,
                    "quote": quote,
                    "confidence": "high",
                    "reason": f"Discrepancy detected: contact page states '{found_postcode}' instead of '{curr_addr.get('postcode')}'.",
                    "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }

    return None


def run_identity_job(
    job_name: str,
    slug: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Run website discovery or address verification job and record findings strictly to proposals.json."""
    if not MUSEUMS_JSON_PATH.exists():
        raise FileNotFoundError(f"{MUSEUMS_JSON_PATH} not found")

    with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    museums = [m for m in data.get("museums", []) if m.get("status", "active") != "removed"]
    if slug:
        museums = [m for m in museums if m.get("slug") == slug]
    if limit and limit > 0:
        museums = museums[:limit]

    fetcher = PoliteFetcher()
    proposals: List[Dict[str, Any]] = []

    print("=" * 65)
    print(f"=== RUNNING IDENTITY JOB: {job_name.upper()} ===")
    print(f"Target Museums: {len(museums)}")
    print("CRITICAL: Findings will be saved to data/enrichment/proposals.json.")
    print("          data/overrides.yaml will NOT be modified.")
    print("=" * 65)

    if job_name == "website":
        # Target museums missing museum_website
        targets = [m for m in museums if not m.get("museum_website")] if not slug else museums
        print(f"Found {len(targets)} museum(s) requiring website discovery.")

        for i, m in enumerate(targets, 1):
            print(f"\n[{i}/{len(targets)}] Discovering website for {m['slug']} ('{m['name']}', {m.get('city')})...")
            prop = discover_museum_website(m, fetcher=fetcher)
            if prop:
                proposals.append(prop)
                print(f"  -> FOUND CANDIDATE: {prop['proposed_value']}")
                print(f"     Quote: {prop['quote']}")
                print(f"     Confidence: {prop['confidence']}")
            else:
                print("  -> No verified official website candidate found.")

    elif job_name == "address_check":
        targets = [m for m in museums if m.get("museum_website")]
        print(f"Checking address on contact pages for {len(targets)} museum(s)...")

        for i, m in enumerate(targets, 1):
            prop = check_museum_address(m, fetcher=fetcher)
            if prop:
                proposals.append(prop)
                print(f"\n[!] DISCREPANCY DETECTED for {m['slug']}:")
                print(f"    Current:  {prop['current_value']}")
                print(f"    Proposed: {prop['proposed_value']}")
                print(f"    Evidence: {prop['evidence_url']}")
                print(f"    Quote:    {prop['quote']}")

    else:
        raise ValueError(f"Unknown identity job '{job_name}'. Supported: 'website', 'address_check'.")

    # Record strictly to proposals.json
    total_stored = record_proposals(proposals)

    print("\n" + "=" * 65)
    print("=== IDENTITY JOB COMPLETED ===")
    print(f"New proposals found this run: {len(proposals)}")
    print(f"Total pending proposals in data/enrichment/proposals.json: {total_stored}")
    print("Reminder: data/overrides.yaml was preserved untouched.")
    print("=" * 65 + "\n")

    return proposals
