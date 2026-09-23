"""Script to execute and compare agentic vs snippet-fallback modes across 20 pilot museums."""

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List

from enrich.jobs.base import JobDefinition
from enrich.ops.storage import record_results
from enrich.runner.orchestrator import EnrichmentOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("enrich.comparison")

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSEUMS_JSON_PATH = REPO_ROOT / "data" / "museums.json"
REPORT_OUTPUT_PATH = REPO_ROOT / ".cache" / "enrichment" / "dry_run_comparison.json"

# Load .env if present
env_file = REPO_ROOT / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v

PILOT_SLUGS = [
    # 10 Curated
    "museumprinsenhofdelft",
    "nationaal-monument-kamp-amersfoort",
    "rijksmuseum",
    "van-gogh-museum",
    "mauritshuis",
    "nemo-science-museum",
    "spoorwegmuseum",
    "watersnoodmuseum",
    "kasteel-de-haar",
    "museum-martena",
    # 10 Random (SEED=42)
    "anno",
    "discovery-museum",
    "dordrechts-museum",
    "fortresse-holland",
    "huis-zypendaal",
    "joods-museum",
    "kasteel-radboud",
    "nationaal-monument-kamp-vught",
    "sint-jan-de-doper",
    "stedelijk-museum-zutphen",
]


def load_pilot_records() -> List[Dict[str, Any]]:
    with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    by_slug = {m["slug"]: m for m in data.get("museums", [])}
    return [by_slug[s] for s in PILOT_SLUGS]


def run_mode(
    mode: str,
    museums: List[Dict[str, Any]],
    base_url: str,
    api_key: str,
    extractor_model: str,
    verifier_model: str,
    job: JobDefinition,
) -> Dict[str, Any]:
    print("\n" + "=" * 60)
    print(f"=== RUNNING PILOT IN MODE: {mode.upper()} ===")
    print("=" * 60)

    orchestrator = EnrichmentOrchestrator(
        base_url=base_url,
        api_key=api_key,
        extractor_model=extractor_model,
        verifier_model=verifier_model,
        job=job,
        mode=mode,
    )

    results = []
    start_total = time.time()

    for i, m in enumerate(museums, 1):
        slug = m["slug"]
        print(f"[{i}/{len(museums)}] ({mode}) Processing {slug}...")
        res = orchestrator.process_museum(m)
        results.append(res)
        status_str = "ACCEPTED" if res["is_accepted"] else "NEEDS_REVIEW"
        print(f"  -> {status_str} (calls: {res['tool_calls']}, time: {res['time_seconds']}s)")
        if not res["is_accepted"]:
            print(f"     Reasons: {res.get('gate_failures') or res.get('verifier_justification')}")

    total_time = round(time.time() - start_total, 2)
    accepted = [r for r in results if r["is_accepted"]]
    needs_review = [r for r in results if not r["is_accepted"]]

    # Collect failure reasons
    failure_reasons: Dict[str, List[str]] = {}
    for r in needs_review:
        reasons = list(r.get("gate_failures", []))
        if r.get("verifier_verdict") not in ("confirm", "skipped"):
            reasons.append(f"Verifier verdict '{r.get('verifier_verdict')}': {r.get('verifier_justification')}")
        failure_reasons[r["slug"]] = reasons

    total_tool_calls = sum(r["tool_calls"] for r in results)

    return {
        "mode": mode,
        "extractor_model": extractor_model,
        "verifier_model": verifier_model,
        "total": len(results),
        "accepted_count": len(accepted),
        "needs_review_count": len(needs_review),
        "total_tool_calls": total_tool_calls,
        "avg_tool_calls_per_museum": round(total_tool_calls / len(results), 2),
        "total_time_seconds": total_time,
        "avg_time_per_museum": round(total_time / len(results), 2),
        "failure_reasons": failure_reasons,
        "results": results,
    }


