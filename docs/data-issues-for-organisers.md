# Upstream Data Issues & Suggested Corrections for Welkom in het Museum

> **Audience:** Coordinators and CMS administrators of the *Welkom in het Museum* programme (VluchtelingenWerk Nederland, het Cultuurfonds & VriendenLoterij).  
> **Prepared by:** Viktor Lesyk — Freelance Software & Data Consultant  
> **Date:** September 2026  
> **Context:** Cross-language audit of live records on `welkominhetmuseum.vriendenloterij.nl` (`/nl/` vs. `/en/`)  
> **Key Finding:** Several records were corrected in the English translation (`/en/`), but the primary Dutch version (`/nl/`) was left with cloned/outdated CMS data. Other critical issues affect both language versions simultaneously.

---

## 1. Summary of Identified Issues

Across the 195 participating museum records on `welkominhetmuseum.vriendenloterij.nl`, our validation pipeline and cross-language quality audit verified **13 specific records** requiring editorial attention:

1. **5 Language Desynchronisations (NL vs. EN):** Venues where the English page (`/en/`) has the correct address, but the primary Dutch page (`/nl/`) still displays a cloned contact block from another museum (e.g. Breda, Schoonhoven, or Broek op Langedijk).
2. **2 Incorrect Website Links & Duplicate Pages:** A venue linking to a completely different museum's website (`km21` linking to the Prison Museum in Drenthe on both `/nl/` and `/en/`), and an active duplicate URL containing another museum's data (`museumstoomtram-hoorn-medemblik`).
3. **5 Cross-Language Postal Code & City Errors (Present on both NL and EN):** Including the KoepelKathedraal in Haarlem displaying Maastricht (`6211 HD`) as its city and postal code, and several typos in 4-digit Dutch postcodes.
4. **1 Taxonomy Tag Error:** Museum categorized under province Groningen instead of Gelderland.

---

## 2. Detailed Discrepancies & Verified Evidence

