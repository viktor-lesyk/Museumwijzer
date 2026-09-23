# Discovery Report: "Welkom in het Museum" Source Website

*Generated: 2026-09-19 · Context: Museumwijzer Phase 1 Data Discovery (§4.2)*

---

## 1. Automated Access and Terms Review (§4.2.1)

### `robots.txt`
- **Location:** `https://welkominhetmuseum.vriendenloterij.nl/robots.txt`
- **Content:**
  ```txt
  User-Agent: *
  Sitemap: https://www.welkominhetmuseum.vriendenloterij.nl/sitemap.xml
  ```
- **Finding:** No `Disallow` directives are present. Automated fetching is not forbidden by `robots.txt`.
- *Note:* The sitemap declaration in `robots.txt` references `www.welkominhetmuseum.vriendenloterij.nl`, but the `www.` subdomain does not have a DNS record. The canonical hostname is `welkominhetmuseum.vriendenloterij.nl` (without `www.`), where `sitemap.xml` is served and lists 203 URLs.

### Terms and Conditions (`/en/voorwaarden/` and `/nl/voorwaarden/`)
- The terms describe the rules for recipients of the physical ticket invitations (distributed via VluchtelingenWerk Nederland in cooperation with Cultuurfonds and VriendenLoterij).
- **Intellectual property clause:**
  > "All copyrights to the content of this site and further content related to this campaign, including all text, images, layout, software or other information, belong to VriendenLoterij or the Prins Bernhard Cultuurfonds."
- **Finding:** There is no prohibition against indexing, automated access, or factual linking.
- **Compliance with Guardrail G-4 ("Facts only"):** The project extracts and stores purely factual data (museum name, province, city, street address, postal code, coordinates, official detail URL, and museum website URL). Creative descriptions, teasers, layout, photos, and branding are neither mirrored nor stored.

---

## 2. Delivery Architecture & Scraping Strategy (§4.2.2)

- **Architecture:** The website is a statically generated Next.js application (`"__N_SSG": true`) backed by Storyblok CMS, hosted on AWS S3 and distributed via CloudFront.
- **Delivery Mechanism:**
  1. The participating museums list page (`/{locale}/deelnemende-musea/`) embeds **all 195 museums** in a single page load inside the `<script id="__NEXT_DATA__">` payload.
  2. Next.js also exposes native, static JSON data endpoints:
     - Full list: `https://welkominhetmuseum.vriendenloterij.nl/_next/data/{buildId}/{locale}/deelnemende-musea.json`
     - Museum detail: `https://welkominhetmuseum.vriendenloterij.nl/_next/data/{buildId}/{locale}/musea/{slug}.json`
  3. CloudFront serves standard `ETag` and `Last-Modified` HTTP headers, supporting cache validation via conditional requests (`If-None-Match`).
- **Public Endpoints Guarantee:**
  - The scraper fetches **only** publicly accessible Next.js pages and routes:
    - Initial discovery: `https://welkominhetmuseum.vriendenloterij.nl/nl/deelnemende-musea/` (reads `buildId` and slug index from `<script id="__NEXT_DATA__">`).
    - Standard Next.js client-side data routes: `https://welkominhetmuseum.vriendenloterij.nl/_next/data/{buildId}/nl/musea/{slug}.json`.
    - Standard HTML fallback: `https://welkominhetmuseum.vriendenloterij.nl/nl/musea/{slug}/`.
  - The scraper does **not** invoke any private, hidden, or undocumented CMS endpoints (e.g. `/umbraco/api/...` is completely absent; the site uses Storyblok CMS distributed via static Next.js artifacts on AWS CloudFront). All ingested data is strictly identical to what a standard browser receives when navigating the public site.
- **Conclusion & Recommended Scraper Approach:**
  - We do **not** need a headless browser (Playwright is unnecessary).
  - The scraper fetches the list page HTML once to read the active `buildId` and extract the 195 museum slugs, then politely fetches the detail JSON files with rate limiting (≤ 1 request per second) and cache headers.


---

## 3. Detail Page Fields & Address Extraction (§4.2.3)

Inspection of detail pages across the dataset revealed the following field availability:

| Field | Source Location in JSON | Availability | Quality / Structure |
|---|---|---|---|
| **Name** | `story.name` | 100% | Clean plain string (e.g. `"Huis Zypendaal"`) |
| **Slug** | `story.slug` | 100% | Stable identifier (e.g. `"huis-zypendaal"`) |
| **Province** | `story.content.tags[].name` | 100% | Single tag matching one of the 12 Dutch provinces |
| **Street Address** | Rich text contact block | >95% | Line preceding the Dutch postcode |
| **Postal Code** | Rich text contact block | >95% | Standard Dutch 4 digits + 2 letters format (`NNNN AA`) |
| **City** | Rich text contact block | >95% | Next to or after postal code; verifiable via PDOK Locatieserver |
| **Coordinates** | Derived via PDOK | High precision | PDOK Locatieserver returns exact `lat`/`lon` from postal code + house number |
| **Official URL** | `https://welkominhetmuseum.vriendenloterij.nl/nl/musea/{slug}/` | 100% | Generated from slug |
| **Museum Website** | Link marks in contact block | >90% | External URL linking to the museum's own website |
| **Opening Hours** | Rich text block | Rare / Not standardized | Detail pages instruct visitors to check the museum's website |

