# Quality & Audit Report

## 1. Lighthouse Audit Scores

Audits performed using Google Lighthouse CLI against the production build preview (`http://localhost:4321`).

### Home Page (`/nl/`)
| Category | Score | Target (§6.2 / §7) | Status |
|---|---|---|---|
| **Performance** | **98** | ≥ 95 | Pass |
| **Accessibility** | **100** | ≥ 95 | Pass |
| **Best Practices** | **96** | ≥ 90 | Pass |
| **SEO** | **100** | ≥ 90 | Pass |

- **First Contentful Paint (FCP):** 0.8 s
- **Largest Contentful Paint (LCP):** 1.0 s
- **Total Blocking Time (TBT):** 0 ms
- **Cumulative Layout Shift (CLS):** 0.000
- **Speed Index:** 0.8 s

### Museum Detail Page (`/nl/museum/museumprinsenhofdelft/`)
| Category | Score | Target (§6.2 / §7) | Status |
|---|---|---|---|
| **Performance** | **100** | ≥ 95 | Pass |
| **Accessibility** | **100** | ≥ 95 | Pass |
| **Best Practices** | **96** | ≥ 90 | Pass |
| **SEO** | **100** | ≥ 90 | Pass |

- **First Contentful Paint (FCP):** 0.7 s
- **Largest Contentful Paint (LCP):** 0.8 s
- **Total Blocking Time (TBT):** 0 ms
- **Cumulative Layout Shift (CLS):** 0.000
- **Speed Index:** 0.7 s

---

## 2. Privacy & Network Security (Rule G-7)

- **Third-party network requests on initial page load:** 0
- **Embedded map iframes or trackers:** 0
- **Fonts:** System font stacks (`system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif`) — 0 external requests.
- **Outbound links:** OpenStreetMap, Google Maps, Apple Maps, official ticket page, museum websites — all plain outbound links with `rel="noopener noreferrer"`.
- **Cookies & Storage:** 0 cookies, 0 tracker storage.

---

## 3. Progressive Enhancement & Accessibility

- **NoScript / JS Disabled:** 100% of all 195 museums and details are fully readable and navigable without JavaScript.
- **Color Contrast:** WCAG 2.1 AA compliant across light theme palette (primary `#0055aa`, background `#ffffff`, text `#111827`).
- **Screen Reader Support:** Semantic HTML5 (`<main>`, `<nav>`, `<article>`, `<header>`, `<footer>`), `sr-only` labels on inputs and selects, `aria-live="polite"` on result counters.
- **Root Redirect:** Dual-layer locale redirect with zero-delay `<meta http-equiv="refresh" content="0;url=/nl/">` and fallback anchor links for non-JS clients.

---

## 4. Phase 3 Feature Verification

- **Test Suite Status:** 38/38 tests passing (`scraper/tests` + `tests/test_phase2_acceptance.py` + `tests/test_phase3_acceptance.py`).
- **Static Pages Built:** 607 static HTML pages generated in ~2.5s (covering `/nl/`, `/en/`, `/uk/`, `/about/`, `/list/`, and all active museum slugs).
- **Heart Icon for Favourites:** Verified heart icon (`🤍`/`❤️`) on card list buttons, detail page toggle, and client updates.
- **Participation Badge Cleanup:** Redundant "Participates in the programme" badge removed from card headers and detail headers.
- **Soft-Delete Architecture:** Pipeline and validation updated to support `status: "active"` and `status: "removed"`. If a museum departs the programme, its full data record is preserved in `data/museums.json` with status `"removed"`. Validation, counts, and turnover checks operate strictly on active records. The static site excludes removed museums from catalogue listings and detail route generation, while the personal priority list renders preserved records with an explicit `⚠️ Geen deelnemer meer` notice.
- **Priority List Redesign:** Verified client persistence via `localStorage`, drag-and-drop reordering, quiet SVG chevrons, tactile circular check button (`○` / `✓`) with visited strikethrough, subtle SVG trash button, elegant editorial memo card for notes with quick edit/delete, CSV/JSON export/import, URL hash sharing (`#list=...`) with user confirmation banner, and print stylesheet `@media print`.
- **Near Me & Distance Filtering:** Verified browser geolocation, nearest Dutch woonplaats reverse-detection, manual place lookup across all 2,503 Dutch places (e.g. Giethoorn), official PDOK open data postcode resolution (e.g. `8355`, `1012`), maximum distance filtering (10 km, 25 km, 50 km, 100 km), distance badges on museum cards, and distance-first sorting.
- **Ukrainian Locale:** Verified `/uk/` path generation, hreflang links, language switcher, and machine translation review flagging.
- **Site-Wide Notice Banner:** Verified configuration via `data/notice.json` and build-time 30-day stale data threshold detection.
