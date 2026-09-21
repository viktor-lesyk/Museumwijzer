"""Adversarial evaluation suite for the independent verifier.

Tests the verifier and deterministic code gates against:
- 12+ Known-wrong adversarial claims (child price, wrong museum URL, combo price, stale price, invented number, free on paid, etc.)
- 8+ Positive controls (authentic, correct prices & closed statuses)

Reports:
(a) Overall rejection rate on wrong claims
(b) Confirm rate on correct claims
(c) Verifier-only rate on semantic cases, separated from gate catches.
"""

import math
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from enrich.fetch import PoliteFetcher
from enrich.gates.price_gates import run_all_price_gates
from enrich.runner.client import OpenAICompatClient
from enrich.tools.fetch_page import sanitize_html_for_agent
from enrich.verifier.verifier import IndependentVerifier, assert_different_model_families

logger = logging.getLogger("enrich.adversarial_eval")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Calculate the two-sided Wilson score confidence interval for a binomial proportion.

    Returns (lower_pct, upper_pct) bounded between 0.0 and 100.0.
    """
    if total <= 0:
        return 0.0, 100.0

    # For 95% confidence, z ~ 1.95996
    z = 1.959963984540054 if confidence == 0.95 else 1.6448536269514722
    p_hat = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denom
    std_err = math.sqrt((p_hat * (1.0 - p_hat) / total) + (z2 / (4.0 * total * total)))
    margin = (z / denom) * std_err

    lower = max(0.0, center - margin) * 100.0
    upper = min(1.0, center + margin) * 100.0
    return round(lower, 1), round(upper, 1)


@dataclass
class TestCase:
    id: str
    category: str  # "wrong" or "correct"
    semantic_subtype: Optional[str]  # e.g. "child_price", "combo_price", "wrong_museum", "stale_price", "group_rate", "positive_control"
    museum_name: str
    museum_website: str
    source_url: str
    claimed_price: Optional[float]
    status: str
    quote: Optional[str]
    description: str
    is_holdout: bool = False


ADVERSARIAL_TEST_CASES: List[TestCase] = [
    # --- 12 KNOWN-WRONG CLAIMS ---
    TestCase(
        id="W1",
        category="wrong",
        semantic_subtype="child_price",
        museum_name="Rijksmuseum",
        museum_website="https://www.rijksmuseum.nl/",
        source_url="https://www.rijksmuseum.nl/",
        claimed_price=0.0,
        status="paid",
        quote="Jongeren t/m 18 jaar Gratis",
        description="Child/youth free entry claimed as standard adult ticket (adult is €25.00)",
    ),
    TestCase(
        id="W2",
        category="wrong",
        semantic_subtype="wrong_museum",
        museum_name="Rijksmuseum",
        museum_website="https://www.rijksmuseum.nl/",
        source_url="https://www.spoorwegmuseum.nl/",
        claimed_price=19.50,
        status="paid",
        quote="Volwassenen € 19,50",
        description="Ticket price from a completely different museum (Spoorwegmuseum URL used for Rijksmuseum)",
    ),
    TestCase(
        id="W3",
        category="wrong",
        semantic_subtype="combo_price",
        museum_name="Joods Museum",
        museum_website="https://jck.nl/",
        source_url="https://jck.nl/locaties/joods-museum",
        claimed_price=30.00,
        status="paid",
        quote="Combiticket Bezoek alle vier locaties Volwassenen € 30",
        description="Cluster combiticket (€30) claimed as single adult museum entry",
    ),
    TestCase(
        id="W4",
        category="wrong",
        semantic_subtype="stale_price",
        museum_name="Rijksmuseum",
        museum_website="https://www.rijksmuseum.nl/",
        source_url="https://www.rijksmuseum.nl/",
        claimed_price=17.50,
        status="paid",
        quote="Volwassenen € 17,50",
        description="Stale/outdated price (€17.50 claimed when the live website states €25.00)",
    ),
    TestCase(
        id="W5",
        category="wrong",
        semantic_subtype="invented_number",
        museum_name="Dordrechts Museum",
        museum_website="https://www.dordrechtsmuseum.nl/",
        source_url="https://www.dordrechtsmuseum.nl/",
        claimed_price=33.33,
        status="paid",
        quote="Volwassenen ticket € 33,33",
        description="Invented price number (€33.33) appearing nowhere in page text",
    ),
    TestCase(
        id="W6",
        category="wrong",
        semantic_subtype="free_on_paid",
        museum_name="Het Spoorwegmuseum",
        museum_website="https://www.spoorwegmuseum.nl/",
        source_url="https://www.spoorwegmuseum.nl/",
        claimed_price=0.0,
        status="free",
        quote="Toegang tot het museum is gratis voor iedereen",
        description="Free general admission claimed for a paid museum (€19.50) with fake quote",
    ),
    TestCase(
        id="W7",
        category="wrong",
        semantic_subtype="group_rate",
        museum_name="Watersnoodmuseum",
        museum_website="https://watersnoodmuseum.nl/",
        source_url="https://watersnoodmuseum.nl/",
        claimed_price=13.50,
        status="paid",
        quote="Groepen vanaf 15 personen € 13,50",
        description="Group discount rate claimed as individual standard adult ticket",
    ),
    TestCase(
        id="W8",
        category="wrong",
        semantic_subtype="pass_discount",
        museum_name="Museum Martena",
        museum_website="https://www.museummartena.nl/",
        source_url="https://www.museummartena.nl/",
        claimed_price=0.0,
        status="free",
        quote="Museumkaart gratis toegang",
        description="Member/Museumkaart pass claimed as general free admission for all adults",
    ),
    TestCase(
        id="W9",
        category="wrong",
        semantic_subtype="student_discount",
        museum_name="ANNO",
        museum_website="https://anno.nl/",
        source_url="https://anno.nl/",
        claimed_price=7.50,
        status="paid",
        quote="Studenten € 7,50",
        description="Student discount tariff claimed as standard adult price (€12.50)",
    ),
    TestCase(
        id="W10",
        category="wrong",
        semantic_subtype="addon_bundle",
        museum_name="Het Spoorwegmuseum",
        museum_website="https://www.spoorwegmuseum.nl/",
        source_url="https://www.spoorwegmuseum.nl/",
        claimed_price=7.50,
        status="paid",
        quote="Audiotour toeslag € 7,50",
        description="Audio tour add-on package claimed as museum entry ticket",
    ),
    TestCase(
        id="W11",
        category="wrong",
        semantic_subtype="out_of_bounds",
        museum_name="Museum Martena",
        museum_website="https://www.museummartena.nl/",
        source_url="https://www.museummartena.nl/",
        claimed_price=99.00,
        status="paid",
        quote="Volwassenen € 99,00",
        description="Extreme out-of-bounds price (€99.00) exceeding max plausible limit (€45.00)",
    ),
    TestCase(
        id="W12",
        category="wrong",
        semantic_subtype="identity_mismatch",
        museum_name="Anne Frank Huis",
        museum_website="https://www.annefrank.org/",
        source_url="https://www.spoorwegmuseum.nl/",
        claimed_price=19.50,
        status="paid",
        quote="Volwassenen € 19,50",
        description="Foreign museum identity and website verified against Spoorwegmuseum page",
    ),

    # --- 8 POSITIVE CONTROLS (AUTHENTIC & CORRECT) ---
    TestCase(
        id="C1",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Rijksmuseum",
        museum_website="https://www.rijksmuseum.nl/",
        source_url="https://www.rijksmuseum.nl/en/visit/practical-info/opening-hours-and-prices",
        claimed_price=25.00,
        status="paid",
        quote="Adults: €25",
        description="Authentic standard adult ticket on Rijksmuseum ticket prices page",
    ),
    TestCase(
        id="C2",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Het Spoorwegmuseum",
        museum_website="https://www.spoorwegmuseum.nl/",
        source_url="https://www.spoorwegmuseum.nl/bezoek/bezoekersinformatie/",
        claimed_price=19.50,
        status="paid",
        quote="Entree € 19,50",
        description="Authentic standard adult ticket on Spoorwegmuseum visitors page",
    ),
    TestCase(
        id="C3",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Watersnoodmuseum",
        museum_website="https://watersnoodmuseum.nl/",
        source_url="https://ticket.watersnoodmuseum.nl/?language=nl",
        claimed_price=16.00,
        status="paid",
        quote="Volwassenen (vanaf 12 jaar) € 16.00",
        description="Authentic standard adult ticket on Watersnoodmuseum ticketing subpage",
    ),
    TestCase(
        id="C4",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Museum Martena",
        museum_website="https://www.museummartena.nl/",
        source_url="https://www.museummartena.nl/bezoekinformatie-museum/tickets-en-tarieven",
        claimed_price=6.00,
        status="paid",
        quote="Volwassenen : € 6,-",
        description="Authentic standard adult ticket on Museum Martena tickets page",
    ),
    TestCase(
        id="C5",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="ANNO",
        museum_website="https://anno.nl/",
        source_url="https://tickets.anno.nl/nl/tickets",
        claimed_price=12.50,
        status="paid",
        quote="Volwassenen € 12,50",
        description="Authentic standard adult ticket on ANNO ticket shop",
    ),
    TestCase(
        id="C6",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Dordrechts Museum",
        museum_website="https://www.dordrechtsmuseum.nl/",
        source_url="https://www.dordrechtsmuseum.nl/praktische-informatie",
        claimed_price=17.00,
        status="paid",
        quote="Volwassenen € 17",
        description="Authentic standard adult ticket on Dordrechts Museum info page",
    ),
    TestCase(
        id="C7",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Sint-Jan de Doper",
        museum_website="https://www.vriendensintjanwaalwijk.nl/",
        source_url="https://www.vriendensintjanwaalwijk.nl/",
        claimed_price=0.0,
        status="free",
        quote="De toegang is gratis.",
        description="Authentic free admission quote on Sint-Jan de Doper homepage",
    ),
    TestCase(
        id="C8",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Museum Prinsenhof Delft",
        museum_website="https://www.museumprinsenhofdelft.nl/",
        source_url="https://www.museumprinsenhofdelft.nl/plan-je-bezoek",
        claimed_price=None,
        status="closed",
        quote="Museum Prinsenhof Delft is tijdelijk gesloten voor verbouwing en vernieuwing.",
        description="Authentic temporary renovation closure quote on Prinsenhof plan page",
    ),
]


HOLD_OUT_TEST_CASES: List[TestCase] = [
    # --- 5 HOLD-OUT POSITIVE CONTROLS (Authentic & Correct from New Unused Museum Pages) ---
    TestCase(
        id="H_C1",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Van Gogh Museum",
        museum_website="https://www.vangoghmuseum.nl/",
        source_url="https://www.vangoghmuseum.nl/en/visit/tickets-and-ticket-prices",
        claimed_price=25.00,
        status="paid",
        quote="Adults: € 25.",
        description="Authentic standard adult ticket on Van Gogh Museum tickets subpage",
        is_holdout=True,
    ),
    TestCase(
        id="H_C2",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Stedelijk Museum Amsterdam",
        museum_website="https://www.stedelijk.nl/",
        source_url="https://www.stedelijk.nl/nl",
        claimed_price=22.50,
        status="paid",
        quote="Volwassenen: € 22,50",
        description="Authentic standard adult ticket on Stedelijk Museum Amsterdam homepage",
        is_holdout=True,
    ),
    TestCase(
        id="H_C3",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Marius van Dokkum Museum",
        museum_website="https://www.mariusvandokkummuseum.nl/",
        source_url="https://www.mariusvandokkummuseum.nl/",
        claimed_price=15.00,
        status="paid",
        quote="Volwassenen € 15",
        description="Authentic standard adult ticket on Marius van Dokkum Museum homepage",
        is_holdout=True,
    ),
    TestCase(
        id="H_C4",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Paleis Lofen",
        museum_website="https://www.paleislofen.nl/",
        source_url="https://www.paleislofen.nl/bezoek/",
        claimed_price=13.50,
        status="paid",
        quote="Volwassene € 13,50",
        description="Authentic standard adult ticket on Paleis Lofen visit page",
        is_holdout=True,
    ),
    TestCase(
        id="H_C5",
        category="correct",
        semantic_subtype="positive_control",
        museum_name="Nationaal Museum Tachtigjarige Oorlog",
        museum_website="https://www.nmto.nl/",
        source_url="https://www.nmto.nl",
        claimed_price=12.50,
        status="paid",
        quote="Volwassenen: €12,50",
        description="Authentic standard adult ticket on NMTO Groenlo homepage",
        is_holdout=True,
    ),

    # --- 5 HOLD-OUT KNOWN-WRONG CLAIMS (Pure Semantic Non-Adult Discounts) ---
    TestCase(
        id="H_W1",
        category="wrong",
        semantic_subtype="student_discount",
        museum_name="Van Gogh Museum",
        museum_website="https://www.vangoghmuseum.nl/",
        source_url="https://www.vangoghmuseum.nl/en/visit/tickets-and-ticket-prices",
        claimed_price=16.00,
        status="paid",
        quote="Students: € 16",
        description="Student discount claimed as regular adult ticket at Van Gogh Museum",
        is_holdout=True,
    ),
    TestCase(
        id="H_W2",
        category="wrong",
        semantic_subtype="student_discount",
        museum_name="Stedelijk Museum Amsterdam",
        museum_website="https://www.stedelijk.nl/",
        source_url="https://www.stedelijk.nl/nl",
        claimed_price=12.50,
        status="paid",
        quote="Student & CJP: € 12,50",
        description="Student / CJP tariff claimed as regular adult ticket at Stedelijk Museum",
        is_holdout=True,
    ),
    TestCase(
        id="H_W3",
        category="wrong",
        semantic_subtype="youth_price",
        museum_name="Marius van Dokkum Museum",
        museum_website="https://www.mariusvandokkummuseum.nl/",
        source_url="https://www.mariusvandokkummuseum.nl/",
        claimed_price=5.00,
        status="paid",
        quote="Jongeren 13 t/m 18 jaar € 5",
        description="Youth admission tariff claimed as regular adult ticket at Marius van Dokkum Museum",
        is_holdout=True,
    ),
    TestCase(
        id="H_W4",
        category="wrong",
        semantic_subtype="child_price",
        museum_name="Paleis Lofen",
        museum_website="https://www.paleislofen.nl/",
        source_url="https://www.paleislofen.nl/bezoek/",
        claimed_price=10.00,
        status="paid",
        quote="Student / Kind (adviesleeftijd vanaf 8 jaar) € 10,-",
        description="Child / student discounted rate claimed as adult ticket at Paleis Lofen",
        is_holdout=True,
    ),
    TestCase(
        id="H_W5",
        category="wrong",
        semantic_subtype="child_price",
        museum_name="Nationaal Museum Tachtigjarige Oorlog",
        museum_website="https://www.nmto.nl/",
        source_url="https://www.nmto.nl",
        claimed_price=7.50,
        status="paid",
        quote="(5-12 jaar): €7,50",
        description="Child ticket rate claimed as regular adult ticket at NMTO",
        is_holdout=True,
    ),
]

ALL_TEST_CASES = ADVERSARIAL_TEST_CASES + HOLD_OUT_TEST_CASES


def evaluate_cohort(cohort_results: List[Dict[str, Any]], cohort_name: str) -> Dict[str, Any]:
    wrong_cases = [r for r in cohort_results if r["category"] == "wrong"]
    correct_cases = [r for r in cohort_results if r["category"] == "correct"]

    # (a) Rejection rate on wrong claims (Consensus)
    wrong_rejected_count = sum(1 for r in wrong_cases if r["consensus_rejected"])
    rejection_rate = (wrong_rejected_count / len(wrong_cases)) * 100.0 if wrong_cases else 0.0
    wrong_ci = wilson_score_interval(wrong_rejected_count, len(wrong_cases))

    # (b) Confirm rate on correct claims (Consensus)
    correct_confirmed_count = sum(1 for r in correct_cases if r["consensus_confirmed"])
    confirm_rate = (correct_confirmed_count / len(correct_cases)) * 100.0 if correct_cases else 0.0
    correct_ci = wilson_score_interval(correct_confirmed_count, len(correct_cases))

    # (c) Verifier-only rate on semantic cases, separated from gate catches
    semantic_subtypes = {
        "child_price", "combo_price", "wrong_museum", "stale_price",
        "group_rate", "pass_discount", "student_discount", "youth_price", "addon_bundle",
    }
    semantic_wrong_cases = [r for r in wrong_cases if r["subtype"] in semantic_subtypes]
    verifier_only_semantic_rejects = sum(1 for r in semantic_wrong_cases if r["verifier_verdict"] in ("reject", "unsure"))
    verifier_semantic_rate = (verifier_only_semantic_rejects / len(semantic_wrong_cases)) * 100.0 if semantic_wrong_cases else 0.0
    semantic_ci = wilson_score_interval(verifier_only_semantic_rejects, len(semantic_wrong_cases))

    gate_catches = sum(1 for r in wrong_cases if not r["gates_passed"])
    verifier_catches = sum(1 for r in wrong_cases if r["verifier_verdict"] in ("reject", "unsure"))

    return {
        "cohort_name": cohort_name,
        "total_cases": len(cohort_results),
        "wrong_count": len(wrong_cases),
        "wrong_rejected": wrong_rejected_count,
        "rejection_rate_pct": round(rejection_rate, 1),
        "rejection_ci_95": wrong_ci,
        "correct_count": len(correct_cases),
        "correct_confirmed": correct_confirmed_count,
        "confirm_rate_pct": round(confirm_rate, 1),
        "confirm_ci_95": correct_ci,
        "semantic_wrong_count": len(semantic_wrong_cases),
        "semantic_rejected": verifier_only_semantic_rejects,
        "semantic_rate_pct": round(verifier_semantic_rate, 1),
        "semantic_ci_95": semantic_ci,
        "gate_catches": gate_catches,
        "verifier_catches": verifier_catches,
    }


def run_adversarial_eval(
    verifier_model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    include_holdout: bool = True,
) -> Dict[str, Any]:
    base_url = base_url or os.environ.get("ENRICH_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = api_key or os.environ.get("ENRICH_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    verifier_model = verifier_model or os.environ.get("ENRICH_VERIFIER_MODEL", "liquid/lfm-2.5-2.6b:free")

    client = OpenAICompatClient(base_url=base_url, api_key=api_key)
    fetcher = PoliteFetcher()
    verifier = IndependentVerifier(client, verifier_model=verifier_model)

    test_cases = ALL_TEST_CASES if include_holdout else ADVERSARIAL_TEST_CASES

    print("=" * 70)
    print("=== ADVERSARIAL VERIFIER EVALUATION ===")
    print(f"Verifier Model: {verifier_model}")
    print(f"Total Test Cases: {len(test_cases)} (Baseline: {len(ADVERSARIAL_TEST_CASES)}, Hold-out: {len(HOLD_OUT_TEST_CASES) if include_holdout else 0})")
    print("=" * 70)

    results = []

    for tc in test_cases:
        prefix = "[HOLD-OUT] " if tc.is_holdout else ""
        print(f"\n{prefix}[{tc.id}] {tc.description}")
        print(f"     Target: {tc.museum_name} | Claim: €{tc.claimed_price} (status: {tc.status})")

        # Fetch page
        succ, html, _ = fetcher.fetch(tc.source_url)
        page_text = ""
        if succ and html:
            sanitized = sanitize_html_for_agent(html, tc.source_url)
            page_text = sanitized["text"]

        extracted_data = {
            "status": tc.status,
            "primary_adult_eur": tc.claimed_price,
            "quote": tc.quote,
            "source_url": tc.source_url,
        }

        # 1. Evaluate Deterministic Code Gates
        gates_passed, gate_failures = run_all_price_gates(
            slug=tc.id.lower(),
            museum_name=tc.museum_name,
            city=None,
            museum_website=tc.museum_website,
            source_url=tc.source_url,
            page_text=page_text,
            extracted_data=extracted_data,
            fetcher=fetcher,
        )

        # 2. Evaluate Verifier Model Alone
        v_result = verifier.verify(
            museum_name=tc.museum_name,
            museum_website=tc.museum_website,
            source_url=tc.source_url,
            claimed_value=tc.claimed_price,
            status=tc.status,
            fetcher=fetcher,
        )

        v_verdict = v_result.get("verdict")  # 'confirm', 'reject', 'unsure'
        consensus_confirmed = gates_passed and v_verdict == "confirm"
        consensus_rejected = not consensus_confirmed

        rec = {
            "id": tc.id,
            "is_holdout": tc.is_holdout,
            "category": tc.category,
            "subtype": tc.semantic_subtype,
            "description": tc.description,
            "gates_passed": gates_passed,
            "gate_failures": gate_failures,
            "verifier_verdict": v_verdict,
            "verifier_justification": v_result.get("justification"),
            "consensus_confirmed": consensus_confirmed,
            "consensus_rejected": consensus_rejected,
        }
        results.append(rec)

        status_str = "REJECTED" if consensus_rejected else "CONFIRMED"
        print(f"     Gates: {'PASS' if gates_passed else 'FAIL (' + ', '.join(gate_failures) + ')'}")
        print(f"     Verifier: {v_verdict.upper()} ({v_result.get('justification')})")
        print(f"     -> Consensus: {status_str}")

    # Cohort analyses
    baseline_results = [r for r in results if not r["is_holdout"]]
    holdout_results = [r for r in results if r["is_holdout"]]

    baseline_metrics = evaluate_cohort(baseline_results, "Baseline Suite (20 cases)")
    holdout_metrics = evaluate_cohort(holdout_results, "Hold-out Suite (10 cases)") if holdout_results else None
    combined_metrics = evaluate_cohort(results, f"Combined Suite ({len(results)} cases)")

    def print_metrics_block(m: Dict[str, Any]):
        print(f"\n--- {m['cohort_name']} ---")
        print(f"  1. Rejection Rate on Wrong Claims:     {m['rejection_rate_pct']:.1f}% ({m['wrong_rejected']}/{m['wrong_count']}) "
              f"[95% Wilson CI: {m['rejection_ci_95'][0]:.1f}% – {m['rejection_ci_95'][1]:.1f}%]")
        print(f"  2. Confirm Rate on Positive Controls:  {m['confirm_rate_pct']:.1f}% ({m['correct_confirmed']}/{m['correct_count']}) "
              f"[95% Wilson CI: {m['confirm_ci_95'][0]:.1f}% – {m['confirm_ci_95'][1]:.1f}%]")
        print(f"  3. Verifier-Only Semantic Catch Rate:  {m['semantic_rate_pct']:.1f}% ({m['semantic_rejected']}/{m['semantic_wrong_count']}) "
              f"[95% Wilson CI: {m['semantic_ci_95'][0]:.1f}% – {m['semantic_ci_95'][1]:.1f}%]")
        print(f"     • Deterministic Gate catches:       {m['gate_catches']}/{m['wrong_count']}")
        print(f"     • Verifier Model catches:           {m['verifier_catches']}/{m['wrong_count']}")

    print("\n" + "=" * 70)
    print("=== STATISTICAL ADVERSARIAL EVALUATION REPORT ===")
    print_metrics_block(baseline_metrics)
    if holdout_metrics:
        print_metrics_block(holdout_metrics)
    print_metrics_block(combined_metrics)
    print("=" * 70)

    return {
        "verifier_model": verifier_model,
        "baseline": baseline_metrics,
        "holdout": holdout_metrics,
        "combined": combined_metrics,
        "results": results,
    }


if __name__ == "__main__":
    run_adversarial_eval()
