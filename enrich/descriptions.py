"""Museum description, highlight, and visual enrichment pipeline.

Fetches factual background from Dutch Wikipedia / Wikimedia Commons and synthesizes:
1. 3-5 sentence engaging, factual summary (in nl, en, uk).
2. 3-4 bullet points on why it's worth visiting / what it's known for (in nl, en, uk).
3. 2-4 category tags in Dutch.
4. Verified main photo from Wikimedia Commons with author and CC license attribution.

Zero billing risk: uses free-tier LiteLLM `free-lite` (Gemini Flash-Lite).
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env if present
env_path = REPO_ROOT / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

USER_AGENT = "Museumwijzer/1.0 (https://museumwijzer.vlesyk.com; museumwijzer@vlesyk.com)"
HEADERS = {"User-Agent": USER_AGENT}

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
LITELLM_MODEL = os.environ.get("LITELLM_FREE_LITE_MODEL", "free-lite")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "sk-localproxy")

DESCRIPTIONS_PATH = Path("data/enrichment/descriptions.json")
MUSEUMS_PATH = Path("data/museums.json")


def clean_html(raw_html: str) -> str:
    """Strip HTML tags and unescape entities."""
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", "", raw_html)
    clean = clean.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return clean.strip()


def query_wikipedia(museum_name: str, city: str) -> Optional[Dict[str, Any]]:
    """Search Dutch Wikipedia for the museum and fetch extract + image metadata.
    
    Ensures that generic city pages (e.g. 'Zwolle') are rejected.
    """
    search_queries = [
        f'"{museum_name}"',
        f"{museum_name} {city}",
        f"{museum_name} museum",
        museum_name,
    ]

    wiki_endpoint = "https://nl.wikipedia.org/w/api.php"
    found_title = None

    for q in search_queries:
        try:
            r = requests.get(
                wiki_endpoint,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": q,
                    "srlimit": 3,
                    "format": "json",
                },
                headers=HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            hits = data.get("query", {}).get("search", [])
            for hit in hits:
                title = hit.get("title", "")
                snippet = hit.get("snippet", "").lower()
                # Verification: snippet or title should contain museum-related keywords
                keywords = ["museum", "kasteel", "collectie", "tentoonstelling", "erfgoed", "monument", "galerie", "kunst", "paleis", "histor", "bezoek", "cultuur"]
                if any(kw in snippet for kw in keywords) or any(kw in title.lower() for kw in ["museum", "kasteel", "huis", "paleis", "center"]):
                    found_title = title
                    break
            if found_title:
                break
        except Exception as e:
            logger.debug(f"Search query '{q}' failed: {e}")

    if not found_title:
        return None

    # Fetch page extract, page image, and image list
    try:
        r = requests.get(
            wiki_endpoint,
            params={
                "action": "query",
                "titles": found_title,
                "prop": "extracts|pageimages|images",
                "exintro": True,
                "explaintext": True,
                "piprop": "name|thumbnail",
                "pithumbsize": 960,
                "imlimit": 30,
                "format": "json",
            },
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        pdata = list(r.json().get("query", {}).get("pages", {}).values())[0]
        if pdata.get("pageid") is None:
            return None

        extract = pdata.get("extract", "").strip()
        img_name = pdata.get("pageimage")
        thumb_url = pdata.get("thumbnail", {}).get("source")

        # Collect up to 3-4 quality photos from page and Commons
        images_info: List[Dict[str, Any]] = []
        seen_files = set()

        if img_name and "logo" not in img_name.lower() and any(img_name.lower().endswith(ext) for ext in [".jpg", ".jpeg"]):
            p_info = fetch_commons_image_info(img_name, thumb_url)
            if p_info:
                images_info.append(p_info)
                seen_files.add(img_name.lower())

        page_images = pdata.get("images", [])
        for im in page_images:
            if len(images_info) >= 3:
                break
            ititle = im.get("title", "").replace("Bestand:", "").replace("File:", "").strip()
            ilower = ititle.lower()
            if ilower in seen_files:
                continue
            if (any(ilower.endswith(ext) for ext in [".jpg", ".jpeg"])
                and not any(bad in ilower for bad in ["logo", "map", "kaart", "wapen", "vlag", "icon", "flag", "banner"])):
                c_info = fetch_commons_image_info(ititle, None)
                if c_info:
                    images_info.append(c_info)
                    seen_files.add(ilower)

        return {
            "title": found_title,
            "extract": extract,
            "images": images_info,
            "image": images_info[0] if images_info else None,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch details for '{found_title}': {e}")
        return None


def fetch_commons_image_info(img_name: str, thumb_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query Wikimedia Commons for artist, license, and page URL."""
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "titles": f"File:{img_name}",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": 960,
                "format": "json",
            },
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        cp = list(pages.values())[0]
        ii = cp.get("imageinfo", [{}])[0]
        meta = ii.get("extmetadata", {})

        author = clean_html(meta.get("Artist", {}).get("value", "Unknown"))
        if len(author) > 60:
            author = author.split(",")[0].strip()
        if not author or author.lower() in ["unknown", "onbekend"]:
            author = clean_html(meta.get("Credit", {}).get("value", "Wikimedia Commons"))
            if len(author) > 60:
                author = author[:60]

        license_short = meta.get("LicenseShortName", {}).get("value", "CC BY-SA")
        license_url = meta.get("LicenseUrl", {}).get("value")
        source_url = f"https://commons.wikimedia.org/wiki/File:{img_name}"

        url = thumb_url or ii.get("thumburl") or ii.get("url")
        if not url:
            return None

        return {
            "url": url,
            "author": author or "Wikimedia Commons",
            "license": license_short,
            "license_url": license_url,
            "source_url": source_url,
        }
    except Exception as e:
        logger.debug(f"Failed to fetch Commons image info for '{img_name}': {e}")
        return None


