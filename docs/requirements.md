# Museumwijzer (working name) — Product Requirements

An unofficial, free, non-commercial finder for museums that take part in the "Welkom in het Museum" programme in the Netherlands.

Version 1.0 draft · Owner: Viktor · Intended reader: an AI coding assistant (e.g. Claude Code) and the owner

---

## 0. How to use this document (instructions for the AI builder)

1. Read the whole document before writing code.
2. Work in the phases in §12. At the end of each phase, stop, summarise what you did, and wait for the owner's review.
3. Do **discovery before code** (§4.2). Do not assume anything about the source website that is marked *(unverified)*. Check it.
4. Prefer boring, small, well-supported technology. Fewer dependencies is better. Justify each dependency in one line in the README.
5. Never commit secrets, personal data, hostnames, IP addresses or details of the owner's private infrastructure.
6. Never add tracking, analytics, ads, or third-party requests at runtime (see §3).
7. If any requirement here conflicts with the legal and ethical guardrails in §3, the guardrails win. Flag the conflict to the owner.
8. When something is ambiguous, pick the simplest option, note the decision in `docs/decisions.md`, and continue. Ask the owner only for decisions listed in §13 or anything that needs an account or money.

---

## 1. Summary

A public website that helps people in the Netherlands:

- discover that the "Welkom in het Museum" programme exists and where to request tickets (on the official site),
- quickly check **whether a specific museum participates**,
- **search by name and by city**, filter by province, and sort by distance from them,
- build and share a **personal priority list** of museums to visit.

### Why this is needed

