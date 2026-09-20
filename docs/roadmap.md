# Museumwijzer Roadmap

This document outlines the strategic roadmap for Museumwijzer, from the initial v1 release through planned investigations and potential future scope expansions.

---

## 1. Version 1.0 — Focused Programme Guide

The primary goal of Museumwijzer v1 is to provide a fast, accessible, privacy-friendly, and independent directory strictly dedicated to the **"Welkom in het Museum"** programme (195 participating museums across the Netherlands).

### v1 Principles:
- **Programme Focus:** Every museum listed participates in the "Welkom in het Museum" initiative. It is explicitly **not** a general or exhaustive directory of all Dutch museums.
- **Fact-Only Data:** Address, geocoordinates, municipality, province, and official website links verified against official records and PDOK. No copyrighted creative descriptions, teasers, or imagery.
- **Privacy & Performance:** Zero trackers, zero third-party fonts, zero runtime external geocoding requests. Pre-rendered static pages (Astro) with progressive enhancement.
- **Languages:** Dutch (`/nl/`), English (`/en/`), and Ukrainian (`/uk/`).
- **Core Utility:** Diacritic- and typo-tolerant search, province and city filters, browser geolocation ("Near Me"), and a client-side Priority List with offline `localStorage` persistence, shareable URL hashes, and export/print capabilities.

---

## 2. Post-v1: Planned Data Enrichment Spike

While v1 relies strictly on core factual address data, users often need additional logistical context (such as opening days, whether a museum is closed on Mondays, and direct links to visitor information).

### 2.1 Opening Hours & Days via OpenStreetMap / Wikidata
- **Investigation Scope:** Conduct a spike to evaluate the coverage and quality of opening days/hours tags (`opening_hours=*` in OSM, or `P3020` / opening hours properties in Wikidata) across the 195 participating museums.
- **Mandatory Licence & Attribution Check (Pre-requisite):**
  - **OpenStreetMap Data:** Governed by the Open Database License (ODbL). Any derived database or integration must respect ODbL attribution and share-alike requirements.
  - **Wikidata:** Released under Creative Commons Public Domain Dedication (CC0).
  - *Requirement:* A formal legal and licensing assessment must be completed and documented before ingesting or distributing external dataset fields in `data/museums.json`.
- **Deep Links to Practical Information:**
  - Investigate collecting or verifying deep links directly to each museum's official visiting hours and admission pricing page (e.g. `https://museum.example/plan-je-bezoek`), reducing navigation friction for visitors.
  - Must include automated sanity checks (e.g., domain match with `museum_website` and HTTP 200 verification).

> [!IMPORTANT]
> **Status:** Enrichment is deferred post-v1. No external scraping, OSM/Wikidata queries, or enrichment code should be added to the production pipeline until this spike is authorized.

---

## 3. Criteria for Widening to a General Dutch Museum Catalogue

Museumwijzer may eventually broaden its scope beyond the "Welkom in het Museum" initiative to encompass all museums across the Netherlands. However, broadening scope introduces substantial maintenance, data quality, and user confusion risks.

To proceed with widening, the following criteria must be satisfied:

1. **User Feedback & Validated Need:**
   - Qualitative and quantitative feedback from users indicating strong demand for a lean, ad-free, high-performance general museum directory.
2. **Authoritative & Sustainable Data Sources:**
   - Identification of an authoritative, continuously updated, and legally open upstream data source (e.g., Museumvereniging / Museumkaart open datasets, RCE/OpenCultuurData, or mature OSM/Wikidata queries).
   - The data source must provide stable identifiers and reliable geocoding without requiring fragile HTML scraping of private entities.
3. **Automated Maintenance & Quality Assurance:**
   - Scalable automated pipeline capable of handling ~1,000+ institutions with robust automated validation rules, duplicate detection, and manageable override workflows.
4. **Unambiguous Programme Distinction (UX & Legal):**
   - The user interface must preserve complete clarity between museums participating in specific free initiatives (such as Welkom in het Museum or Museumkaart) and general admission venues, preventing visitors from arriving with invalid ticket expectations.
