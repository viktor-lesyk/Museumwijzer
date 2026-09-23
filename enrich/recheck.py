"""Manual-only price recheck command for Museumwijzer.

Policy:
- This command is strictly for MANUAL execution by an engineer/operator.
- NEVER add this script or command to cron, systemd timers, or GitHub Actions.
- Uses free-tier models only (LiteLLM proxy 'free-lite' + OpenRouter free model).
- Tracks Tavily search quota (1,000 monthly credits) and minimizes searches by verifying
  stored source_urls directly before falling back to search.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from enrich.fetch import PoliteFetcher
from enrich.simple_pipeline import (
    SearchQuotaGuard,
    extract_domain,
    extract_html_title,
    is_ticketing_subdomain,
    process_museum_dual_model,
    save_dual_model_results,
    validate_free_tier_configuration,
)
from enrich.tools.fetch_page import sanitize_html_for_agent

logger = logging.getLogger("enrich.recheck")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "enrichment"
MUSEUMS_JSON_PATH = REPO_ROOT / "data" / "museums.json"
PRICES_JSON_PATH = DATA_DIR / "prices.json"
NEEDS_REVIEW_PATH = DATA_DIR / "needs_review.json"

PRICE_KEYWORDS_PATTERN = re.compile(
    r"€|\beur\b|\beuro\b|toegang|entree|tickets?|prijs|prijzen|tarief|tarieven|gratis|kosten|volwassenen",
    re.IGNORECASE,
)


def verify_stored_source_url(
    museum: Dict[str, Any],
    source_url: str,
    fetcher: PoliteFetcher,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Verify whether stored source_url still resolves and contains pricing information.

    Checks:
    1. Valid HTTP/HTTPS scheme and hostname.
    2. Respects robots.txt.
    3. Resolves with HTTP 200.
    4. Did not redirect away from museum domain or ticketing subdomain.
    5. Did not redirect from a specific subpage to the root domain ('/').
    6. Content still contains pricing-related keywords or currency symbols.

    Returns:
      (is_valid, final_url, html_content, failure_reason)
    """
    if not source_url or not isinstance(source_url, str):
        return False, None, None, "Missing or invalid source_url"

    clean_url = source_url.strip()
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        return False, None, None, f"Invalid URL scheme: {clean_url}"

    website = museum.get("museum_website") or clean_url
    base_domain = extract_domain(website)

    # 1. Robots check
    allowed, robot_reason = fetcher.robots.check_access(clean_url)
    if not allowed:
        return False, None, None, f"Disallowed by robots.txt: {robot_reason}"

    # 2. Rate limit
    fetcher._wait_for_rate_limit(clean_url)

    # 3. HTTP GET (fresh request)
    try:
        resp = fetcher.session.get(clean_url, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return False, None, None, f"HTTP {resp.status_code}"

        final_url = resp.url
        final_domain = extract_domain(final_url)

        # 4. Domain provenance check
        if base_domain and not is_ticketing_subdomain(final_url, base_domain):
            return False, final_url, None, f"Redirected to external domain: {final_domain} (expected {base_domain})"

        # 5. Check if redirected from a specific subpage to root homepage
        orig_parsed = urlparse(clean_url)
        final_parsed = urlparse(final_url)
        orig_path = orig_parsed.path.rstrip("/")
        final_path = final_parsed.path.rstrip("/")

        if len(orig_path) > 1 and final_path in ("", "/"):
            return False, final_url, None, "Redirected from specific pricing page to homepage root"

        html_text = resp.text
        sanitized = sanitize_html_for_agent(html_text, final_url).get("text", "")

        # 6. Pricing content check
        if not PRICE_KEYWORDS_PATTERN.search(sanitized):
            return False, final_url, None, "Page no longer contains pricing keywords or € currency symbol"

        return True, final_url, html_text, None

    except Exception as e:
        return False, None, None, f"Network/fetch exception: {e}"


def run_recheck(
    dry_run: bool = True,
    limit: Optional[int] = None,
    slugs: Optional[List[str]] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute manual-only recheck across existing enrichment records.
    """
    # 1. Strict safety guardrails
    litellm_base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    litellm_api_key = os.environ.get("LITELLM_API_KEY", "sk-localproxy")
    litellm_model = model or os.environ.get("LITELLM_FREE_LITE_MODEL", "free-lite")

    openrouter_base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    openrouter_model = os.environ.get("OPENROUTER_FREE_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

    validate_free_tier_configuration(
        litellm_model=litellm_model,
        openrouter_model=openrouter_model,
        disallow_brave=True,
    )

    # 2. Load data
    with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
        all_museums = [m for m in json.load(f).get("museums", []) if m.get("status", "active") != "removed"]

    museums_by_slug = {m["slug"]: m for m in all_museums if "slug" in m}

    existing_prices: Dict[str, Dict[str, Any]] = {}
    if PRICES_JSON_PATH.exists():
        try:
            with open(PRICES_JSON_PATH, "r", encoding="utf-8") as f:
                existing_prices = {m["slug"]: m for m in json.load(f).get("museums", []) if "slug" in m}
        except Exception:
            pass

    existing_needs: Dict[str, Dict[str, Any]] = {}
    if NEEDS_REVIEW_PATH.exists():
        try:
            with open(NEEDS_REVIEW_PATH, "r", encoding="utf-8") as f:
                existing_needs = {m["slug"]: m for m in json.load(f).get("records", []) if "slug" in m}
        except Exception:
            pass

    # 3. Filter targets
    if slugs:
        target_museums = [museums_by_slug[s] for s in slugs if s in museums_by_slug]
    else:
        target_museums = all_museums

    if limit and limit > 0:
        target_museums = target_museums[:limit]

    fetcher = PoliteFetcher()
    quota_guard = SearchQuotaGuard()
    initial_quota = quota_guard.get_used_count()

    print("\n" + "=" * 78)
    print("=== MUSEUMWIJZER ENRICHMENT MANUAL RECHECK ===")
    print("POLICY: MANUAL ONLY (Strictly forbidden in automated cron/CI)")
    print(f"MODE:                 {'[DRY RUN - No files will be modified]' if dry_run else '[APPLY - Updating JSON on disk]'}")
    print(f"Target Museums:       {len(target_museums)}")
    print(f"Model 1 (Primary):    {litellm_model} @ {litellm_base_url}")
    print(f"Model 2 (Opinion):    {openrouter_model} @ {openrouter_base_url}")
    print(f"Search Provider:      Tavily (Current monthly quota: {initial_quota}/{quota_guard.max_monthly_searches})")
    print("=" * 78)

    results: List[Dict[str, Any]] = []
    deltas: List[Dict[str, Any]] = []
    direct_rechecks = 0
    search_fallbacks = 0
    start_time = time.time()

    for idx, museum in enumerate(target_museums, 1):
        slug = museum.get("slug", "")
        name = museum.get("name", slug)
        website = museum.get("museum_website")
        stored_price_rec = existing_prices.get(slug)
        stored_needs_rec = existing_needs.get(slug)

        prev_status = stored_price_rec.get("price", {}).get("status") if stored_price_rec else (
            stored_needs_rec.get("disagreement_type", "needs_review") if stored_needs_rec else "unindexed"
        )
        prev_eur = stored_price_rec.get("price", {}).get("primary_adult_eur") if stored_price_rec else None

        print(f"\n[{idx}/{len(target_museums)}] Rechecking {slug} ({name})...")
        stored_url = stored_price_rec.get("price", {}).get("source_url") if stored_price_rec else None

        override_pages = None
        method_used = "search"

        # Check if we can directly re-verify stored source_url without search
        if stored_price_rec and prev_status in ("paid", "free", "closed") and stored_url:
            print(f"  → Testing stored source_url: {stored_url}")
            is_valid, final_url, html_content, fail_reason = verify_stored_source_url(
                museum=museum,
                source_url=stored_url,
                fetcher=fetcher,
            )
            if is_valid and html_content:
                print(f"  ✓ URL still valid (HTTP 200, pricing terms present). Skipping search.")
                title = extract_html_title(html_content)
                sanitized = sanitize_html_for_agent(html_content, final_url).get("text", "")
                pages = [{
                    "url": final_url,
                    "title": title or name,
                    "text": sanitized,
                    "source": "stored_source_url",
                }]

                # Optionally include homepage for identity confirmation if different
                if website and website != final_url:
                    ok_hp, hp_html, _ = fetcher.fetch(website)
                    if ok_hp and hp_html:
                        pages.append({
                            "url": website,
                            "title": extract_html_title(hp_html) or "Home",
                            "text": sanitize_html_for_agent(hp_html, website).get("text", "")[:4000],
                            "source": "homepage",
                        })

                override_pages = pages
                method_used = "direct_url"
                direct_rechecks += 1
            else:
                print(f"  ⚠ Stored URL invalid ({fail_reason}). Falling back to domain search...")
                search_fallbacks += 1
        else:
            print(f"  → Museum in {prev_status}. Running full search flow...")
            search_fallbacks += 1

        # Run dual-model evaluation
        res = process_museum_dual_model(
            museum=museum,
            fetcher=fetcher,
            quota_guard=quota_guard,
            litellm_base_url=litellm_base_url,
            litellm_api_key=litellm_api_key,
            litellm_model=litellm_model,
            openrouter_base_url=openrouter_base_url,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
            override_pages=override_pages,
        )
        results.append(res)

        new_price_obj = res.get("price", {})
        new_status = new_price_obj.get("status")
        new_eur = new_price_obj.get("primary_adult_eur")
        is_accepted = res.get("is_accepted", False)

        # Categorize Delta
        delta_type = "unchanged"
        delta_desc = ""

        if stored_price_rec:
            if is_accepted:
                if new_status == prev_status and (
                    (new_eur is None and prev_eur is None) or
                    (new_eur is not None and prev_eur is not None and abs(float(new_eur) - float(prev_eur)) < 0.01)
                ):
                    delta_type = "unchanged"
                    delta_desc = f"€{new_eur:.2f}" if new_eur is not None else new_status
                elif new_status == "paid" and prev_status == "paid" and new_eur != prev_eur:
                    delta_type = "price_changed"
                    delta_desc = f"€{prev_eur:.2f} → €{new_eur:.2f}"
                else:
                    delta_type = "status_changed"
                    delta_desc = f"{prev_status} (prev €{prev_eur}) → {new_status} (new €{new_eur})"
            else:
                delta_type = "became_unavailable"
                delta_desc = f"Was accepted ({prev_status} €{prev_eur}), now {res.get('disagreement_type')}"
        else:
            if is_accepted:
                delta_type = "newly_resolved"
                delta_desc = f"Was {prev_status} → now {new_status} €{new_eur}"
            else:
                delta_type = "still_unresolved"
                delta_desc = f"Still needs review: {res.get('disagreement_type')}"

        deltas.append({
            "slug": slug,
            "name": name,
            "delta_type": delta_type,
            "delta_desc": delta_desc,
            "method_used": method_used,
            "prev_status": prev_status,
            "prev_eur": prev_eur,
            "new_status": new_status,
            "new_eur": new_eur,
            "source_url": new_price_obj.get("source_url"),
            "quote": new_price_obj.get("quote"),
            "reasoning_summary": new_price_obj.get("reasoning_summary"),
        })

        icon_map = {
            "unchanged": "⏸ UNCHANGED",
            "price_changed": "📈 PRICE CHANGED",
            "status_changed": "🔄 STATUS CHANGED",
            "newly_resolved": "✨ NEWLY RESOLVED",
            "became_unavailable": "⚠️ BECAME UNAVAILABLE",
            "still_unresolved": "❌ STILL UNRESOLVED",
        }
        print(f"  → Result: {icon_map.get(delta_type, delta_type)} [{delta_desc}] ({res['time_seconds']}s, via {method_used})")
        time.sleep(0.5)

    searches_used_this_run = quota_guard.get_used_count() - initial_quota
    total_time = round(time.time() - start_time, 2)

    # 4. Save results if not dry-run
    if not dry_run:
        acc_saved, rev_saved = save_dual_model_results(results)
        print(f"\n[APPLIED] Successfully recorded {acc_saved} accepted and {rev_saved} needs_review records.")
    else:
        print("\n[DRY RUN] No files modified on disk.")

    # 5. Formulate summary & print report
    summary_counts: Dict[str, int] = {}
    for d in deltas:
        summary_counts[d["delta_type"]] = summary_counts.get(d["delta_type"], 0) + 1

    print("\n" + "=" * 78)
    print("=== ENRICHMENT RECHECK INFORMATIONAL REPORT ===")
    print(f"Execution Mode:       {'DRY RUN (no files modified)' if dry_run else 'APPLIED'}")
    print(f"Total Rechecked:      {len(deltas)}")
    print(f"  • Unchanged:        {summary_counts.get('unchanged', 0)}")
    print(f"  • Price Changed:    {summary_counts.get('price_changed', 0)}")
    print(f"  • Status Changed:   {summary_counts.get('status_changed', 0)}")
    print(f"  • Newly Resolved:   {summary_counts.get('newly_resolved', 0)}")
    print(f"  • Unavailable:      {summary_counts.get('became_unavailable', 0)}")
    print(f"  • Still Unresolved: {summary_counts.get('still_unresolved', 0)}")
    print(f"Direct URL Hits:      {direct_rechecks} (no search quota used)")
    print(f"Search Fallbacks:     {search_fallbacks}")
    print(f"Tavily Searches Used: {searches_used_this_run} (Month total: {quota_guard.get_used_count()}/{quota_guard.max_monthly_searches})")
    print(f"Total Elapsed Time:   {total_time}s")
    print("=" * 78)

    # Detailed listings
    changed = [d for d in deltas if d["delta_type"] in ("price_changed", "status_changed")]
    if changed:
        print("\n📈 CHANGED RECORDS:")
        for d in changed:
            print(f"  • {d['slug']} ({d['name']}):")
            print(f"    {d['delta_desc']}")
            print(f"    URL:   {d['source_url']}")
            print(f"    Quote: {d['quote']}")
            print(f"    Note:  {d['reasoning_summary']}")

    newly_res = [d for d in deltas if d["delta_type"] == "newly_resolved"]
    if newly_res:
        print("\n✨ NEWLY RESOLVED RECORDS:")
        for d in newly_res:
            print(f"  • {d['slug']} ({d['name']}): {d['delta_desc']}")
            print(f"    URL:   {d['source_url']}")
            print(f"    Quote: {d['quote']}")

    unavail = [d for d in deltas if d["delta_type"] == "became_unavailable"]
    if unavail:
        print("\n⚠️ BECAME UNAVAILABLE / NEEDS REVIEW:")
        for d in unavail:
            print(f"  • {d['slug']} ({d['name']}): {d['delta_desc']}")

    print("\n" + "=" * 78 + "\n")

    return {
        "dry_run": dry_run,
        "total_checked": len(deltas),
        "counts": summary_counts,
        "direct_rechecks": direct_rechecks,
        "search_fallbacks": search_fallbacks,
        "searches_used_run": searches_used_this_run,
        "total_time_seconds": total_time,
        "deltas": deltas,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Manual price recheck runner (MANUAL ONLY: do not add to cron/systemd/CI)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run without modifying prices.json or needs_review.json (default: True)",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Apply and persist changes to prices.json and needs_review.json",
    )
    parser.add_argument(
        "--write",
        dest="dry_run",
        action="store_false",
        help="Alias for --apply",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of museums to recheck",
    )
    parser.add_argument(
        "--slugs",
        default=None,
        help="Comma-separated list of specific museum slugs to recheck",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Primary extractor model (LiteLLM proxy)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenRouter Base URL",
    )
    args = parser.parse_args()

    slug_list = [s.strip() for s in args.slugs.split(",") if s.strip()] if args.slugs else None

    run_recheck(
        dry_run=args.dry_run,
        limit=args.limit,
        slugs=slug_list,
        model=args.model,
        base_url=args.base_url,
    )


if __name__ == "__main__":
    main()
