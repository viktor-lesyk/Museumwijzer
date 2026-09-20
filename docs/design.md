# Museumwijzer Visual Identity & Technical Architecture Design

*Context: Phase 2 Front-End Design Document (§6, §7, §10, G-1, G-7)*

---

## 1. Visual Identity & Brand Separation (Guardrail G-1)

The official campaign organisers (VriendenLoterij, Cultuurfonds, VluchtelingenWerk) use loud, high-energy lottery branding featuring bright flame orange (`#e37222`), bold red (`#d52b1e`), and vibrant yellow badge accents.

To respect Guardrail G-1 and present a calm, civic, independent public service:
- **Visual Tone:** Calm, editorial, understated, clear, and dignified. It looks like a cultural field guide, not a promotional lottery contest.
- **Colour Palette:**
  - **Canvas (Background):** Soft parchment / crisp neutral (`#f8fafc`; dark mode `#0f172a`)
  - **Surface (Cards, Bars):** Pure white (`#ffffff`; dark mode `#1e293b`)
  - **Primary / Brand:** Delft Slate Blue (`#1e3a5f` / `#2563eb`), evoking classic Dutch civic institutions.
  - **Action / Interactive:** Deep Navy (`#1d4ed8`) with high-contrast active states.
  - **Success / Participation Badge:** Muted Forest Green (`#15803d` on `#f0fdf4`) for verified participating museums.
  - **Neutral / Text:** Deep Charcoal (`#0f172a`) for maximum readability, Slate Gray (`#475569`) for metadata.
  - **Border & Dividers:** Subtle slate stroke (`#e2e8f0`; dark mode `#334155`).
  - **Strict Prohibition:** No orange or lottery-style graphics; no logos of the organisers or museums.
- **Typography:**
  - Standard system font stack (`system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`).
  - **Rationale:** 0 KB transfer overhead, instantaneous rendering with zero layout shifts (CLS 0.0), and zero third-party font tracking (G-7).
- **Accessibility & Contrast:**
  - All text meets or exceeds WCAG 2.2 AA (4.5:1 for body, 3:1 for large text).
  - Explicit 3px high-contrast outline on `:focus-visible` for complete keyboard accessibility.
  - Full support for `prefers-color-scheme` (dark mode) and `prefers-reduced-motion`.

---

## 2. Technology Stack Choice (ADR 005)

> **Stack Choice: Astro (Static Output / SSG)**
>
> 1. Pre-renders 100% static HTML at build time for all 195 museums, guaranteeing the site works completely without JavaScript (progressive enhancement).
> 2. Zero client-side JavaScript runtime framework overhead (only ~8 KB of vanilla client JS for interactive instant search and filtering).
> 3. Native file-based i18n routing (`/nl/`, `/en/`) with built-in `hreflang` tags and structured metadata.
> 4. Native TypeScript support with direct imports from `data/museums.json` and `data/meta.json`.
> 5. Simple static output directory (`dist/`) deployable anywhere (GitHub Pages or Cloudflare Pages) with zero runtime server failure modes.

---

## 3. Multilingual & RTL Architecture

The i18n system is structured around decoupled language dictionaries (`site/src/i18n/`):
- `languages.ts`: Configuration of supported locales, labels, and text direction (`dir: 'ltr' | 'rtl'`).
- In Phase 2, `nl` (Dutch) and `en` (English) are active. In Phase 3, `uk` (Ukrainian) is enabled with zero structural changes.
- RTL locales (e.g. Arabic `ar`) are accommodated using logical CSS properties (`margin-inline-start`, `padding-inline`, `text-align: start`).

---

## 4. Progressive Enhancement & Search Design

- **Static Baseline:** The full list of 195 museums is rendered directly into HTML semantic `<article>` tags at build time. Without JavaScript, visitors can browse and view all museums immediately.
- **Client Enhancement:** A tiny, self-contained client script progressively enhances the page:
  - Instant live filtering across name, city, province, and aliases.
  - Normalised diacritic-insensitive matching ("Zypendaal", "zypendaál").
  - Province multi-select filter chips and city autocomplete dropdown.
  - Dynamic result counter and prominent "Does X participate?" status banner.