The official participating-museums page (https://welkominhetmuseum.vriendenloterij.nl/en/deelnemende-musea/) is paginated (about 22 pages of 8 museums), can be filtered only by province, has no search, no city, no map and no way to save a shortlist.

### Goals

- G1. A visitor can find out if a museum participates in under 10 seconds.
- G2. Works well on a phone, in Dutch, English and Ukrainian (more languages later).
- G3. Stays up to date automatically, with almost no maintenance.
- G4. Open source, easy for others to contribute to.
- G5. Respectful of the programme organisers, the museums and the users' privacy.

### Non-goals

- Not an official service. Not affiliated with the organisers.
- Does not issue, request or sell tickets. Does not judge who is eligible.
- No accounts, no backend server, no database.
- No ads, affiliate links, donations or analytics in v1.
- Does not copy museum descriptions, photos, logos or other creative content from the source.

---

## 2. Users and scenarios

| Persona | Scenario | What they need |
|---|---|---|
| Newcomer | "Is there a free museum programme? How do I get tickets?" | 3-line explanation on the home page and a prominent link to the official ticket request |
| Checker | "Does Museum X take part?" | Fast name search, a clear yes, or "not in the current list" plus a link to the official list |
| Planner | "What is near me / in my city?" | City search, province filter, sort by distance |
| List-maker | "Which ones do I want to visit first?" | Ordered priority list, visited marks, export and print |
| Helper (volunteer, community worker) | "I want to send someone a shortlist" | A shareable link that reproduces the list, without accounts |

---

## 3. Legal and ethical guardrails (mandatory)

The owner is not a lawyer and this document is not legal advice. These rules exist to keep the project respectful and low-risk.

- **G-1 Name and branding.** The product name, domain, logo and colour scheme must not include or imitate "VriendenLoterij", "VluchtelingenWerk", "Cultuurfonds" or "Welkom in het Museum". Plain descriptive text such as "unofficial guide to the Welkom in het Museum programme" is fine. No logos of the organisers or museums.
- **G-2 Disclaimer.** Every page footer and the About page must state that the site is independent and unofficial, that the information may be out of date, and that the official source is the organisers' website (with link). Texts in Appendix B.
- **G-3 Attribution.** Show "Data source: welkominhetmuseum.vriendenloterij.nl" with a link, and the date of the last data update, on every page.
- **G-4 Facts only.** Store and display only factual fields: name, province, city, address, coordinates, link to the official museum page, optional museum website. Do **not** copy or mirror the source's descriptions, teaser text, photos or page layout. Do not hotlink images from the source or its CDN. Every museum entry links to its official page.
- **G-5 Tickets and eligibility.** Send users to the official request page for tickets. Do not collect ticket requests or any personal data. Do not state or interpret eligibility rules; link to the official "How it works" and FAQ pages instead.
- **G-6 Scraper conduct.** Read and respect `robots.txt` and the terms. Only use pages or endpoints that the public website itself uses in a normal browser visit. Do not bypass authentication, rate limits or bot protection. At most 1 request per second, identify with a descriptive User-Agent that includes the project URL and a contact email, cache with ETag / If-Modified-Since where supported, run at most weekly. If `robots.txt` or the terms disallow automated access, **stop and ask the owner**.
- **G-7 Privacy.** No personal data collected. No cookies. No analytics in v1. No third-party requests at runtime (self-host fonts and assets; no CDNs). "Near me" uses the browser's geolocation entirely client-side and the position is never sent anywhere. The priority list lives only in the user's browser (localStorage) or in a share link they create.
- **G-8 Non-commercial.** No ads, sponsorship, affiliate links or paid features.
- **G-9 Contact and takedown.** A visible contact address and GitHub issues link. If the organisers or a museum ask for a change or removal, it must be possible to do that quickly. Provide a documented one-step way to unpublish the site.
- **G-10 Outreach.** Before public launch the owner will contact the organisers (Appendix A). Do not launch publicly until the owner confirms this step is done. Building and testing can proceed in the meantime.

---

## 4. Data source

### 4.1 What is known *(observed on 2026-09-19; anything not listed is unverified)*

- List page: `https://welkominhetmuseum.vriendenloterij.nl/en/deelnemende-musea/`
- The site appears to be built with Next.js; images are served from Storyblok's CDN (a hint of a headless CMS, *unverified*).
- 22 pages, 8 cards per page (about 170 museums; the page text says "more than 150").
- Each card shows: name, province, a date such as "19 june 2026" (**meaning unknown**), a teaser sentence, and a link to a detail page at `/en/musea/<slug>/`.
- Province filter chips exist (12 provinces). The `/en/` prefix suggests other language versions (e.g. `/nl/`) *(unverified)*.
- Official ticket request page: `https://uitnodiging.vriendenloterij.nl/vluchtelingen?lang=EN`
- Campaign terms: `https://welkominhetmuseum.vriendenloterij.nl/en/voorwaarden/`
- The list cards do **not** show the city. It may be on detail pages *(unverified)*.

### 4.2 Discovery step (do this first, before writing the scraper)

1. Fetch and read `robots.txt` and the terms page. Summarise anything relevant to automated access or reuse. Stop and ask the owner if anything restricts it.
2. Work out how the list is delivered, preferring the least intrusive option in this order:
   1. server-rendered HTML that supports pagination via a URL parameter,
   2. a public JSON endpoint that the site itself calls in a normal browser visit,
   3. a headless browser (Playwright) as a last resort.
3. Inspect three detail pages. Record which fields exist (address, city, website, opening information, etc.).
4. Determine what the card date means (added, updated, end of participation, something else).
5. Check whether the site has Dutch and other language versions and how museum names differ between them.
6. Write findings to `docs/discovery.md` with three sample museums, and pause for owner review.

---

## 5. Data model and pipeline

### 5.1 Output file: `data/museums.json`

```json
{
  "generated_at": "2026-09-19T06:00:00Z",
  "source": {
    "name": "Welkom in het Museum",
    "url": "https://welkominhetmuseum.vriendenloterij.nl/en/deelnemende-musea/"
  },
  "museums": [
    {
      "slug": "huis-zypendaal",
      "name": "Huis Zypendaal",
      "province": "Gelderland",
      "city": "Arnhem",
      "address": { "street": "", "postcode": "", "city": "" },
      "lat": 0.0,
      "lon": 0.0,
      "official_url": "https://welkominhetmuseum.vriendenloterij.nl/en/musea/huis-zypendaal/",
      "museum_website": null,
      "source_date_raw": "19 june 2026",
      "first_seen": "2026-09-19",
      "last_seen": "2026-09-19"
    }
  ]
}
```

- `slug` comes from the source URL and is the stable ID (used in share links).
- Fields not available from the source are `null`, never guessed. The example values above are placeholders.
- `source_date_raw` is stored but **not displayed** until its meaning is understood.
- Museums no longer listed at the source are dropped from `museums.json` and recorded in `data/changelog.json` (added / removed, with dates) for a "What's new" section and to help debug scraper problems.

### 5.2 Other data files

- `data/overrides.yaml`: manual corrections (city, coordinates, alias names), applied after scraping, reviewed via pull requests.
- `data/city-aliases.yaml`: e.g. "Den Haag" = "'s-Gravenhage", "Den Bosch" = "'s-Hertogenbosch".
- `data/geocode-cache.json`: coordinates per museum, so geocoding only runs for new or changed addresses.

### 5.3 Pipeline steps

1. **Fetch** list and detail pages politely (G-6). Save raw responses to a git-ignored cache for debugging.
2. **Parse** into the schema. Parsing lives in one module with fixtures from real pages, so site changes are easy to spot.
3. **Normalise** whitespace, unicode (NFC), province names, and city names.
4. **Geocode** new or changed addresses with the PDOK Locatieserver (free Dutch government geocoder). Fall back to name + city. Anything that cannot be geocoded is listed in the run report for manual override.
5. **Apply overrides.**
6. **Validate** (see §8.2). On failure, keep the previous `museums.json`, do not deploy, and raise an alert.
7. **Diff** against the previous file and write `changelog.json`.
8. **Write** `museums.json` with stable ordering (sorted by slug) so git diffs are meaningful.

### 5.4 Suggested tooling

Python 3.12, `httpx` or `requests`, `selectolax` or BeautifulSoup, `pydantic` for schema validation, `pytest`. Playwright only if discovery shows it is required.

---

## 6. Front-end requirements

### 6.1 Pages

- **Home / Finder:** short explainer (max 3 lines), prominent "Request tickets on the official site" button, search box, filters, results.
- **Museum detail (`/museum/<slug>`):** name, province, city, address, link to the official page, link to the museum's website if known, "Add to my list", small map link (opens the user's map app or OpenStreetMap by link only).
- **My list:** the priority list (see §6.3).
- **About:** what this site is, that it is unofficial, data source and update date, how it works, privacy statement, contact, link to the GitHub repo.

