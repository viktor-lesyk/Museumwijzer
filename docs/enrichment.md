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

## 3. Deterministic Code Gates

Before invoking the verifier model, code gates validate the extraction:
1. **Domain & Link Provenance:** `source_url` domain must match `museum_website` domain or subdomain, or be reached by following internal links from the root website.
2. **Literal Verbatim Presence:** The claimed numerical price and supporting quote (≤ 15 words) must appear verbatim in the page text.
3. **Admission Validity:**
   - Paid: `adult_eur` between €1.00 and €45.00; `admission: "paid"`.
   - Free: Requires an explicit quote proving free general admission for all adults (free-for-children does not qualify); `adult_eur: 0.0`.
4. **Combo / Duo Rejection:** Quotes containing `"combo"`, `"combi"`, `"duo"`, or `"gezamenlijk"` are rejected to `needs_review`.
5. **YoY Change Check:** If a price changes by >30% compared to the previous run, it is flagged for human review.

---

## 4. How to Add a New Enrichment Job

Jobs are defined declaratively in YAML under `enrich/jobs/<job_name>.yaml`.

### Example Job Definition (`enrich/jobs/closure_status.yaml`):
```yaml
field: closure_status
title: "Museum Closure and Renovation Status"
description_en: >-
  Determine whether the museum is currently open to visitors, temporarily closed
  for renovation/rebuilding, or permanently closed.
output_schema:
  type: object
  properties:
    is_open:
      type: boolean
    closure_reason:
      type: ["string", "null"]
    expected_reopening:
      type: ["string", "null"]
    quote:
      type: ["string", "null"]
    source_url:
      type: ["string", "null"]
  required: ["is_open"]
plausibility:
  forbidden_quote_keywords: []
refresh_interval_days: 90
```

Future jobs such as `opening_days`, `closure_status`, or `categories` can be added simply by creating a YAML specification in `enrich/jobs/` and implementing any job-specific deterministic gate checks.

---

## 5. CLI Usage & Commands

The enrichment framework provides three primary commands via `python -m enrich`:

### Run Enrichment Job
```bash
# Run adult ticket enrichment on all museums in agentic mode
python -m enrich run --job price_adult --mode agentic

# Run on a specific museum in fallback mode
python -m enrich run --slug van-gogh-museum --mode fallback

# Resume an interrupted run (skipping museums already in prices.json)
python -m enrich run --job price_adult --resume

# Process only records requiring refresh (>540 days old)
python -m enrich run --job price_adult --only-stale
```

### Identity Audit (`audit-identity`)
Audits all active museum records by fetching each museum's homepage, extracting `<title>` and `<h1>`, and confirming that distinctive tokens from the museum name and city match:
```bash
python -m enrich audit-identity
```

### Spot Check Audit (`audit`)
Randomly samples accepted rows from `data/enrichment/prices.json` for human inspection:
```bash
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
