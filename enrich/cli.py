"""Command-line interface for the Museumwijzer Enrichment framework."""

import argparse
import json
import logging
import os
from pathlib import Path
import sys
from typing import List, Optional

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
from enrich.jobs.base import JobDefinition, list_available_jobs
from enrich.ops.audit import run_spot_check_audit
from enrich.ops.storage import load_json, record_results
from enrich.runner.orchestrator import EnrichmentOrchestrator

logger = logging.getLogger("enrich.cli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSEUMS_JSON_PATH = REPO_ROOT / "data" / "museums.json"
PRICES_PATH = REPO_ROOT / "data" / "enrichment" / "prices.json"


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
        # Filter museums whose checked_on date is older than refresh_interval_days
        # (For pilot, missing is considered stale)
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
    run_parser.add_argument("--mode", choices=["agentic", "fallback"], default="agentic", help="Research mode")
    run_parser.add_argument("--only-stale", action="store_true", help="Only process records requiring refresh")
    run_parser.add_argument("--resume", action="store_true", help="Skip museums already present in prices.json")
    run_parser.add_argument("--limit", type=int, default=None, help="Limit number of museums to process")
    run_parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL")
    run_parser.add_argument("--api-key", default=None, help="API key")
    run_parser.add_argument("--extractor-model", default=None, help="Model for extraction phase")
    run_parser.add_argument("--verifier-model", default=None, help="Model for verification phase (must be different family)")
    run_parser.add_argument("--allow-same-family", action="store_true", help="Bypass family check (testing only)")

    # 2. audit-identity command
    audit_id_parser = subparsers.add_parser("audit-identity", help="Audit museum websites for identity/title mismatches")
    audit_id_parser.add_argument("--limit", type=int, default=None, help="Limit number of museums to audit")

    # 3. audit command
    audit_parser = subparsers.add_parser("audit", help="Spot check accepted records")
    audit_parser.add_argument("--sample", type=int, default=10, help="Number of random accepted records to inspect")

    args = parser.parse_args()

    if args.command == "audit-identity":
        run_identity_audit(limit=args.limit)
        return

    if args.command == "audit":
        run_spot_check_audit(sample_size=args.sample)
        return

    if args.command == "run":
        job = JobDefinition.load(args.job)
        base_url = args.base_url or os.environ.get("ENRICH_BASE_URL", "http://localhost:11434/v1")
        api_key = args.api_key or os.environ.get("ENRICH_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        extractor = args.extractor_model or os.environ.get("ENRICH_EXTRACTOR_MODEL", "qwen3.5:9b")
        verifier = args.verifier_model or os.environ.get("ENRICH_VERIFIER_MODEL", "deepseek-r1:1.5b")

        print("=" * 60)
        print("=== MUSEUMWIJZER ENRICHMENT RUNNER ===")
        print(f"Job:             {job.title} ({job.field})")
        print(f"Mode:            {args.mode}")
        print(f"Base URL:        {base_url}")
        print(f"Extractor Model: {extractor}")
        print(f"Verifier Model:  {verifier}")
        print("=" * 60)

        orchestrator = EnrichmentOrchestrator(
            base_url=base_url,
            api_key=api_key,
            extractor_model=extractor,
            verifier_model=verifier,
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
        print("\n" + "=" * 60)
        print("=== RUN COMPLETE ===")
        print(f"Total Processed: {len(results)}")
        print(f"Accepted:        {acc_count}")
        print(f"Needs Review:    {rev_count}")
        print("=" * 60)


if __name__ == "__main__":
    main()