### 6.2 Search and filters

- One search box matching name, city, province and aliases.
- Case-insensitive and diacritic-insensitive ("Zypendaal", "zypendaál", "ZYPENDAAL" all match). Tolerate small typos (e.g. MiniSearch or Fuse.js, or a small in-house fuzzy matcher).
- Recognise city aliases from `city-aliases.yaml`.
- Province filter (multi-select), city filter (autocomplete from cities present in the data).
- **Clear answers to "does X participate?"**: if there is a strong match, show it first with a clear label. If not found, show "Not found in the current list (updated <date>)" and a link to the official list. Never state "not participating" as fact.
- Results show count, and update instantly as the user types.
- Sort options: name, distance (when available), province.

### 6.3 Priority list

- Add and remove museums from any result or detail page.
- Reorder via drag-and-drop **and** accessible up/down buttons.
- Mark as "visited". Optional short personal note per museum.
- Stored in `localStorage` (wrapped in try/catch, the app must still work if storage is unavailable).
- **Share link:** encodes the ordered slugs in the URL hash (e.g. `#list=slug1,slug2,...`) so no server is needed. Opening a link shows the list and offers "Save to my list" (never overwrite silently).
- Slugs that no longer exist are shown as "no longer listed".
- Export as CSV and JSON, import from JSON, print stylesheet.

### 6.4 Near me

- Only on explicit user action (button). Uses the browser Geolocation API; distance calculated client-side (haversine).
- Fallback without permission: choose a city from the list and sort by distance from that city's museums' centroid.
- No third-party geocoding calls from the browser.

### 6.5 Map (optional, Phase 5)

- List-first design. If a map is added, use Leaflet with OpenStreetMap tiles under the tile usage policy with visible attribution, loaded only when the user opens the map. Consider self-hosted PMTiles if traffic grows. The map must not be required for any feature.

### 6.6 Languages

- v1: Dutch, English, Ukrainian. Separate paths (`/nl/`, `/en/`, `/uk/`) with `hreflang` tags and a language switcher. Default by browser language, remembered without cookies (localStorage is enough).
- UI strings in one resource file per language. Machine-drafted translations must be flagged for review by native speakers before launch. Museum names are not translated.
- Layout must support RTL (e.g. Arabic) later without a redesign.

### 6.7 Design

- Mobile-first, clean, calm. Own visual identity (see G-1), no imitation of the official site.
- Respect `prefers-color-scheme` and `prefers-reduced-motion`.
- Large touch targets, readable at 200% zoom.

---

## 7. Architecture and technology

- **Static site**, no backend. Build output is plain HTML/CSS/JS files.
- **Progressive enhancement:** the museum list is pre-rendered at build time so it is readable and indexable without JavaScript. JavaScript adds search, filters, distance and the priority list.
- Suggested stack: Astro (static output, minimal client JS) or Vite + TypeScript without a UI framework. Choose one and justify it in five lines or fewer in `docs/decisions.md`.
- Search index generated at build time from `museums.json`.
- Self-host fonts and all assets. Set a strict Content-Security-Policy via meta tag or headers where the host allows.
- **Hosting:** GitHub Pages or Cloudflare Pages, served on a subdomain of the owner's domain (CNAME record). **Do not serve the site from the owner's home server or expose any home infrastructure.** Own-server hosting is only acceptable if it is a separate, hardened, public-facing host.
- Suggested layout:

