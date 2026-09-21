# Museumwijzer Verifying Agent Enrichment Framework

## 1. Architectural Overview & Design Principles

The `enrich/` framework is a model-agnostic, multi-stage verifying agent system designed to enrich museum records with external metadata (starting with `price_adult`) while guaranteeing data integrity.

Enrichment operates independently from the weekly scraping pipeline:
- Prices and enrichment data are stored in `data/enrichment/prices.json`.
- Problematic, ambiguous, or unverifiable claims are routed to `data/enrichment/needs_review.json`.
- Enrichment data is **not** wired into the public static site until manually approved.

```
                     ┌───────────────────────────┐
                     │     Target Museum Record  │
                     └─────────────┬─────────────┘
                                   │
                                   ▼
        ┌─────────────────────────────────────────────────────┐
        │                 EXTRACTION PHASE                    │
        │  Agentic Tool Calling (max 8 calls) OR Fallback     │
        │  Allowed Tools: fetch_page, web_search (pointers)   │
        │  Model: Configured Extractor (e.g. Gemma / Qwen)   │
        └──────────────────────────┬──────────────────────────┘
                                   │
                                   ▼
        ┌─────────────────────────────────────────────────────┐
        │            DETERMINISTIC CODE GATES                 │
        │  1. Domain Match / Provenance from museum_website   │
        │  2. Literal Match of Number & Quote (≤15 words)     │
        │  3. Museum Identity (Name/City) on Page             │
        │  4. Plausible Price Range (€1.00 – €45.00)          │
        │  5. Combo / Duo / Joint Ticket Rejection            │
        │  6. Year-over-Year (YoY) Change Flag (>30%)         │
        └──────────────────────────┬──────────────────────────┘
                                   │ (All Gates Passed)
                                   ▼
        ┌─────────────────────────────────────────────────────┐
        │             INDEPENDENT VERIFIER PHASE              │
        │  Isolated call receiving ONLY: {name, url, price}   │
        │  Never sees extractor reasoning                     │
        │  Different Model Family Required (e.g. Liquid/Llama)│
        │  Output: confirm | reject | unsure                  │
        └──────────────────────────┬──────────────────────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                │ Consensus Check                     │
                │ Gates PASS + Verifier CONFIRM?      │
                └─────────┬─────────────────┬─────────┘
                          │ YES             │ NO
                          ▼                 ▼
          ┌──────────────────────────┐  ┌──────────────────────────┐
          │ data/enrichment/         │  │ data/enrichment/         │
          │ prices.json              │  │ needs_review.json        │
          └──────────────────────────┘  └──────────────────────────┘
```

---

## 2. Model Family Segregation & Guardrails

1. **Two Different Model Families Enforced:**
   To avoid self-reinforcing hallucinations, the extractor model and verifier model must belong to distinct families (e.g., `gemma` and `liquid`, or `qwen` and `deepseek`). The framework refuses to run if identical families are configured (`assert_different_model_families`).
2. **Prompt Injection Defense:**
   All untrusted HTML content fetched from the web is cleaned and wrapped in `<untrusted_web_content url="...">...</untrusted_web_content>` delimiters before being passed to any model.
3. **Strict Tool Allowlist:**
   Only two tools are exposed to the agent:
   - `fetch_page(url)`: Polite rate-limited fetcher (1 req/s per domain, User-Agent with contact email, robots.txt check, bot-protection challenge detection).
   - `web_search(query)`: Pointer-only search (Tavily/Brave). Search snippets are strictly pointers and do not count as evidence.
   Personal tools (Notion, Drive, Todoist) are never exposed.
4. **Execution Budgets:**
   - Maximum 8 tool calls per museum.
   - Temperature 0.0 for deterministic reproducibility.
   - Secret scrubbing: All trace logs stored in `.cache/enrichment/traces/<slug>.json` are stripped of API keys and Bearer tokens.

---

## 2.1 Expanded Price Schema

The admission price schema (`enrich/jobs/price_adult.yaml`) captures admission pricing with sorting and filtering capabilities:

```yaml
status: "paid" | "free" | "closed" | "combo_only" | "blocked_by_bot_protection" | "not_found" | "unknown"
primary_adult_eur: number | null  # Standard single-entry adult ticket in EUR (1.00 - 45.00 for paid, 0.0 for free, null otherwise)
free_for:                         # Audiences with free admission (controlled vocabulary)
  - children_under_4
  - children_under_12
  - children_under_18
  - youth
  - students
  - seniors
  - museumkaart
  - vriendenloterij_vip_kaart
  - icom
  - rembrandtkaart
  - everyone
  - other
combo_available: boolean | null   # Whether combination tickets are sold alongside single entry
offerings:                        # Full ticket offering list (Phase 2)
  - audience: "adult" | "youth" | "child" | "student" | "senior" | "family" | "group" | "other"
    amount_eur: number | null
    label: string                 # Up to 8 words as on the page
    conditions: string | null     # e.g. '18-25 years'
quote: string | null              # Literal supporting quote from page (maximum 15 words)
source_url: string | null         # Exact URL where price and quote were found
reason: string
confidence: "high" | "medium" | "low" | "blocked_by_bot_protection" | "blocked_by_robots"
entered_by: "agent" | "manual"
mode: "agentic" | "fallback"
extractor_model: string
verifier_model: string
checked_on: string                # YYYY-MM-DD
```

### Confidence Calibration:
- **High:** A single clearly labelled adult ticket price found directly on the official primary or ticketing subpage.
- **Medium:** Multi-tier pricing (e.g. peak vs off-peak, castle vs gardens, online vs door), secondary subpage, or complex options.
- **Low / Needs Review:** Inferred or ambiguous prices.

---

## 2.2 Escalation Ladder & Retry Architecture

Extraction runs with an automatic two-step recovery ladder before routing to `needs_review.json`:

1. **Quote Length Immediate Retry:**
   If the extraction is valid and all gates pass except that the supporting quote exceeds 15 words, the orchestrator initiates an immediate single-turn retry instructing the model to trim the quote to ≤ 15 words while preserving literal page wording.
2. **Model Escalation Ladder:**
   If the primary extractor model fails gates, an optional stronger escalation model (`ENRICH_ESCALATION_MODEL`, e.g. `meta-llama/llama-3.3-70b-instruct`) is invoked for a secondary extraction attempt.
   - Guardrail: The escalation model is checked at initialization to ensure it belongs to a **different model family** from the independent verifier.

---

## 3. Deterministic Code Gates

Before invoking the verifier model, code gates validate the extraction deterministically (no LLM):
1. **Domain & Link Provenance:** `source_url` domain must match `museum_website` domain or subdomain, or be reached by following internal links from the root website.
2. **Literal Verbatim Presence:** The claimed numerical price and supporting quote (≤ 15 words) must appear verbatim in the page text.
3. **Admission Validity:**
   - Paid: `primary_adult_eur` between €1.00 and €45.00; `status: "paid"`.
   - Free: Requires an explicit quote proving free general admission for all adults (free-for-children does not qualify); `primary_adult_eur: 0.0`.
4. **Combo / Duo Rejection:** Quotes containing `"combo"`, `"combi"`, `"duo"`, `"gezamenlijk"`, or `"combiticket"` are rejected to `needs_review`.
5. **Year-over-Year (YoY) Change Flag:** If a price changes by >30% compared to the previous run, it is flagged for human review.

---

## 3.1 Independent Verifier Methodology & Statistical Evaluation

### Isolation Guarantees:
1. **Zero Contamination:** The verifier receives strictly `{museum_name, museum_website, source_url, claimed_value, status}` and sanitized page text inside `<untrusted_web_content>` tags.
2. **No Extractor Reasoning:** The verifier never sees the extractor's thoughts, intermediate steps, or rationale.
3. **Deterministic Sampling:** Verified at `temperature: 0.0`.
4. **Strict Cross-Family Requirement:** Evaluated by `assert_different_model_families`.

