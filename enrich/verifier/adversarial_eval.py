"""Adversarial evaluation suite for the independent verifier.

Tests the verifier and deterministic code gates against:
- 12+ Known-wrong adversarial claims (child price, wrong museum URL, combo price, stale price, invented number, free on paid, etc.)
- 8+ Positive controls (authentic, correct prices & closed statuses)

Reports:
(a) Overall rejection rate on wrong claims
(b) Confirm rate on correct claims
(c) Verifier-only rate on semantic cases, separated from gate catches.
"""

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


def run_adversarial_eval(
    verifier_model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    base_url = base_url or os.environ.get("ENRICH_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = api_key or os.environ.get("ENRICH_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    verifier_model = verifier_model or os.environ.get("ENRICH_VERIFIER_MODEL", "liquid/lfm-2.5-2.6b:free")

    client = OpenAICompatClient(base_url=base_url, api_key=api_key)
    fetcher = PoliteFetcher()
    verifier = IndependentVerifier(client, verifier_model=verifier_model)

    print("=" * 65)
    print("=== ADVERSARIAL VERIFIER EVALUATION ===")
    print(f"Verifier Model: {verifier_model}")
    print(f"Total Test Cases: {len(ADVERSARIAL_TEST_CASES)} (12 wrong, 8 positive controls)")
    print("=" * 65)

    results = []

    for tc in ADVERSARIAL_TEST_CASES:
        print(f"\n[{tc.id}] {tc.description}")
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

        # 2. Evaluate Verifier Model Alone (even if gates failed, to measure semantic verifier performance)
        v_result = verifier.verify(
            museum_name=tc.museum_name,
            museum_website=tc.museum_website,
            source_url=tc.source_url,
            claimed_value=tc.claimed_price,
            status=tc.status,
            fetcher=fetcher,
        )

        v_verdict = v_result.get("verdict")  # 'confirm', 'reject', 'unsure'
        v_rejected = v_verdict in ("reject", "unsure")

        # Overall Consensus Decision: gates must pass AND verifier must confirm
        consensus_confirmed = gates_passed and v_verdict == "confirm"
        consensus_rejected = not consensus_confirmed

        rec = {
            "id": tc.id,
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

    # Compute Metrics
    wrong_cases = [r for r in results if r["category"] == "wrong"]
    correct_cases = [r for r in results if r["category"] == "correct"]

    # (a) Rejection rate on wrong claims (Consensus)
    wrong_rejected_count = sum(1 for r in wrong_cases if r["consensus_rejected"])
    rejection_rate = (wrong_rejected_count / len(wrong_cases)) * 100.0 if wrong_cases else 0.0

    # (b) Confirm rate on correct claims (Consensus)
    correct_confirmed_count = sum(1 for r in correct_cases if r["consensus_confirmed"])
    confirm_rate = (correct_confirmed_count / len(correct_cases)) * 100.0 if correct_cases else 0.0

    # (c) Verifier-only rate on semantic cases (child, combo, wrong museum, other offering),
    # separated from cases where deterministic gates already catch them.
    semantic_subtypes = {"child_price", "combo_price", "wrong_museum", "stale_price", "group_rate", "pass_discount", "student_discount", "addon_bundle"}
    semantic_wrong_cases = [r for r in wrong_cases if r["subtype"] in semantic_subtypes]
    verifier_only_semantic_rejects = sum(1 for r in semantic_wrong_cases if r["verifier_verdict"] in ("reject", "unsure"))
    verifier_semantic_rate = (verifier_only_semantic_rejects / len(semantic_wrong_cases)) * 100.0 if semantic_wrong_cases else 0.0

    # Gate catches vs Verifier catches
    gate_catches = sum(1 for r in wrong_cases if not r["gates_passed"])
    verifier_catches = sum(1 for r in wrong_cases if r["verifier_verdict"] in ("reject", "unsure"))

    summary = {
        "verifier_model": verifier_model,
        "total_test_cases": len(results),
        "wrong_cases_count": len(wrong_cases),
        "correct_cases_count": len(correct_cases),
        "rejection_rate_wrong_claims_pct": round(rejection_rate, 1),
        "confirm_rate_correct_claims_pct": round(confirm_rate, 1),
        "verifier_semantic_reject_rate_pct": round(verifier_semantic_rate, 1),
        "gate_catches_count": gate_catches,
        "verifier_catches_count": verifier_catches,
        "results": results,
    }

    print("\n" + "=" * 65)
    print("=== ADVERSARIAL EVALUATION REPORT ===")
    print(f"1. Rejection Rate on Known-Wrong Claims: {rejection_rate:.1f}% ({wrong_rejected_count}/{len(wrong_cases)})")
    print(f"2. Confirm Rate on Correct Positive Controls: {confirm_rate:.1f}% ({correct_confirmed_count}/{len(correct_cases)})")
    print(f"3. Verifier-Only Rate on Semantic Cases: {verifier_semantic_rate:.1f}% ({verifier_only_semantic_rejects}/{len(semantic_wrong_cases)})")
    print(f"   - Deterministic Gate catches: {gate_catches}/{len(wrong_cases)}")
    print(f"   - Verifier Model catches:     {verifier_catches}/{len(wrong_cases)}")
    print("=" * 65)

    return summary


if __name__ == "__main__":
    run_adversarial_eval()