def main():
    base_url = os.environ.get("ENRICH_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.environ.get("ENRICH_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    extractor_model = os.environ.get("ENRICH_EXTRACTOR_MODEL", "google/gemma-4-26b-a4b-it:free")
    verifier_model = os.environ.get("ENRICH_VERIFIER_MODEL", "liquid/lfm-2.5-2.6b:free")

    job = JobDefinition.load("price_adult")
    museums = load_pilot_records()

    import argparse
    parser = argparse.ArgumentParser(description="Run pilot comparison or single mode across 20 museums")
    parser.add_argument("--mode", choices=["agentic", "fallback", "both"], default="agentic", help="Execution mode (default: agentic)")
    parser.add_argument("--record", action="store_true", default=True, help="Record results to prices.json and needs_review.json")
    args = parser.parse_args()

    fallback_report = None
    agentic_report = None

    if args.mode in ("fallback", "both"):
        fallback_report = run_mode(
            mode="fallback",
            museums=museums,
            base_url=base_url,
            api_key=api_key,
            extractor_model=extractor_model,
            verifier_model=verifier_model,
            job=job,
        )

    if args.mode in ("agentic", "both"):
        agentic_report = run_mode(
            mode="agentic",
            museums=museums,
            base_url=base_url,
            api_key=api_key,
            extractor_model=extractor_model,
            verifier_model=verifier_model,
            job=job,
        )
    if args.record:
        results_to_record = agentic_report["results"] if agentic_report else (fallback_report["results"] if fallback_report else None)
        if results_to_record:
            acc, rev = record_results(results_to_record)
            print(f"\nRecorded results: {acc} accepted, {rev} needs_review in data/enrichment/")

    comparison = {
        "pilot_museums_count": len(museums),
        "models": {
            "extractor": extractor_model,
            "verifier": verifier_model,
        },
        "fallback_mode": fallback_report,
        "agentic_mode": agentic_report,
    }

    REPORT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)

    if fallback_report and agentic_report:
        print("\n" + "=" * 75)
        print("=== DRY RUN COMPARISON SUMMARY (20 PILOT MUSEUMS) ===")
        print("=" * 75)
        print(f"{'Metric':<30} | {'Fallback Mode':<18} | {'Agentic Mode':<18}")
        print("-" * 75)
        print(f"{'Accepted':<30} | {fallback_report['accepted_count']:<18} | {agentic_report['accepted_count']:<18}")
        print(f"{'Needs Review':<30} | {fallback_report['needs_review_count']:<18} | {agentic_report['needs_review_count']:<18}")
        print(f"{'Total Tool / Page Calls':<30} | {fallback_report['total_tool_calls']:<18} | {agentic_report['total_tool_calls']:<18}")
        print(f"{'Avg Calls / Museum':<30} | {fallback_report['avg_tool_calls_per_museum']:<18} | {agentic_report['avg_tool_calls_per_museum']:<18}")
        print(f"{'Total Time (s)':<30} | {fallback_report['total_time_seconds']:<18} | {agentic_report['total_time_seconds']:<18}")
        print(f"{'Avg Time / Museum (s)':<30} | {fallback_report['avg_time_per_museum']:<18} | {agentic_report['avg_time_per_museum']:<18}")
        print("=" * 75)
    elif agentic_report:
        print("\n" + "=" * 65)
        print("=== AGENTIC PILOT RUN SUMMARY (20 MUSEUMS) ===")
        print(f"Accepted:     {agentic_report['accepted_count']}/{len(museums)}")
        print(f"Needs Review: {agentic_report['needs_review_count']}/{len(museums)}")
        print(f"Tool Calls:   {agentic_report['total_tool_calls']} (avg {agentic_report['avg_tool_calls_per_museum']} / museum)")
        print(f"Time Taken:   {agentic_report['total_time_seconds']}s")
        print("=" * 65)


if __name__ == "__main__":
    main()