### Adversarial Evaluation Suite:
The verifier is benchmarked against **30 test cases** partitioned into a 20-case baseline suite and a 10-case hold-out suite from completely new museum pages. Metrics are statistically grounded using **two-sided 95% Wilson score confidence intervals**:

| Suite Cohort | Total Cases | Wrong Claims Rejected (95% CI) | Positive Controls Confirmed (95% CI) | Verifier-Only Semantic Catch Rate (95% CI) |
|---|---|---|---|---|
| **Baseline Suite** | 20 (12 wrong, 8 correct) | **100.0%** (12/12) `[75.8% – 100.0%]` | **100.0%** (8/8) `[67.6% – 100.0%]` | **100.0%** (8/8) `[67.6% – 100.0%]` |
| **Hold-Out Suite** | 10 (5 wrong, 5 correct) | **100.0%** (5/5) `[56.6% – 100.0%]` | **100.0%** (5/5) `[56.6% – 100.0%]` | **100.0%** (5/5) `[56.6% – 100.0%]` |
| **Combined Overall** | **30 (17 wrong, 13 correct)** | **100.0%** (17/17) `[81.6% – 100.0%]` | **100.0%** (13/13) `[77.2% – 100.0%]` | **100.0%** (13/13) `[77.2% – 100.0%]` |

#### Gate Catches vs Semantic Verifier Catches:
- **Deterministic Gate Catches (4 cases):** Invented prices not on page (`W5`), combi keywords (`W3`), prices out of bounds (`W11`), and foreign museum domains (`W12`).
- **Verifier-Only Semantic Catches (13 cases):** Real, validly formatted prices on live pages that belong to other audiences: child free entry claimed as adult (`W1`, `H_W4`, `H_W5`), student discounts (`W9`, `H_W1`, `H_W2`), youth tariffs (`H_W3`), member/Museumkaart passes (`W8`), group discounts (`W7`), audio tour bundles (`W10`), and stale historical prices (`W4`). These pass all deterministic gates and require LLM semantic reasoning.

---

## 4. Identity Discovery & Address Verification Jobs

Identity jobs operate under a strict governance model: **they NEVER modify `data/overrides.yaml` directly**. All candidate updates are written strictly to `data/enrichment/proposals.json` for human inspection and bulk approval.

### Jobs:
1. **`website` (`enrich/jobs/website.yaml`):**
   - Discovers official homepages for museums missing `museum_website` (10 active venues).
   - **Aggregator Blacklist:** Rejects TripAdvisor, Wikipedia, Museum.nl, WhichMuseum, Facebook, Instagram, TikTok, VVV, municipal news portals, and booking engines.
   - **Identity Proof:** Requires candidate page to match the museum's distinctive name and city tokens.
2. **`address_check` (`enrich/jobs/address_check.yaml`):**
   - Visits official contact/route pages (`/contact`, `/route`, `/bereikbaarheid`).
   - Extracts Dutch postal codes and street addresses.
   - Detects discrepancies against `data/museums.json` and proposes corrections to `proposals.json`.

---

## 5. CLI Usage & Commands

The enrichment CLI (`python -m enrich`) provides commands for extraction, identity audits, and proposals management:

### Run Enrichment Jobs
```bash
# Run adult ticket enrichment on all museums in agentic mode (default)
python -m enrich run --job price_adult --mode agentic

# Run website discovery on museums lacking websites
python -m enrich run --job website

# Run address discrepancy check against official contact pages
python -m enrich run --job address_check

# Target a specific museum slug
python -m enrich run --job price_adult --slug van-gogh-museum

# Resume an interrupted run
python -m enrich run --job price_adult --resume

# Process only records requiring refresh (>540 days old)
python -m enrich run --job price_adult --only-stale
```

### Review Proposals
```bash
# List all pending proposals awaiting bulk approval
python -m enrich proposals
```

### Generate Detailed Reports
```bash
# Print summary breakdown of accepted records vs needs_review categories
python -m enrich report
```