```
/
├── data/                  museums.json, changelog.json, overrides.yaml, city-aliases.yaml
├── scraper/               fetch, parse, normalise, geocode, validate
├── site/                  front end source
├── docs/                  discovery.md, decisions.md, architecture.md
├── .github/workflows/     data-refresh.yml, build-deploy.yml, ci.yml
├── .github/ISSUE_TEMPLATE/
├── README.md, LICENSE, CONTRIBUTING.md, SECURITY.md
```

---

## 8. Automation, monitoring, sustainability

### 8.1 Workflows

- `data-refresh.yml`: weekly schedule and manual trigger. Runs the pipeline, commits `data/` changes if any (as a bot, or via a pull request the owner can auto-merge).
- `build-deploy.yml`: on changes to `main`, build the site and deploy.
- `ci.yml`: on pull requests, run scraper tests (against saved fixtures, not the live site), front-end tests, link check, accessibility check.
- **Verify** how GitHub handles scheduled workflows in inactive public repositories (they can be disabled after a period of no repository activity) and document how this project avoids that. Provide a fallback trigger option.

### 8.2 Validation rules (block deployment of new data when violated)

- Museum count within ±20% of the previous run and at least 100.
- At least 95% of museums have a city and valid coordinates inside the Netherlands.
- Slugs unique, names non-empty, URLs well-formed and on the expected host.
- No more than 10% of museums added or removed in one run without manual approval.

### 8.3 Alerts and freshness

- On any failure, open (or update) a single GitHub issue labelled `data-refresh-failed` with the run report. The owner gets notified by GitHub.
- The site always shows "Data last updated: <date>". If the data is older than 30 days, show a visible warning banner.
- If the scraper breaks, the site keeps serving the last good data.

### 8.4 Sustainability

- Fixtures of real source pages committed under `scraper/tests/fixtures/` so a parser break is easy to reproduce and fix.
- Dependency updates via Dependabot or Renovate; pin versions.
- `docs/maintenance.md`: "what to do when the scraper breaks", "how to add a language", "how to unpublish".

---

## 9. Open-source setup

- Public GitHub repository. Code under the MIT licence.
- The data file is derived from a third-party source: the README must say the data comes from the organisers' site, that rights to it belong to them, and that this project claims no separate data licence.
- README: purpose, screenshot, how it works, how to run locally, how the data pipeline works, disclaimer, how to report data errors, how to contribute a translation.
- CONTRIBUTING.md, SECURITY.md (contact for security issues), issue templates: "Data error", "Translation", "Feature request".
- **Repository hygiene for a first public repo:** commit with the owner's GitHub `noreply` email address, not a personal email. Before the first public push, scan history and files for secrets, tokens, internal hostnames, IP addresses, personal paths and private notes.

---

## 10. Non-functional requirements

- **Performance:** initial page under 300 KB transferred (excluding map), Lighthouse performance and accessibility at least 95 on mobile.
- **Accessibility:** WCAG 2.2 AA. Full keyboard operation, visible focus, screen-reader labels, sufficient contrast, no information conveyed by colour alone.
- **Browsers:** last two versions of Chrome, Safari, Firefox and Edge; iOS Safari and Android Chrome.
- **Privacy and security:** see G-7. HTTPS only. No third-party scripts or fonts.
- **SEO:** proper titles and descriptions per language, `hreflang`, sitemap, `lang` attributes. Optional `schema.org/Museum` markup.
- **Reliability:** fully static, so no runtime failure modes beyond hosting.

---

## 11. Testing and acceptance criteria

1. Searching "zypendaal", "Zypendaal" and "zypendaál" returns Huis Zypendaal.
2. Searching a city name returns all museums in that city, including via aliases (e.g. "Den Haag").
3. A museum not in the data yields "Not found in the current list (updated <date>)" with a link to the official list, and never a claim that it does not participate.
4. The priority list survives a page reload; a share link opens the same ordered list on another device; removed museums show as "no longer listed".
5. With JavaScript disabled, the full list of museums is readable.
6. No network requests to third-party domains occur during normal use (automated check). Geolocation data never leaves the browser.
7. Feeding the pipeline a corrupted or empty fixture keeps the previous data, blocks deployment, and opens an alert issue.
8. Scraper tests pass against committed fixtures without touching the live site.
9. Lighthouse and accessibility targets in §10 are met on the home page and a detail page.
10. Every page shows the disclaimer, attribution and last-updated date.

---

## 12. Phases

