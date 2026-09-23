# Museumwijzer Price Enrichment Recheck Runbook

Operational guide for manually refreshing museum admission prices (~yearly maintenance cycle).

---

## 1. Policy: Strictly Manual Execution

> [!CAUTION]
> **DO NOT AUTOMATE THIS COMMAND.**
> Never add `python -m enrich recheck` to cron, systemd timers, GitHub Actions, or scheduled cloud workers.

### Why manual-only?
1. **Zero Billing / Cost Guardrail**: Museumwijzer operates on a strict zero-cost architecture with no paid models or credit cards attached. Free-tier providers periodically change their policies or model availability. Human oversight guarantees no paid APIs are inadvertently invoked.
2. **OpenRouter Model Rotation**: Free models on OpenRouter (models with the `:free` suffix) rotate or deprecate every few months. An unattended job would fail or throw errors when a model ID retires.
3. **Bot Protection & Anti-Scraping Churn**: Cloudflare, Incapsula, and perimeter defenses change across cultural institution websites. A sudden wave of bot protection blocks must be evaluated by a human engineer, not silently retried in loops.
4. **Website Redesigns**: Dutch museums periodically revamp ticket pages and CMS URLs. Human review ensures pricing structures (such as online vs door splits or seasonal variants) are correctly mapped.

---

## 2. Pre-Run Verification Checklist

Before running any enrichment or recheck commands, verify each component of the pipeline:

### Checklist
- [ ] **1. LiteLLM Local Proxy (`free-lite`)**:
  - Ensure the local proxy is running:
    ```bash
    curl -s http://localhost:4000/health
    ```
  - Verify `LITELLM_FREE_LITE_MODEL` in `.env` is set (e.g. `free-lite`).
- [ ] **2. OpenRouter Free Model Active**:
  - OpenRouter rotates `:free` models. Check currently active free models via their API:
    ```bash
    curl -s https://openrouter.ai/api/v1/models | grep -o '"id":"[^"]*:free"'
    ```
  - Pick an active, capable free model (e.g. `nvidia/nemotron-3-super-120b-a12b:free`, `meta-llama/llama-3.3-70b-instruct:free`, or similar).
  - Update `OPENROUTER_FREE_MODEL` in `.env` if necessary.
- [ ] **3. Tavily Free Tier Status**:
  - Verify Tavily free tier is still active (1,000 free search credits/month, no credit card required).
  - Verify remaining monthly quota in `.cache/enrichment/search_quota.json`.
- [ ] **4. Zero-Billing Safeguards in `.env`**:
  - Ensure no billing-metered keys or flags are set:
    - `USE_BRAVE_SEARCH` must NOT be `true` (Brave metered card billing is forbidden).
    - `OPENROUTER_FREE_MODEL` MUST end with `:free`.
    - `LITELLM_FREE_LITE_MODEL` MUST contain `free`.

---

## 3. Execution Workflow

### Step 1: Run in Dry-Run Mode First
Always perform a dry run to inspect changes without altering files on disk.

```bash
# Recheck all museums (dry-run is default)
.venv/bin/python -m enrich recheck --dry-run

# Or test a small subset or specific museums first:
.venv/bin/python -m enrich recheck --slugs rijksmuseum,van-gogh-museum,mauritshuis --dry-run
.venv/bin/python -m enrich recheck --limit 10 --dry-run
```

### Step 2: Evaluate the Informational Delta Report
Review the summary printed at the conclusion of the run:

```text
=== ENRICHMENT RECHECK INFORMATIONAL REPORT ===
Execution Mode:       DRY RUN (no files modified)
Total Rechecked:      195
  • Unchanged:        130
  • Price Changed:    12
  • Status Changed:   1
  • Newly Resolved:   3
  • Unavailable:      2
  • Still Unresolved: 47
Direct URL Hits:      124 (no search quota used)
Search Fallbacks:     71
Tavily Searches Used: 24 (Month total: 398/1000)
```

#### What to look for:
1. **Price Delta Distribution**:
   - Are price changes within normal inflation expectations (e.g. +€0.50 to +€2.50)?
   - Did any price jump dramatically (e.g. €15 to €40)? If so, inspect the quote and reasoning to check whether a bundled tour or family ticket was extracted by mistake.
2. **Direct URL Hit Rate**:
   - The direct URL verification checks stored `source_url`s (HTTP 200, no redirect away from ticketing, pricing keywords present) and bypasses search. A high hit rate saves search quota.
3. **Newly Unavailable Records**:
   - If a museum previously accepted now shows `became_unavailable`, check the failure reason (e.g. 404, CMS redesign, bot protection, or model disagreement).
4. **Unexpected Bulk Changes**:
   - If a large batch of museums from a shared domain (e.g. `glk.nl`) fails or changes simultaneously, verify whether the domain changed its structure.

### Step 3: Apply the Updates
Once the dry-run report is approved:

```bash
# Apply changes to data/enrichment/prices.json and data/enrichment/needs_review.json
.venv/bin/python -m enrich recheck --apply
```

### Step 4: Rebuild the Static Site
Rebuild the Astro site to ensure all static pages and price cards compile properly:

```bash
cd site
npm run build
```

Verify that all pages build without errors (600+ pages built in ~3s).

### Step 5: Run Acceptance Tests

```bash
.venv/bin/pytest
```

Ensure all tests pass (unit tests, phase 2 acceptance, phase 3 acceptance, hygiene, and recheck tests).

---

## 4. Definition of "Done"

A recheck cycle is complete when:
1. `data/enrichment/prices.json` and `data/enrichment/needs_review.json` have been updated with fresh timestamps and verified prices.
2. The static site builds cleanly (`npm run build`).
3. All pytest test suites pass.
4. Git diff is clean, reviewed, and committed to git (focused commit).