### Auditing
```bash
# Audit all museum homepages for title/H1 identity mismatches
python -m enrich audit-identity

# Spot check 10 randomly sampled accepted records
python -m enrich audit --sample 10
```

---

## 6. Pilot Results: Fallback Mode vs Agentic Mode

A dry run was conducted on **20 pilot museums** (10 curated + 10 randomly sampled with `SEED=42`).

**Models Used:**
- **Extractor:** `google/gemma-4-26b-a4b-it:free` (family: `gemma`)
- **Verifier:** `liquid/lfm-2.5-2.6b:free` (family: `liquid`)

### Comparison Summary:

| Metric | Snippet-Fallback Mode | Agentic Tool-Calling Mode |
|---|---|---|
| **Accepted (Consensus)** | 10 (50%) | 12 (60%) |
| **Needs Review** | 10 (50%) | 8 (40%) |
| **Total Page / Tool Calls** | 64 calls | 52 calls |
| **Average Calls / Museum** | 3.2 calls | 2.6 calls |
| **Total Run Time** | 277.1s (~4.6 min) | 544.1s (~9.1 min) |
| **Average Time / Museum** | 13.8s | 27.2s |

### Failure Reasons Breakdown (Why Records Were Routed to `needs_review`):
1. **Combo Ticket Rejection:** `joods-museum` had only cluster Duotickets (€20) and Combitickets (€30). Caught by the combo rejection gate.
2. **Word Count Limit:** `nationaal-monument-kamp-vught` had a 17-word quote explaining the combined barracks ticket. Caught by the ≤15-word gate.
3. **YoY Price Jump:** `fortresse-holland` increased from €9.50 to €15.00 (+57.9%). Caught by the YoY change threshold gate (>30%).
4. **Renovation Closures:** `museumprinsenhofdelft` accurately recorded as closed with `adult_eur: null` and accepted.
5. **Bot Protection:** `mauritshuis` blocked automated requests via Cloudflare HTTP 403 on robots.txt and was cleanly recorded as `blocked_by_bot_protection`.
6. **Subpage Navigation Advantage:** Agentic mode successfully discovered and accepted tickets on `van-gogh-museum` and `nemo-science-museum` by navigating to `/tickets` subpages via tool calls, whereas fallback mode required the ticket links to be prominent on the homepage.

---

## 7. Production Automation: systemd & Cron

### Configuration (`.env`)
Create a `.env` file in the project root:
```ini
ENRICH_BASE_URL=https://openrouter.ai/api/v1
ENRICH_API_KEY=your_api_key_here
ENRICH_EXTRACTOR_MODEL=google/gemma-4-26b-a4b-it:free
ENRICH_VERIFIER_MODEL=liquid/lfm-2.5-2.6b:free
MUSEUMWIJZER_CONTACT=admin@example.com
```

### systemd Service (`/etc/systemd/system/museumwijzer-enrich.service`)
```ini
[Unit]
Description=Museumwijzer Periodic Metadata Enrichment
After=network.target

[Service]
Type=oneshot
User=museumwijzer
WorkingDirectory=/srv/museumwijzer
EnvironmentFile=/srv/museumwijzer/.env
ExecStart=/srv/museumwijzer/.venv/bin/python3 -m enrich run --job price_adult --only-stale
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### systemd Timer (`/etc/systemd/system/museumwijzer-enrich.timer`)
Runs monthly on the 1st of each month at 03:00 AM:
```ini
[Unit]
Description=Run Museumwijzer enrichment monthly
Requires=museumwijzer-enrich.service

[Timer]
OnCalendar=*-*-01 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```
Enable the timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now museumwijzer-enrich.timer
```

### Cron Alternative (`crontab -e`)
```cron
# Run enrichment on the 1st of every month at 03:00 AM
0 3 1 * * cd /srv/museumwijzer && .venv/bin/python3 -m enrich run --job price_adult --only-stale >> /var/log/museumwijzer-enrich.log 2>&1
```
