# Architecture and Product Decisions

## ADR 001: Scraper Extraction Strategy
- **Context:** §4.2 requires preferring the least intrusive method for retrieving museum data: server-rendered HTML/URL pagination, public JSON endpoints, or headless browser (Playwright) as last resort.
- **Decision:** Use Next.js SSG JSON endpoints (`/_next/data/{buildId}/nl/...`) discovered dynamically from the list page HTML.
- **Rationale:** The source website is built with Next.js SSG and Storyblok CMS. It serves pure JSON files for all routes directly via CloudFront. This avoids heavy headless browser dependencies (Playwright), consumes minimal bandwidth, respects ETag caching, and guarantees 100% data fidelity.

## ADR 002: Canonical Source Language
- **Context:** The source website provides content in 6 languages (`nl`, `en`, `uk`, `ar`, `fa`, `ti`).
- **Decision:** Use Dutch (`nl`) as the canonical data source for scraping.
- **Rationale:** Analysis revealed that museum names, slugs, addresses, and external links are 100% identical across languages. The Dutch version is the primary source of truth for Dutch museum names and Dutch address formatting.

## ADR 003: Handling of Card Publication Dates
- **Context:** Cards on the source site display dates such as "19 june 2026" whose meaning was unverified.
- **Decision:** Store `source_date_raw` in `museums.json` for internal diffing and freshness checks, but do not display it in the user-facing UI as a participation date.
- **Rationale:** Deep inspection of the Storyblok CMS payload showed that these dates correspond to `first_published_at` or `created_at` CMS timestamps. They do not represent campaign validity or museum participation deadlines. Displaying them to users would cause confusion.

## ADR 004: Geocoding via PDOK Locatieserver
- **Context:** Coordinates and standardized municipality/city data are required for distance sorting and search filtering without third-party browser tracking.
- **Decision:** Geocode addresses during the data pipeline using the PDOK Locatieserver (`api.pdok.nl/bzk/locatieserver`), caching all results in `data/geocode-cache.json`.
- **Usage & Licensing Terms:**
  - **Licence:** PDOK data is open government data, primarily derived from the BAG (Basisregistratie Adressen en Gebouwen) and Bestuurlijke Grenzen, distributed under **Creative Commons Attribution 4.0 International (CC BY 4.0)** and Dutch open data regulations (Wet hergebruik van overheidsinformatie).
  - **Attribution Requirement:** Attribution must cite Kadaster / PDOK without implying governmental endorsement: *"Geodata: PDOK / Kadaster (CC BY 4.0 / BAG)"*. This will be included in the site footer, data source notices, and README.
  - **Fair Use:** PDOK is open and free to all users. To ensure responsible civic usage, the scraper caches all geocoding results persistently in `data/geocode-cache.json`, only queries for new or changed museum addresses, and throttles requests to ≤ 1 request per second.

## ADR 005: Front-End Stack Choice (Astro Static Output)
- **Context:** §7 suggests choosing either Astro or Vite + TypeScript without a UI framework.
- **Decision:** Use Astro with static output (`output: 'static'`).
- **Justification (<=5 lines):**
  1. Astro pre-renders 100% static HTML for all 195 museums at build time, ensuring full readability without JavaScript (progressive enhancement).
  2. Zero client-side JavaScript runtime framework overhead (only ~8 KB of vanilla client JS for instant search and filtering).
  3. Built-in file-based i18n routing (`/nl/`, `/en/`) with automatic `hreflang` tags and structured metadata.
  4. Direct JSON imports from `data/museums.json` and `data/meta.json` with strict build-time type checking.
  5. Completely self-contained build output (`dist/`) requiring no server runtime, cookies, or external CDN assets.

## ADR 006: Common City Display Name vs Legal BAG Name
- **Context:** PDOK Locatieserver (BAG) returns formal legal names such as `'s-Gravenhage` and `'s-Hertogenbosch`, whereas the public and source website use `Den Haag` and `Den Bosch`.
- **Decision:** Display the common, colloquial city name (`Den Haag`, `Den Bosch`) in the UI, card listings, and city dropdown. Store the formal Kadaster woonplaats in `pdok_woonplaats` and administrative municipality in `municipality` for sanity checks.
- **Search Compatibility:** Search and client filters normalize queries and card metadata against both names so searching for either `Den Haag` or `'s-Gravenhage` finds the exact same results.

## ADR 007: Temporary Closures and Renovations Advisory Banner
- **Context:** Participating museums may be temporarily closed for renovation (e.g. Museum Prinsenhof Delft until late 2026). Participation does not guarantee the doors are currently open.
- **Decision:** Display a prominent, objective advisory notice on all museum detail pages: *"Check the museum's website for current opening hours and closures"* (*"Controleer altijd de website van het museum voor actuele openingstijden en eventuele tijdelijke sluitingen"*).

## ADR 008: Outbound Directions Links
- **Context:** Users often save museums to personal map lists (such as Google Maps) or need direct navigation.
- **Decision:** Provide plain outbound links for OpenStreetMap, Google Maps (`https://www.google.com/maps/search/?api=1&query=...`), and Apple Maps (`https://maps.apple.com/?q=...`) using encoded museum name, address, and city.
- **Privacy Compliance:** No third-party map embeds, iframes, or tracking scripts are loaded; navigation occurs purely when the user clicks an external link.
