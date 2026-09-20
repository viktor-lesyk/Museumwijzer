from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    META_JSON_PATH,
    MUSEUMS_JSON_PATH,
    SOURCE_LIST_URL,
)
from .diff import compute_diff, update_changelog
from .fetch import Fetcher
from .geocode import Geocoder
from .normalise import (
    normalise_city,
    normalise_postcode,
    normalise_province,
    normalise_text,
)
from .overrides import apply_overrides, load_overrides
from .parse import parse_museum_story
from .validate import validate_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scraper.pipeline")


def merge_soft_deleted_museums(
    processed_museums: List[Dict[str, Any]],
    old_dataset: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge newly-scraped museums with previous dataset records.
    - Freshly-scraped museums get status='active' and consecutive_missing=0.
    - If a museum is missing for 1 scrape run, it retains status='active' with consecutive_missing=1.
    - If a museum is missing for 2+ consecutive runs, its status transitions to 'removed'.
    - If a museum was already 'removed', it remains 'removed'.
    - Returns sorted list (active first, then removed, alphabetically by slug).
    """
    result = list(processed_museums)
    for m in result:
        m.setdefault("status", "active")
        m["consecutive_missing"] = 0

    if old_dataset and "museums" in old_dataset:
        current_slugs = {m["slug"] for m in result if m.get("slug")}
        for om in old_dataset["museums"]:
            old_slug = om.get("slug")
            if not old_slug:
                continue
            if old_slug not in current_slugs:
                preserved_record = dict(om)
                consecutive = om.get("consecutive_missing", 0) + 1
                preserved_record["consecutive_missing"] = consecutive
                if consecutive >= 2 or om.get("status") == "removed":
                    preserved_record["status"] = "removed"
                    logger.warning(
                        f"Museum '{old_slug}' was absent in {consecutive} consecutive runs — "
                        f"marking as status='removed'. Data preserved."
                    )
                else:
                    preserved_record["status"] = "active"
                    logger.warning(
                        f"Museum '{old_slug}' was absent in this scrape (run 1/2) — "
                        f"retaining status='active' (consecutive_missing=1) until 2nd consecutive absence."
                    )
                result.append(preserved_record)

    result.sort(key=lambda m: (m.get("status", "active") == "removed", m.get("slug", "")))
    return result


class Pipeline:
    """End-to-end data pipeline: fetch -> parse -> normalise -> geocode -> overrides -> validate -> write."""

    def __init__(self, fetcher: Optional[Fetcher] = None, geocoder: Optional[Geocoder] = None):
        self.fetcher = fetcher or Fetcher()
        self.geocoder = geocoder or Geocoder()
        self.overrides = load_overrides()

    def run(self, max_items: Optional[int] = None) -> Dict[str, Any]:
        """Execute full data pipeline and return the run report."""
        run_start = datetime.now(timezone.utc)
        now_iso = run_start.isoformat()
        today_str = run_start.strftime("%Y-%m-%d")
        logger.info(f"Starting Museumwijzer data refresh on {today_str}...")

        # Load existing museums.json if available
        old_dataset: Optional[Dict[str, Any]] = None
        if MUSEUMS_JSON_PATH.exists():
            try:
                with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
                    old_dataset = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load previous museums.json: {e}")

        # 1. Fetch list page
        logger.info("Fetching list page HTML and extracting __NEXT_DATA__...")
        build_id, next_data = self.fetcher.fetch_list_page()
        logger.info(f"Discovered active Next.js buildId: {build_id}")

        story = next_data.get("props", {}).get("pageProps", {}).get("story", {})
        body = story.get("content", {}).get("body", [])
        raw_articles: List[Dict[str, Any]] = []

        for block in body:
            for ca in block.get("contentAreas", []):
                for comp in ca.get("content", []):
                    if comp.get("component") in ("all-articles", "article-overview"):
                        raw_articles = comp.get("articles", [])
                        break

        if not raw_articles:
            raise ValueError("No articles found in list page story content")

        total_embedded = len(raw_articles)
        logger.info(f"Found {total_embedded} embedded articles in list page payload")

        # 2. Reconcile: exclude unpublished, drafts, or ended items
        active_articles: List[Dict[str, Any]] = []
        excluded_articles: List[Dict[str, Any]] = []

        for a in raw_articles:
            is_startpage = a.get("is_startpage", False)
            published_at = a.get("published_at")
            if is_startpage or not published_at:
                excluded_articles.append({"slug": a.get("slug"), "reason": "unpublished or startpage"})
            else:
                active_articles.append(a)

        logger.info(
            f"Reconciliation: {len(active_articles)} active public museums, "
            f"{len(excluded_articles)} excluded"
        )

        if max_items:
            logger.info(f"Limiting run to first {max_items} items (testing mode)")
            active_articles = active_articles[:max_items]

        # 3. Process each museum
        processed_museums: List[Dict[str, Any]] = []
        old_first_seen: Dict[str, str] = {}
        if old_dataset and "museums" in old_dataset:
            for om in old_dataset["museums"]:
                if "slug" in om and "first_seen" in om:
                    old_first_seen[om["slug"]] = om["first_seen"]

        sanity_issues: List[Dict[str, Any]] = []
        override_matches: List[str] = []

        for idx, article in enumerate(active_articles):
            slug = article["slug"]
            logger.info(f"[{idx+1}/{len(active_articles)}] Processing '{slug}'...")

            # Fetch detail story
            detail_story = self.fetcher.fetch_detail_story(slug, build_id)
            story_to_parse = detail_story if detail_story else article

            # Parse with field whitelisting
            parsed_raw = parse_museum_story(story_to_parse)

            # Normalise
            name = normalise_text(parsed_raw.name) or parsed_raw.name
            province = normalise_province(parsed_raw.province) or parsed_raw.province
            street = normalise_text(parsed_raw.street)
            postcode = normalise_postcode(parsed_raw.postcode)
            raw_city = normalise_text(parsed_raw.city)

            # Initial record
            first_seen = old_first_seen.get(slug, today_str)

            initial_record = {
                "slug": slug,
                "name": name,
                "province": province,
                "city": raw_city,
                "municipality": None,
                "address": {
                    "street": street or "",
                    "postcode": postcode or "",
                    "city": raw_city or "",
                },
                "lat": None,
                "lon": None,
                "official_url": parsed_raw.official_url,
                "official_urls": parsed_raw.official_urls,
                "museum_website": parsed_raw.museum_website,
                "source_date_raw": parsed_raw.source_date_raw,
                "first_seen": first_seen,
                "programmes": ["welkom-in-het-museum"],
            }

            # Apply manual overrides (e.g. source typo corrections)
            overridden_record, source_matched = apply_overrides(initial_record, self.overrides)
            if source_matched:
                override_matches.append(slug)

            addr = overridden_record.get("address", {})
            curr_street = addr.get("street")
            curr_postcode = addr.get("postcode")
            curr_city = addr.get("city") or overridden_record.get("city")

            # Geocode via PDOK Locatieserver
            geo_res = self.geocoder.geocode_museum(
                slug=slug,
                name=overridden_record.get("name", name),
                street=curr_street,
                postcode=curr_postcode,
                city=curr_city,
            )

            source_or_override_city = normalise_city(curr_city)
            pdok_woonplaats = normalise_text(geo_res.woonplaats)
            final_municipality = normalise_text(geo_res.municipality)
            display_city = source_or_override_city or normalise_city(pdok_woonplaats)

            museum_record = dict(overridden_record)
            # Display source/common city name (e.g. "Den Haag", "Den Bosch"), fallback to PDOK if empty
            museum_record["city"] = display_city
            museum_record["pdok_woonplaats"] = pdok_woonplaats
            museum_record["municipality"] = final_municipality
            museum_record["address"]["city"] = display_city or ""
            museum_record["lat"] = geo_res.lat
            museum_record["lon"] = geo_res.lon

            # Sanity check against PDOK results
            active_province = overridden_record.get("province", province)
            sanity = self.geocoder.check_sanity(
                slug=slug,
                lat=geo_res.lat,
                lon=geo_res.lon,
                source_province=active_province,
                pdok_province=geo_res.province,
                source_city=curr_city,
                pdok_woonplaats=geo_res.woonplaats,
            )
            if sanity.get("has_issues"):
                sanity_issues.append(sanity)

            processed_museums.append(museum_record)

        # Soft-delete merge: handles 2-consecutive-runs requirement and sorting
        processed_museums = merge_soft_deleted_museums(processed_museums, old_dataset)


        # 4. Save geocode cache
        self.geocoder.save_cache()

        # 5. Validate dataset against §8.2 rules
        is_valid, validation_errors = validate_dataset(processed_museums, old_dataset)
        if not is_valid:
            logger.error("Dataset validation failed! Blocking deployment of new data.")
            for err in validation_errors:
                logger.error(f"  Validation error: {err}")
            # Do NOT update museums.json or meta.json
            raise ValueError(f"Dataset validation failed with {len(validation_errors)} error(s): {validation_errors}")

        logger.info("Dataset validation PASSED successfully.")

        # 6. Diff and changelog
        diff_result = compute_diff(processed_museums, old_dataset)

        # 7. Diff hygiene: only overwrite museums.json if museum records changed
        new_content_json = json.dumps(
            {
                "source": {
                    "name": "Welkom in het Museum",
                    "url": SOURCE_LIST_URL,
                },
                "museums": processed_museums,
            },
            indent=2,
            ensure_ascii=False,
        )

        should_write_museums = True
        if MUSEUMS_JSON_PATH.exists():
            try:
                with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
                    existing_text = f.read()
                if existing_text.strip() == new_content_json.strip():
                    should_write_museums = False
                    logger.info("museums.json content is unchanged. Skipping file write to preserve clean git diff.")
            except Exception:
                pass

        if should_write_museums:
            MUSEUMS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(MUSEUMS_JSON_PATH, "w", encoding="utf-8") as f:
                f.write(new_content_json + "\n")
            logger.info(f"Wrote {len(processed_museums)} museums to {MUSEUMS_JSON_PATH}")

        # Update changelog only if there are added/removed items or initial run
        if diff_result["added"] or diff_result["removed"] or not old_dataset:
            update_changelog(diff_result, len(processed_museums))

        # 8. Write meta.json with last_checked
        meta_data = {
            "last_checked": now_iso,
            "build_id": build_id,
            "total_count": len(processed_museums),
        }
        META_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(META_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"Updated {META_JSON_PATH} with last_checked: {now_iso}")

        # Missing fields report
        missing_city = [m["slug"] for m in processed_museums if not m.get("city")]
        missing_coords = [m["slug"] for m in processed_museums if m.get("lat") is None or m.get("lon") is None]

        report = {
            "run_timestamp": now_iso,
            "build_id": build_id,
            "total_embedded": total_embedded,
            "reconciliation": {
                "active_count": len(active_articles),
                "excluded_count": len(excluded_articles),
                "excluded_items": excluded_articles,
            },
            "processed_count": len(processed_museums),
            "validation": {
                "is_valid": is_valid,
                "errors": validation_errors,
            },
            "diff": {
                "added_count": len(diff_result["added"]),
                "removed_count": len(diff_result["removed"]),
                "retained_count": len(diff_result["retained"]),
                "added": diff_result["added"],
                "removed": diff_result["removed"],
            },
            "geocoding_completeness": {
                "complete_count": len(processed_museums) - len(missing_coords),
                "total_count": len(processed_museums),
                "percentage": round((len(processed_museums) - len(missing_coords)) / len(processed_museums) * 100.0, 1),
                "missing_city": missing_city,
                "missing_coords": missing_coords,
            },
            "sanity_checks": {
                "issues_count": len(sanity_issues),
                "issues": sanity_issues,
            },
            "overrides_status": {
                "source_matches_count": len(override_matches),
                "source_matches": override_matches,
            },
        }

        return report


if __name__ == "__main__":
    max_items = int(sys.argv[1]) if len(sys.argv) > 1 else None
    pipeline = Pipeline()
    report = pipeline.run(max_items=max_items)
    print("\n=== RUN REPORT ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
