"""Enrich museums with public review ratings and review counts.

Zero billing risk: uses free-tier LiteLLM `free-lite` (Gemini Flash-Lite).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List
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

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
LITELLM_MODEL = os.environ.get("LITELLM_FREE_LITE_MODEL", "free-lite")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "sk-localproxy")

RATINGS_PATH = REPO_ROOT / "data" / "enrichment" / "ratings.json"
MUSEUMS_PATH = REPO_ROOT / "data" / "museums.json"


def load_ratings() -> Dict[str, Any]:
    if RATINGS_PATH.exists():
        try:
            with open(RATINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": 1, "museums": []}


def save_ratings(data: Dict[str, Any]) -> None:
    RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RATINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(data['museums'])} ratings to {RATINGS_PATH}")


def fetch_batch_ratings(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    museum_list_str = "\n".join(
        [f"- slug: {m['slug']}, name: {m['name']}, city: {m.get('city', '')}" for m in batch]
    )

    prompt = f"""For each of the following museums in the Netherlands, provide their typical Google Maps / Google review rating (out of 5.0, e.g. 4.6) and approximate number of reviews (e.g. 1500, 32000, 115000):

{museum_list_str}

Respond ONLY with a valid JSON object matching this schema:
{{
  "ratings": [
    {{
      "slug": "museum-slug",
      "rating": 4.6,
      "reviews_count": 1250
    }}
  ]
}}
If a museum's rating is truly unknown, you may use null for rating and 0 for reviews_count.
"""

    payload = {
        "model": LITELLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a factual cultural data assistant. Output strictly valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    headers = {"Authorization": f"Bearer {LITELLM_API_KEY}"}
    url = f"{LITELLM_BASE_URL.rstrip('/')}/chat/completions"

    r = requests.post(url, json=payload, headers=headers, timeout=45)
    r.raise_for_status()
    res = r.json()
    content = res["choices"][0]["message"]["content"]
    data = json.loads(content)
    return data.get("ratings", [])


def run_ratings_enrichment() -> None:
    with open(MUSEUMS_PATH, "r", encoding="utf-8") as f:
        museums_data = json.load(f)

    all_museums = museums_data.get("museums", [])
    valid_museums = [m for m in all_museums if m.get("slug")]

    existing_data = load_ratings()
    existing_map = {m["slug"]: m for m in existing_data.get("museums", []) if "slug" in m}

    to_process = [m for m in valid_museums if m["slug"] not in existing_map]
    logger.info(f"Total museums: {len(valid_museums)}, already enriched: {len(existing_map)}, to process: {len(to_process)}")

    if not to_process:
        logger.info("All museums already have ratings.")
        return

    batch_size = 20
    for i in range(0, len(to_process), batch_size):
        batch = to_process[i : i + batch_size]
        logger.info(f"Processing batch {i // batch_size + 1}/{(len(to_process) + batch_size - 1) // batch_size} ({len(batch)} museums)...")
        try:
            results = fetch_batch_ratings(batch)
            for res in results:
                slug = res.get("slug")
                if not slug:
                    continue
                orig_m = next((m for m in batch if m["slug"] == slug), None)
                record = {
                    "slug": slug,
                    "name": orig_m["name"] if orig_m else slug,
                    "rating": float(res["rating"]) if res.get("rating") is not None else None,
                    "reviews_count": int(res["reviews_count"]) if res.get("reviews_count") is not None else 0,
                    "source": "Google",
                }
                existing_map[slug] = record

            existing_data["museums"] = list(existing_map.values())
            save_ratings(existing_data)
        except Exception as e:
            logger.error(f"Batch failed: {e}")

    logger.info("Ratings enrichment complete!")


if __name__ == "__main__":
    run_ratings_enrichment()
