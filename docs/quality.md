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