| # | Museum Name | Upstream URL Slug | Status on Dutch Site (`/nl/`) | Status on English Site (`/en/`) | Verified Correct Data & Source | Impact & Editorial Recommendation |
|---|---|---|---|---|---|---|
| **1** | **Sint-Jan de Doper** | `sint-jan-de-doper` | <span style="color:red">**Grote Kerk van Breda**<br>Kerkplein 2, 4811 XT Breda<br>`grotekerkbreda.nl`</span> | Correct in EN:<br>Sint Jan de Doper<br>Sint Jansplein 2, Waalwijk | **Sint Jansplein 2, 5141 GR Waalwijk**<br>Website: `https://www.vriendensintjanwaalwijk.nl/`<br>[vriendensintjanwaalwijk.nl](https://www.vriendensintjanwaalwijk.nl/) | **Severe:** On the Dutch site (`/nl/`), the contact block was cloned from Grote Kerk Breda. Dutch visitors are directed to Breda rather than Waalwijk. Sync the Waalwijk address to `/nl/`. |
| **2** | **Het Nieuwe Instituut** | `het-nieuwe-instituut` | <span style="color:red">Museumpark 25<br>**9341 AA Veenhuizen**<br>`gevangenismuseum.nl`</span> | <span style="color:red">Same bug on EN:<br>Museumpark 25<br>**9341 AA Veenhuizen**<br>`gevangenismuseum.nl`</span> | **Museumpark 25, 3015 CB Rotterdam**<br>Website: `https://nieuweinstituut.nl/`<br>[nieuweinstituut.nl](https://nieuweinstituut.nl/) | **Severe (Both NL & EN):** Postcode/city and website link were cloned from the Prison Museum in Drenthe. Venue is in Museumpark Rotterdam. |
| **3** | **Czaar Peterhuisje** | `czaar-peterhuisje` | <span style="color:red">**Ned. Zilvermuseum Schoonhoven**<br>Kazerneplein 4, Schoonhoven<br>`zilvermuseum.com`</span> | Correct in EN:<br>The Czaar Peter House<br>Krimp 23, Zaandam | **Krimp 23, 1506 AA Zaandam**<br>Website: `https://zaansmuseum.nl/czaar-peterhuisje/`<br>[zaansmuseum.nl](https://zaansmuseum.nl/czaar-peterhuisje/) | **Severe:** Dutch page (`/nl/`) cloned Zilvermuseum Schoonhoven. English page was corrected, but Dutch page was never updated in the CMS. |
| **4** | **Museum Kaap Skil** | `museum-kaap-skil` | <span style="color:red">**Ned. Zilvermuseum Schoonhoven**<br>Kazerneplein 4, Schoonhoven<br>`zilvermuseum.com`</span> | Correct in EN:<br>Museum Kaap Skil<br>Heemskerckstraat 9, Texel | **Heemskerckstraat 9, 1792 AA Oudeschild (Texel)**<br>Website: `https://kaapskil.nl/`<br>[kaapskil.nl/contact](https://kaapskil.nl/contact/) | **Severe:** Dutch page (`/nl/`) cloned Zilvermuseum Schoonhoven. English page has correct Texel address; Dutch page needs sync. |
| **5** | **Huis Willet-Holthuysen** | `huis-willet-holthuysen` | <span style="color:red">**Ned. Zilvermuseum Schoonhoven**<br>Kazerneplein 4, Schoonhoven<br>`zilvermuseum.com`</span> | Correct in EN:<br>Huis Willet-Holthuysen<br>Herengracht 605, Amsterdam | **Herengracht 605, 1017 CE Amsterdam**<br>Website: `https://www.willetholthuysen.nl/`<br>[amsterdammuseum.nl](https://www.amsterdammuseum.nl/contact) | **Severe:** Dutch page (`/nl/`) cloned Zilvermuseum Schoonhoven. English page has correct Amsterdam address; Dutch page needs sync. |
| **6** | **KM21** | `km21` | <span style="color:red">Stadhouderslaan 43, Den Haag<br>Website: `gevangenismuseum.nl`</span> | <span style="color:red">Same on EN:<br>Stadhouderslaan 43, Den Haag<br>Website: `gevangenismuseum.nl`</span> | **Stadhouderslaan 43, 2517 HV Den Haag**<br>Website: **`https://www.km21.nl/`**<br>[km21.nl](https://www.km21.nl/) | **High (Both NL & EN):** Address is correct in The Hague, but the website link directs visitors to the Gevangenismuseum in Drenthe. |
| **7** | **Museumstoomtram Hoorn-Medemblik** *(Duplicate)* | `museumstoomtram`<br>`museumstoomtram-hoorn-medemblik` | • `museumstoomtram`: Hoorn<br>• `...hoorn-medemblik`: <span style="color:red">BroekerVeiling data</span> | • `museumstoomtram`: Hoorn<br>• `...hoorn-medemblik`: Enkhuizen jetty | **Van Dedemstraat 8, 1624 NN Hoorn**<br>Website: **`https://www.stoomtram.nl/`**<br>[stoomtram.nl/contact](https://www.stoomtram.nl/contact/) | **High:** Two live items for the same attraction. The 2025 Dutch slug duplicated Museum BroekerVeiling. Recommend unpublishing or 301-redirecting the duplicate slug. |
| **8** | **KoepelKathedraal Haarlem** | `koepelkathedraal` | <span style="color:red">Leidsevaart 146<br>**6211 HD Maastricht**</span> | <span style="color:red">Same bug on EN:<br>Leidsevaart 146<br>**6211 HD Maastricht**</span> | **Leidsevaart 146, 2014 HE Haarlem**<br>Website: `https://koepelkathedraal.nl/`<br>[koepelkathedraal.nl](https://koepelkathedraal.nl/) | **Medium (Both NL & EN):** Street address is correct in Haarlem, but city and postcode say **6211 HD Maastricht**, causing GPS navigation to plot to Limburg. |
| **9** | **Nationaal Monument Oranjehotel** | `nationaal-monument-oranjehotel` | <span style="color:red">Postcode: **297 BP** Den Haag</span> | <span style="color:red">Same bug on EN:<br>Postcode: **297 BP**</span> | **2597 BP Den Haag**<br>Address: Van Alkemadelaan 1258<br>[oranjehotel.org/contact](https://www.oranjehotel.org/nl/contact/) | **Medium (Both NL & EN):** Typo missing initial digit '5'. Causes route planners and navigation systems to fail. |
| **10** | **Forum Groningen** | `forum-groningen` | <span style="color:red">Postcode: **99712 KN** Groningen</span> | <span style="color:red">Same bug on EN:<br>Postcode: **99712 KN**</span> | **9712 KN Groningen**<br>Address: Nieuwe Markt 1<br>[forum.nl/contact](https://forum.nl/nl/contact) | **Medium (Both NL & EN):** Typo with duplicate digit '9' yielding an invalid 5-digit postcode. *(Note: Separate Storyworld page has valid 9712 KN).* |
| **11** | **Kunstmuseum Den Haag** | `kunstmuseum-den-haag` | <span style="color:red">Postcode: **2717 HV** Den Haag</span> | <span style="color:red">Same bug on EN:<br>Postcode: **2717 HV**</span> | **2517 HV Den Haag**<br>Address: Stadhouderslaan 41<br>[kunstmuseum.nl/bezoek](https://www.kunstmuseum.nl/nl/bezoek) | **Medium (Both NL & EN):** Typo ('2717' instead of '2517'). |
| **12** | **Museum Volkenkunde / Wereldmuseum Leiden** | `museum-volkenkunde` | <span style="color:red">Postcode: **1624 NN** Leiden</span> | <span style="color:red">Same bug on EN:<br>Postcode: **1624 NN**</span> | **2312 BS Leiden**<br>Address: Steenstraat 1<br>[wereldmuseum.nl](https://leiden.wereldmuseum.nl/nl/over-wereldmuseum-leiden/contact) | **Medium (Both NL & EN):** Postcode `1624 NN` belongs to Hoorn. Also note: museum officially rebranded to **Wereldmuseum Leiden**. |
| **13** | **Museum Tachtigjarige Oorlog** | `museum-tachtigjarige-oorlog` | <span style="color:red">CMS tag: **Groningen**</span> | <span style="color:red">Same bug on EN:<br>Tag: **Groningen**</span> | Province: **Gelderland**<br>Address: Mattelierstraat 5, Groenlo<br>[nmto.nl/contact](https://www.nmto.nl/contact) | **Medium (Both NL & EN):** Groenlo is in Gelderland (Achterhoek), but tagged with `Groningen` in the CMS taxonomy filter. |

---

## 3. Editorial & Usability Suggestions

### A. Plain-Text Website URLs (Missing Hyperlinks)
On several museum pages in both language versions, the official website address is included in the contact text, but was entered as plain text rather than an active clickable hyperlink (`<a>` tag). Adding active links improves the mobile user experience:
- **Madurodam** (`madurodam`): `www.madurodam.nl` is in body text; recommend turning into a clickable link.
- **TextielMuseum** (`Textiel-museum`): `www.textielmuseum.nl` is in body text; recommend turning into a clickable link.
- **H’ART Museum** (`HaRT-Museum1`): `www.hartmuseum.nl` is in body text; recommend turning into a clickable link.
- **Museum BroekerVeiling** (`museum-broekerveiling`): `www.broekerveiling.nl` is in body text; recommend turning into a clickable link.
- **Museumhuis Sloëtjes** (`Museumhuis-sloetjes1`): `www.hendrickdekeyser.nl/huis-sloetjes` is in body text; recommend turning into a clickable link.
- **Museum Tromp’s Huys** (`Museum-Tromps-Huys`): `www.trompshuys.nl` is in body text; recommend turning into a clickable link.

### B. CMS Slug Formatting & Consistency
For long-term URL stability and SEO consistency:
- `HaRT-Museum1` → recommend slug `hart-museum` (remove capitalisation and draft number `1`).
- `Museum-Tromps-Huys` → recommend slug `museum-tromps-huys` (lowercase).
- `Museumhuis-sloetjes1` → recommend slug `museumhuis-sloetjes` (remove draft number `1`).
- `Textiel-museum` → recommend slug `textielmuseum` (lowercase without hyphen, matching official spelling).