---

## 4. Card Date Meaning (§4.2.4)

- **Observed Date:** The date displayed on cards (e.g., `"19 june 2026"`, `"5 september 2023"`) corresponds directly to `story.first_published_at` or `story.created_at` in Storyblok CMS.
- **Meaning:** It represents the CMS publishing timestamp when the article entry was created or first published by the site editors.
- **Implication:** It is **not** an expiration date, participation end date, or campaign validity cutoff. As required by §5.1, `source_date_raw` will be recorded internally for change tracking, but will **not** be presented in the UI as a participation date.

---

## 5. Multilingual Structure (§4.2.5)

- **Available Locales:** The site actively supports 6 locales:
  - `nl` (Nederlands)
  - `en` (English)
  - `uk` (Українська)
  - `ar` (العربية)
  - `fa` (فارسی)
  - `ti` (ትግርኛ)
- **Consistency:**
  - Exactly 195 museums are present in all language versions.
  - Museum names and slugs are **100% identical** across `nl`, `en`, and `uk` (0 differences).
  - Addresses and website links are shared across locales; only promotional body copy (which we do not use) and interface navigation vary.
- **Scraper Recommendation:** Scrape the Dutch (`nl`) version as the canonical source.

---

## 6. Three Sample Museums

Below are the factual records parsed from the source for three representative museums, including PDOK geocoding results:

### Sample 1: Huis Zypendaal
- **Slug:** `huis-zypendaal`
- **Name:** `Huis Zypendaal`
- **Province:** `Gelderland`
- **Address Line:** `Zijpendaalseweg 44`
- **Postal Code:** `6814 CL`
- **City:** `Arnhem`
- **Coordinates (PDOK):** `lat: 51.99923772, lon: 5.89302289`
- **Official URL:** `https://welkominhetmuseum.vriendenloterij.nl/nl/musea/huis-zypendaal/`
- **Museum Website:** `https://www.glk.nl/zypendaal/huis-zypendaal`
- **CMS Date (raw):** `2026-06-19T08:30:30.104Z`

### Sample 2: Van Gogh Museum
- **Slug:** `van-gogh-museum`
- **Name:** `Van Gogh Museum`
- **Province:** `Noord-Holland`
- **Address Line:** `Museumplein 6`
- **Postal Code:** `1071 DJ`
- **City:** `Amsterdam`
- **Coordinates (PDOK):** `lat: 52.35792475, lon: 4.88132267`
- **Official URL:** `https://welkominhetmuseum.vriendenloterij.nl/nl/musea/van-gogh-museum/`
- **Museum Website:** `https://www.vangoghmuseum.nl/nl`
- **CMS Date (raw):** `2022-11-14T18:06:06.415Z`

### Sample 3: Watersnoodmuseum
- **Slug:** `watersnoodmuseum`
- **Name:** `Watersnoodmuseum`
- **Province:** `Zeeland`
- **Address Line:** `Weg van de Buitenlandse Pers 5`
- **Postal Code:** `4305 RJ`
- **City:** `Ouwerkerk`
- **Coordinates (PDOK):** `lat: 51.61742265, lon: 3.98282179`
- **Official URL:** `https://welkominhetmuseum.vriendenloterij.nl/nl/musea/watersnoodmuseum/`
- **Museum Website:** `https://watersnoodmuseum.nl/`
- **CMS Date (raw):** `2022-11-09T08:36:07.480Z`

---

## 7. Next Steps (Phase 1 Pipeline Implementation)

1. Implement Python pipeline in `scraper/`:
   - `fetch.py`: fetches the list and detail pages with caching, rate limiting (1 req/sec), and polite User-Agent.
   - `parse.py`: extracts factual fields from Storyblok JSON blocks.
   - `geocode.py`: queries PDOK Locatieserver using postal code and street address, with local caching in `data/geocode-cache.json`.
   - `normalise.py`: handles unicode normalization (NFC) and whitespace cleaning.
   - `validate.py`: enforces §8.2 validation rules (count, completeness, valid coordinates in NL).
2. Save raw fixtures in `scraper/tests/fixtures/` for repeatable offline tests.
3. Generate the first `data/museums.json` and diff tracking.
