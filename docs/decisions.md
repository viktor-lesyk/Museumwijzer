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

## ADR 009: Client-Side Priority List Architecture (LocalStorage & URL Hash Sharing)
- **Context:** §6.3 requires personal priority list, reordering, visited status, notes, shareability, export/import, print styles without any backend server.
- **Decision:** Use `localStorage` for offline client persistence and URL hash (`#list=slug1,slug2,...`) for serverless sharing.
- **Rationale:** The static site remains backendless and private. The hash is processed entirely client-side and never transmitted to web servers in HTTP requests. When opening a shared hash, the app prompts "Save to my list" rather than silently overwriting existing user data.

## ADR 010: Privacy-Preserving "Near Me" Geolocation & City Centroid Fallback
- **Context:** §6.4 requires client-side distance calculation and fallback when geolocation is denied or unavailable, with zero third-party geocoding calls from the browser.
- **Decision:** Use browser `navigator.geolocation` only on explicit user click, computing Haversine distance in browser JavaScript. Pre-calculate mean city centroids at build time in Astro for fallback reference cities.
- **Rationale:** Strict privacy guarantee (G-7). Zero external network calls. Users can calculate distance from any city even without granting GPS permissions.

## ADR 011: Ukrainian Locale (/uk/) & Translation Review Flag
- **Context:** §6.6 requires Ukrainian support with separate path `/uk/` alongside Dutch and English.
- **Decision:** Generate `/uk/`, `/uk/about/`, `/uk/list/`, and `/uk/museum/<slug>/` with localized UI strings, Ukrainian `hreflang`, and language switcher. Keep museum names untranslated.
- **Review Requirement:** Machine-drafted strings are documented with `REVIEW_FLAG` in `site/src/i18n/ui.ts` for native speaker review before launch.

## ADR 012: Site-Wide Notice Banner Architecture
- **Context:** A mechanism is needed to alert visitors if the programme ends or changes, or if data is older than 30 days.
- **Decision:** Governed by `data/notice.json` (for manual announcements) and `data/meta.json` (for automated 30-day stale data warnings rendered at build time).

## ADR 013: Dutch Places Dataset & PDOK Postcode Resolution for Distance Filtering
- **Context:** Users wanting to calculate distances without sharing GPS (or from a different town like Giethoorn that has no participating museum, or via 4-digit/6-digit postal code) need accurate coordinates.
- **Decision:**
  1. Ship a compact dataset of all 2,503 Dutch woonplaatsen centroids (`/data/places.json`, ~100 KB uncompressed, ~25 KB gzipped), preloaded lazily when location controls are engaged.
  2. Provide live lookup against the official Dutch open data PDOK Locatieserver (`api.pdok.nl`, permitted by CSP) for postal codes (e.g. `8355`, `1012`) and alternate place spellings.
  3. Reverse-geocode GPS coordinates to the nearest Dutch woonplaats to explicitly display the detected location (e.g., `Gedetecteerde locatie: nabij Delft (52.00° N, 4.36° E)`).
  4. Allow filtering by maximum distance (10 km, 25 km, 50 km, 100 km).
- **Rationale:** Fully offline-capable for all Dutch towns and villages, instantaneous lookup without network requests for places, open Dutch government fallback for postcodes, and total transparency on what location was detected.

## ADR 014: Free-Tier LLM Ratings Enrichment & Numerical Reviews Display
- **Context:** Users need review scores and volume to decide which museums to visit. Direct scraping (e.g. TripAdvisor) suffers 403 blocks, while Google Places API incurs billing risk on Google Cloud.
- **Decision:** Use local free-tier LiteLLM proxy (`free-lite` / Gemini Flash-Lite) to batch-extract public Google review ratings and review counts across all participating museums into `data/enrichment/ratings.json`.
- **Rationale:** 100% free with zero billing risk, fast offline build, avoids runtime API calls from browser, and avoids duplicate external links on museum pages.

## ADR 015: Client-Side "Already Visited" Museum Marking & Filter
- **Context:** Users who have already visited certain museums need an effortless way to mark them as visited and filter them out of their search and map results.
- **Decision:**
  1. Add a quick `✓` toggle button directly on every museum card media overlay and on detail page headers.
  2. Store visited museum slugs in `localStorage` under key `museumwijzer_visited_museums`.
  3. Provide a sticky toolbar toggle button `👁️‍🗨️ Verberg bezocht` with persistent preference stored under `museumwijzer_hide_visited`.
  4. When active, visited museums are hidden from both the grid and the country map view, and the result count updates with transparent counts (e.g. `190 musea gevonden (4 bezocht verborgen)`).
- **Rationale:** Fully client-side, private, instant, zero account creation or backend needed, and preserves state across sessions.
