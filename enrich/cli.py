"""Command-line interface for the Museumwijzer Enrichment framework."""

import argparse
from collections import Counter
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Load .env if present
def load_env_file():
    env_path = Path(__file__).resolve().parent.parent / ".env"
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

load_env_file()

from enrich.audit_identity import run_identity_audit
from enrich.identity import run_identity_job
from enrich.jobs.base import JobDefinition, list_available_jobs
from enrich.ops.audit import run_spot_check_audit
from enrich.ops.proposals import load_proposals
from enrich.ops.storage import load_json, record_results
from enrich.runner.orchestrator import EnrichmentOrchestrator

logger = logging.getLogger("enrich.cli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSEUMS_JSON_PATH = REPO_ROOT / "data" / "museums.json"
PRICES_PATH = REPO_ROOT / "data" / "enrichment" / "prices.json"
NEEDS_REVIEW_PATH = REPO_ROOT / "data" / "enrichment" / "needs_review.json"


def load_target_museums(
    slug_filter: Optional[str] = None,
    only_stale: bool = False,
    resume: bool = False,
    limit: Optional[int] = None,
    job: Optional[JobDefinition] = None,
) -> List[dict]:
    with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    museums = [m for m in data.get("museums", []) if m.get("status", "active") != "removed"]

    if slug_filter:
        museums = [m for m in museums if m.get("slug") == slug_filter]
        if not museums:
            raise ValueError(f"Slug '{slug_filter}' not found in active museums.")

    existing_prices = load_json(PRICES_PATH).get("museums", [])
    existing_by_slug = {m["slug"]: m for m in existing_prices if "slug" in m}

    if resume:
        museums = [m for m in museums if m["slug"] not in existing_by_slug]

    if only_stale and job:
        filtered = []
        for m in museums:
            rec = existing_by_slug.get(m["slug"])
            if not rec:
                filtered.append(m)
            else:
                filtered.append(m)
        museums = filtered

    if limit and limit > 0:
        museums = museums[:limit]

    return museums


def print_detailed_report():
    """Print structured breakdown of accepted records and needs_review issues."""
    prices_data = load_json(PRICES_PATH)
    needs_data = load_json(NEEDS_REVIEW_PATH)

    accepted_list = prices_data.get("museums", [])
    review_list = needs_data.get("records", [])

    print("\n" + "=" * 65)
    print("=== ENRICHMENT STATUS REPORT ===")
    print("=" * 65)

    # 1. Accepted breakdown
    paid_records = []
    free_records = []
    closed_records = []
    other_accepted = []

    for m in accepted_list:
        p = m.get("price", {})
        status = p.get("status", "unknown")
        if status == "paid" or (p.get("primary_adult_eur") or p.get("adult_eur")):
            paid_records.append(m)
        elif status == "free" or (p.get("primary_adult_eur") == 0.0 or p.get("adult_eur") == 0.0):
            free_records.append(m)
        elif status == "closed":
            closed_records.append(m)
        else:
            other_accepted.append(m)

    print(f"\n[✓] TOTAL ACCEPTED: {len(accepted_list)}")
    if paid_records:
        prices = [
            (m["price"].get("primary_adult_eur") if m["price"].get("primary_adult_eur") is not None else m["price"].get("adult_eur", 0.0))
            for m in paid_records
        ]
        prices = [pr for pr in prices if pr is not None]
        avg_price = sum(prices) / len(prices) if prices else 0.0
        print(f"  • Paid Admission:     {len(paid_records)} museums (avg €{avg_price:.2f}, min €{min(prices):.2f}, max €{max(prices):.2f})")
    print(f"  • Free Admission:     {len(free_records)} museums")
    if free_records:
        print(f"    -> {', '.join(m['slug'] for m in free_records)}")
    print(f"  • Temporarily Closed: {len(closed_records)} museums")
    if closed_records:
        print(f"    -> {', '.join(m['slug'] for m in closed_records)}")
    if other_accepted:
        print(f"  • Other / Protected:  {len(other_accepted)} museums")

    # 2. Needs Review Breakdown
    print(f"\n[✗] TOTAL NEEDS REVIEW: {len(review_list)}")
    reason_categories = Counter()

    for r in review_list:
        failures = r.get("gate_failures", [])
        v_verdict = r.get("verifier_verdict")

        categorized = False
        for f in failures:
            f_lower = f.lower()
            if "not found verbatim" in f_lower:
                reason_categories["literal_quote_mismatch"] += 1
                categorized = True
            elif "exceeds 15 words limit" in f_lower:
                reason_categories["quote_length_exceeded"] += 1
                categorized = True
            elif "combo" in f_lower or "duo" in f_lower:
                reason_categories["combo_ticket_rejected"] += 1
                categorized = True
            elif "yoy change" in f_lower:
                reason_categories["yoy_price_jump"] += 1
                categorized = True
            elif "range" in f_lower:
                reason_categories["range_out_of_bounds"] += 1
                categorized = True
            elif "domain" in f_lower:
                reason_categories["domain_mismatch"] += 1
                categorized = True
            elif "identity" in f_lower:
                reason_categories["identity_mismatch"] += 1
                categorized = True

        if not categorized:
            if v_verdict == "reject":
                reason_categories["verifier_rejected"] += 1
            elif r.get("price", {}).get("status") == "blocked_by_bot_protection":
                reason_categories["bot_protection"] += 1
            else:
                reason_categories["unspecified_review"] += 1

    for cat, cnt in reason_categories.most_common():
        print(f"  • {cat:<24}: {cnt}")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m enrich",
        description="Museumwijzer verifying agent enrichment framework",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. run command
    run_parser = subparsers.add_parser("run", help="Run enrichment job on museums")
    run_parser.add_argument("--job", default="price_adult", help="Job definition name (default: price_adult)")
    run_parser.add_argument("--slug", default=None, help="Target a specific museum slug")
    run_parser.add_argument("--mode", choices=["simple", "agentic", "fallback"], default="simple", help="Research mode (default: simple)")
    run_parser.add_argument("--only-stale", action="store_true", help="Only process records requiring refresh")
    run_parser.add_argument("--resume", action="store_true", help="Skip museums already present in prices.json")
    run_parser.add_argument("--limit", type=int, default=None, help="Limit number of museums to process")
    run_parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL")
    run_parser.add_argument("--api-key", default=None, help="API key")
    run_parser.add_argument("--extractor-model", default=None, help="Model for extraction phase")
    run_parser.add_argument("--verifier-model", default=None, help="Model for verification phase (must be different family)")
    run_parser.add_argument("--escalation-model", default=None, help="Stronger model for retry escalation ladder (must be different family from verifier)")
    run_parser.add_argument("--allow-same-family", action="store_true", help="Bypass family check (testing only)")

    # 2. audit-identity command
    audit_id_parser = subparsers.add_parser("audit-identity", help="Audit museum websites for identity/title mismatches")
    audit_id_parser.add_argument("--limit", type=int, default=None, help="Limit number of museums to audit")

    # 3. audit command
    audit_parser = subparsers.add_parser("audit", help="Spot check accepted records")
    audit_parser.add_argument("--sample", type=int, default=10, help="Number of random accepted records to inspect")
    audit_parser.add_argument("--paid-only", action="store_true", help="Only show accepted paid admission rows")

    # 4. report command
    report_parser = subparsers.add_parser("report", help="Print detailed report of accepted vs needs_review records")

    # 5. proposals command
    proposals_parser = subparsers.add_parser("proposals", help="List pending identity and address proposals from data/enrichment/proposals.json")

    # 6. recheck command (MANUAL ONLY: strictly forbidden in cron/systemd/CI)
    recheck_parser = subparsers.add_parser(
        "recheck",
        help="Manually recheck prices (direct source_url validation, dual-model comparison, delta reporting)",
    )
    recheck_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run without modifying prices.json or needs_review.json (default: True)",
    )
    recheck_parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Apply and persist changes to prices.json and needs_review.json",
    )
    recheck_parser.add_argument(
        "--write",
        dest="dry_run",
        action="store_false",
        help="Alias for --apply",
    )
    recheck_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of museums to recheck",
    )
    recheck_parser.add_argument(
        "--slugs",
        default=None,
        help="Comma-separated list of specific museum slugs to recheck",
    )
    recheck_parser.add_argument(
        "--extractor-model",
        default=None,
        help="Model for extraction phase (LiteLLM proxy)",
    )
    recheck_parser.add_argument(
        "--base-url",
        default=None,
        help="OpenRouter Base URL",
    )
    recheck_parser.add_argument(
        "--api-key",
        default=None,
        help="API key",
    )

    args = parser.parse_args()

    if args.command == "recheck":
        from enrich.recheck import run_recheck
        slug_list = [s.strip() for s in args.slugs.split(",") if s.strip()] if args.slugs else None
        run_recheck(
            dry_run=args.dry_run,
            limit=args.limit,
            slugs=slug_list,
            model=args.extractor_model,
            base_url=args.base_url,
            api_key=args.api_key,
        )
        return

    if args.command == "proposals":
        proposals = load_proposals()
        print("\n" + "=" * 65)
        print("=== PENDING ENRICHMENT PROPOSALS (data/enrichment/proposals.json) ===")
        print(f"Total proposals pending bulk review: {len(proposals)}")
        print("=" * 65)
        if not proposals:
            print("No pending proposals found.")
        for p in proposals:
            print(f"\n• Slug:       {p.get('slug')} [{p.get('field')}]")
            print(f"  Proposed:   {p.get('proposed_value')}")
            print(f"  Evidence:   {p.get('evidence_url')}")
            print(f"  Quote:      {p.get('quote')}")
            print(f"  Confidence: {p.get('confidence')} | Date: {p.get('checked_on')}")
            print(f"  Reason:     {p.get('reason')}")
        print("=" * 65 + "\n")
        return

    if args.command == "report":
        print_detailed_report()
        return

    if args.command == "audit-identity":
        run_identity_audit(limit=args.limit)
        return

    if args.command == "audit":
        run_spot_check_audit(sample_size=args.sample, paid_only=args.paid_only)
        return

    if args.command == "run":
        if args.job in ("website", "address_check"):
            run_identity_job(job_name=args.job, slug=args.slug, limit=args.limit)
            return

        if args.mode == "simple" and args.job == "price_adult":
            from enrich.simple_pipeline import run_simple_pipeline
            museums_path = REPO_ROOT / "data" / "museums.json"
            with open(museums_path, "r", encoding="utf-8") as f:
                all_museums = json.load(f)["museums"]

            if args.slug:
                target_museums = [m for m in all_museums if m.get("slug") == args.slug]
            else:
                target_museums = all_museums

            base_url = args.base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
            extractor = args.extractor_model or os.environ.get("LITELLM_FREE_LITE_MODEL", "free-lite")

            run_simple_pipeline(
                museums=target_museums,
                model=extractor,
                base_url=base_url,
                api_key=api_key,
                limit=args.limit,
                resume=args.resume,
            )
            return

        job = JobDefinition.load(args.job)
        base_url = args.base_url or os.environ.get("ENRICH_BASE_URL", "http://localhost:11434/v1")
        api_key = args.api_key or os.environ.get("ENRICH_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        extractor = args.extractor_model or os.environ.get("ENRICH_EXTRACTOR_MODEL", "qwen3.5:9b")
        verifier = args.verifier_model or os.environ.get("ENRICH_VERIFIER_MODEL", "deepseek-r1:1.5b")
        escalation = args.escalation_model or os.environ.get("ENRICH_ESCALATION_MODEL")

        print("=" * 65)
        print("=== MUSEUMWIJZER ENRICHMENT RUNNER ===")
        print(f"Job:              {job.title} ({job.field})")
        print(f"Mode:             {args.mode}")
        print(f"Base URL:         {base_url}")
        print(f"Extractor Model:  {extractor}")
        print(f"Verifier Model:   {verifier}")
        if escalation:
            print(f"Escalation Model: {escalation}")
        print("=" * 65)

        orchestrator = EnrichmentOrchestrator(
            base_url=base_url,
            api_key=api_key,
            extractor_model=extractor,
            verifier_model=verifier,
            escalation_model=escalation,
            job=job,
            mode=args.mode,
            force_different_families=not args.allow_same_family,
        )

        museums = load_target_museums(
            slug_filter=args.slug,
            only_stale=args.only_stale,
            resume=args.resume,
            limit=args.limit,
            job=job,
        )

        print(f"Loaded {len(museums)} museum(s) to process.")
        results = []
        for i, m in enumerate(museums, 1):
            print(f"\n[{i}/{len(museums)}] Processing {m['slug']}...")
            res = orchestrator.process_museum(m)
            results.append(res)
            status_symbol = "✓ ACCEPTED" if res["is_accepted"] else "✗ NEEDS_REVIEW"
            print(f"  -> Result: {status_symbol} (tool calls: {res['tool_calls']}, time: {res['time_seconds']}s)")
            if not res["is_accepted"]:
                if res.get("gate_failures"):
                    print(f"     Gate failures: {res['gate_failures']}")
                if res.get("verifier_verdict") != "confirm":
                    print(f"     Verifier verdict: {res.get('verifier_verdict')} ({res.get('verifier_justification')})")

        acc_count, rev_count = record_results(results)
        print_detailed_report()


if __name__ == "__main__":
    main()