def parse_json_from_llm(raw: str) -> Optional[Dict[str, Any]]:
    """Safely parse JSON from LLM output, handling markdown fences or extra trailing text."""
    if not raw:
        return None
    try:
        return json.loads(raw.strip())
    except Exception:
        pass

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    try:
        idx = raw.find("{")
        if idx != -1:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(raw[idx:])
            return obj
    except Exception:
        pass

    return None


ALLOWED_CATEGORIES = [
    "kunst",
    "geschiedenis",
    "kastelen",
    "wetenschap",
    "natuur",
    "familie",
]


def synthesize_description(museum: Dict[str, Any], wiki_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Call free-tier LLM to synthesize summary, why_visit bullet points, and category tags."""
    context = ""
    if wiki_info and wiki_info.get("extract"):
        context = f"Wikipedia background:\n{wiki_info['extract']}"
    elif museum.get("museum_website"):
        context = f"Official website: {museum['museum_website']}"

    prompt = f"""You are an expert cultural guide writing an informative, welcoming directory of museums in the Netherlands.
Museum: {museum.get('name')}
City: {museum.get('city')}
Province: {museum.get('province')}
{context}

Generate a JSON object with:
1. "summary": an engaging, factual, concise summary of 3-5 sentences in three languages ("nl", "en", "uk") explaining what the museum is, its primary focus or theme, and what visitors can expect to discover.
2. "why_visit": 3-4 bullet points in three languages ("nl", "en", "uk") describing key highlights, renowned exhibits, or unique reasons to visit.
3. "categories": select 1 or 2 PRE-DEFINED CATEGORIES from this exact list ONLY:
   - "kunst" (Art & Design: paintings, sculpture, modern art, graphic design)
   - "geschiedenis" (History & Heritage: cultural history, archaeology, war & peace, local heritage)
   - "kastelen" (Castles & Palaces: historic castles, royal palaces, fortified estates, country houses)
   - "wetenschap" (Science & Technology: science, engineering, maritime/naval, transport, trains, space)
   - "natuur" (Nature & Animals: natural history, biodiversity, wildlife, geology, botanical gardens)
   - "familie" (Family & Interactive: hands-on discovery, child-friendly, open-air parks)

Do NOT copy promotional hype or marketing clichés. Keep it clear, objective, and inspiring for newcomers, families, and cultural explorers. Write strictly in proper Dutch for "nl", standard English for "en", and Ukrainian for "uk". Never mix languages or include characters from other scripts. Respond ONLY with valid JSON.
"""

    payload = {
        "model": LITELLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a professional multilingual museum editor. Output strictly valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    headers = {"Authorization": f"Bearer {LITELLM_API_KEY}"}
    url = f"{LITELLM_BASE_URL.rstrip('/')}/chat/completions"

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=40)
        r.raise_for_status()
        res = r.json()
        content = res["choices"][0]["message"]["content"]
        data = parse_json_from_llm(content)
        if not data:
            raise ValueError(f"Could not parse valid JSON from: {content[:100]}...")
        return data
    except Exception as e:
        logger.error(f"LLM synthesis failed for {museum.get('slug')}: {e}")
        return {
            "summary": {
                "nl": f"{museum.get('name')} in {museum.get('city')}.",
                "en": f"{museum.get('name')} in {museum.get('city')}.",
                "uk": f"{museum.get('name')} у місті {museum.get('city')}.",
            },
            "why_visit": {
                "nl": [],
                "en": [],
                "uk": [],
            },
            "tags": [],
        }


def load_descriptions() -> Dict[str, Any]:
    if DESCRIPTIONS_PATH.exists():
        try:
            with open(DESCRIPTIONS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "museums": []}


def save_descriptions(data: Dict[str, Any]) -> None:
    DESCRIPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(DESCRIPTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(data['museums'])} descriptions to {DESCRIPTIONS_PATH}")


def run_enrichment(slugs: Optional[List[str]] = None, limit: Optional[int] = None, force: bool = False) -> None:
    with open(MUSEUMS_PATH, "r", encoding="utf-8") as f:
        museums_data = json.load(f)

    all_museums = museums_data.get("museums", [])
    if slugs:
        target_museums = [m for m in all_museums if m.get("slug") in slugs]
    elif limit:
        target_museums = all_museums[:limit]
    else:
        target_museums = all_museums

    desc_store = load_descriptions()
    existing_map = {m["slug"]: m for m in desc_store.get("museums", []) if "slug" in m}

    processed = 0
    for museum in target_museums:
        slug = museum.get("slug")
        if not slug:
            continue

        if slug in existing_map and not force:
            logger.info(f"Skipping already enriched museum: {slug}")
            continue

        logger.info(f"Processing museum: {museum.get('name')} ({slug}) in {museum.get('city')}")

        # 1. Wikipedia + Wikimedia
        wiki_info = query_wikipedia(museum.get("name", ""), museum.get("city", ""))
        image_meta = wiki_info.get("image") if wiki_info else None
        images_list = wiki_info.get("images", []) if wiki_info else []
        if not images_list and image_meta:
            images_list = [image_meta]

        # 2. LLM synthesis
        llm_output = synthesize_description(museum, wiki_info)

        cats = [c for c in llm_output.get("categories", llm_output.get("tags", [])) if c in ALLOWED_CATEGORIES]
        if not cats:
            cats = ["geschiedenis"]

        record = {
            "slug": slug,
            "name": museum.get("name"),
            "image": image_meta,
            "images": images_list,
            "summary": llm_output.get("summary", {}),
            "why_visit": llm_output.get("why_visit", {}),
            "categories": cats,
            "tags": cats,
            "source": "wikipedia_and_commons" if wiki_info else "official_website",
            "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

        existing_map[slug] = record
        desc_store["museums"] = list(existing_map.values())
        save_descriptions(desc_store)
        processed += 1

    logger.info(f"Enrichment pass completed. Processed {processed} museums.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Museum description and photo enrichment")
    parser.add_argument("--slugs", nargs="+", help="Specific museum slugs to enrich")
    parser.add_argument("--limit", type=int, help="Limit number of museums")
    parser.add_argument("--force", action="store_true", help="Re-enrich even if already present")
    args = parser.parse_args()

    run_enrichment(slugs=args.slugs, limit=args.limit, force=args.force)