- **Phase 0 (owner, in parallel):** choose name and domain, send the outreach email (Appendix A), create the GitHub account settings (noreply email).
- **Phase 1, discovery and data:** `docs/discovery.md`, scraper, validation, tests, first `museums.json`. Stop for review.
- **Phase 2, MVP site:** list, search, province and city filters, museum pages, About and legal texts, Dutch and English. Stop for review.
- **Phase 3, personal features:** priority list, share, export and print, near me, Ukrainian. Stop for review.
- **Phase 4, automation and launch:** workflows, alerts, custom subdomain, repository polish, security and secrets scan, accessibility audit. Launch only after the owner confirms the outreach step (G-10).
- **Phase 5, optional:** map, "What's new", more languages, offline support (PWA).

---

## 13. Open decisions for the owner

1. Product name and subdomain (see Appendix C for ideas). Check availability of the name and domain first.
2. Hosting: GitHub Pages vs Cloudflare Pages.
3. Languages for launch beyond Dutch, English and Ukrainian, and who reviews them.
4. Whether to include each museum's own website link (if available from the source).
5. Whether to add any analytics later (default: none; if ever, cookieless and self-hosted, with a public statement).
6. Whether to build the map (Phase 5).
7. Commit path for automated data updates: direct bot commits or pull requests.

---

## Appendix A: outreach email drafts (for the owner to send before launch)

**English**

> Subject: Independent museum finder for "Welkom in het Museum": heads-up and question
>
> Hello,
>
> I'm a volunteer developer in the Netherlands. I'm building a small, free, non-commercial website that helps people search the participating museums of "Welkom in het Museum" by name and city, sort them by distance, and make their own shortlist. The site is clearly labelled as unofficial, links to your site for all ticket requests and information, credits you as the data source, and collects no personal data.
>
> To keep it accurate I would like to refresh the museum list weekly from your public participating-museums page, at a very low request rate. I only use factual details (museum name, province, city, address) and link back to your museum pages; I do not copy your texts or images.
>
> Do you have any objections, requirements for attribution, or an existing data feed I could use instead? I'm happy to adjust or take the site down if you prefer.
>
> Kind regards,
> [Name, website, email]

**Nederlands**

> Onderwerp: Onafhankelijke museumzoeker voor "Welkom in het Museum": korte aankondiging en vraag
>
> Beste team,
>
> Ik ben een vrijwillige ontwikkelaar in Nederland en bouw een kleine, gratis, niet-commerciële website waarmee mensen de deelnemende musea van "Welkom in het Museum" kunnen zoeken op naam en plaats, sorteren op afstand en een eigen lijstje maken. De site is duidelijk gemarkeerd als onofficieel, verwijst voor alle kaartaanvragen en informatie naar jullie website, vermeldt jullie als bron en verzamelt geen persoonsgegevens.
>
> Om de lijst actueel te houden wil ik hem wekelijks bijwerken vanaf jullie openbare pagina met deelnemende musea, met een zeer laag aantal verzoeken. Ik gebruik alleen feitelijke gegevens (naam, provincie, plaats, adres) en link naar jullie museumpagina's; jullie teksten en afbeeldingen neem ik niet over.
>
> Hebben jullie bezwaren, wensen voor bronvermelding, of bestaat er een databestand dat ik kan gebruiken? Ik pas de site graag aan of haal hem offline als jullie dat willen.
>
> Met vriendelijke groet,
> [Naam, website, e-mail]

---

## Appendix B: disclaimer and attribution texts

**English (footer):** "This is an independent, unofficial website and is not affiliated with VluchtelingenWerk Nederland, the Cultuurfonds or the VriendenLoterij. Information may be out of date. Always check the official website. Data source: welkominhetmuseum.vriendenloterij.nl. Last updated: {date}."

**Nederlands (footer):** "Dit is een onafhankelijke, onofficiële website en is niet verbonden aan VluchtelingenWerk Nederland, het Cultuurfonds of de VriendenLoterij. Informatie kan verouderd zijn. Controleer altijd de officiële website. Bron: welkominhetmuseum.vriendenloterij.nl. Laatst bijgewerkt: {date}."

**Українська:** to be drafted by the AI builder and reviewed by a native speaker before launch.

---

## Appendix C: name ideas

- **Museumwijzer** ("museum guide"), Dutch, short, descriptive. Check that the name and domain are free.
- **Museum Compass NL**, English-friendly.
- **Musea Zoeker**, plain and searchable.
- Avoid: names containing "free" (tickets need a request), "official", "Museumkaart" (an existing product), and any organiser or programme name (G-1).
