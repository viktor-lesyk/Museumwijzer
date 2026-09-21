# Upstream Data Issues & Suggested Corrections for Welkom in het Museum

> **Audience:** Coordinators and CMS administrators of the *Welkom in het Museum* programme (VriendenLoterij).  
> **Prepared by:** The Museumwijzer team  
> **Date:** September 2026  
> **Purpose:** A collaborative, factual compilation of data inconsistencies, postal code typos, misplaced addresses, and duplicate entries identified during automated data validation and quality auditing. We hope this report is helpful in improving the accuracy of visitor information across all participating platforms.

---

## 1. Summary of Identified Issues

Across the 195 participating museum records scraped from `welkominhetmuseum.vriendenloterij.nl`, our validation pipeline and identity verification tooling identified **16 specific records** requiring editorial attention:

- **6 Critical Location/Website Errors:** Institutional websites or physical addresses pointing to a completely different museum (likely due to CMS record cloning or copy-paste errors).
- **3 Postal Code Typos:** Typos in Dutch 4-digit postal codes that break geocoding, public transit routing, and navigation apps.
- **1 Administrative Boundary Error:** Museum assigned to the wrong province in the CMS taxonomy.
- **1 Active Duplicate Entry:** The same museum published under two active URLs with conflicting metadata.
- **1 Missing Closed-for-Renovation Status:** Major multi-year museum closure unflagged.
- **10 Missing Official Website URLs:** Active participating venues with no link to their official homepage.

---

## 2. Detailed Discrepancies & Verified Evidence

| # | Museum Name | Upstream URL Slug | Current Upstream Data | Verified Correct Data | Evidence & Official Source URL | Impact & Notes |
|---|---|---|---|---|---|---|
| **1** | **Sint-Jan de Doper** | `sint-jan-de-doper` | Address: *Sint Janstraat 2, 5211 ZL 's-Hertogenbosch*<br>Website: `grotekerkbreda.nl` | Address: **Sint Jansplein 2, 5141 GR Waalwijk**<br>Website: `https://www.vriendensintjanwaalwijk.nl/` | [vriendensintjanwaalwijk.nl](https://www.vriendensintjanwaalwijk.nl/) ("Kerkadres: Sint Jansplein 2, 5141 GR Waalwijk") | **Severe:** Visitors navigating to the current address arrive at the Sint-Janskathedraal in Den Bosch or Grote Kerk Breda, rather than Sint-Jan de Doper in Waalwijk. |
| **2** | **Het Nieuwe Instituut** | `het-nieuwe-instituut` | Address: *Oude Gracht 1, Veenhuizen*<br>Website: `https://www.gevangenismuseum.nl/` | Address: **Museumpark 25, 3015 CB Rotterdam**<br>Website: `https://nieuweinstituut.nl/` | [nieuweinstituut.nl](https://nieuweinstituut.nl/) ("Nieuwe Instituut Museumpark 25 3015 CB Rotterdam") | **Severe:** CMS entry was cloned from Nationaal Gevangenismuseum in Veenhuizen (Drenthe). The venue is located in Museumpark Rotterdam. |
| **3** | **KM21** | `km21` | Website: `https://www.gevangenismuseum.nl/` | Website: **`https://www.km21.nl/`**<br>Address: Stadhouderslaan 43, 2517 HV Den Haag | [km21.nl](https://www.km21.nl/) ("KM21 Stadhouderslaan 43 2517 HV Den Haag") | **High:** Website link leads visitors to the Gevangenismuseum in Drenthe instead of KM21 (contemporary art museum in The Hague). |
| **4** | **Museumstoomtram Hoorn-Medemblik** *(Duplicate)* | `museumstoomtram`<br>`museumstoomtram-hoorn-medemblik` | • `museumstoomtram` (2022): Van Dedemstraat 8, Hoorn (`stoomtram.nl`)<br>• `museumstoomtram-hoorn-medemblik` (2025): *Museumweg 2, Broek op Langedijk* (no website) | Single Canonical Entry: **Van Dedemstraat 8, 1624 NN Hoorn**<br>Website: **`https://www.stoomtram.nl/`** | [stoomtram.nl/contact](https://www.stoomtram.nl/contact/) ("Bezoekadres / Hoorn Tramstation: Van Dedemstraat 8 1624 NN Hoorn") | **High:** Two live items for the same attraction. The 2025 item inadvertently duplicated Museum BroekerVeiling's address. Recommended action: remove or 301-redirect the 2025 slug to the original 2022 slug. |
| **5** | **Nederlands Zilvermuseum Schoonhoven** | `nederlands-zilvermuseum-schoonhoven` | Address: *Museumweg 2, 1721 CX Broek op Langedijk*<br>Website: *(null)* | Address: **Kazerneplein 4, 2871 CZ Schoonhoven**<br>Website: **`https://zilvermuseum.com/`** | [zilvermuseum.com](https://zilvermuseum.com/) ("Kazerneplein 4, 2871 CZ Schoonhoven") | **Severe:** Inadvertently duplicated Museum BroekerVeiling's address in North Holland rather than Schoonhoven (Zuid-Holland). |
| **6** | **Czaar Peterhuisje** | `czaar-peterhuisje` | Address: *Kazerneplein 4, 2871 CZ Schoonhoven*<br>Website: *(null)* | Address: **Krimp 23, 1506 AA Zaandam**<br>Website: **`https://zaansmuseum.nl/czaar-peterhuisje/`** | [zaansmuseum.nl](https://zaansmuseum.nl/czaar-peterhuisje/) ("Adres Czaar Peterhuisje Krimp 23 1506 AA Zaandam") | **Severe:** Body text and address were duplicated from Nederlands Zilvermuseum Schoonhoven. Venue is in Zaandam. |
| **7** | **Museum Kaap Skil** | `museum-kaap-skil` | Address: *Kazerneplein 4, 2871 CZ Schoonhoven*<br>Website: *(null)* | Address: **Heemskerckstraat 9, 1792 AA Oudeschild (Texel)**<br>Website: **`https://kaapskil.nl/`** | [kaapskil.nl/contact](https://kaapskil.nl/contact/) ("Het adres van Museum Kaap Skil is Heemskerckstraat 9, 1792 AA Oudeschild, Texel.") | **Severe:** Duplicated Zilvermuseum Schoonhoven address. Venue is located on Texel. |
| **8** | **Huis Willet-Holthuysen** | `huis-willet-holthuysen` | Address: *Kazerneplein 4, 2871 CZ Schoonhoven*<br>Website: *(null)* | Address: **Herengracht 605, 1017 CE Amsterdam**<br>Website: **`https://www.willetholthuysen.nl/`** | [amsterdammuseum.nl](https://www.amsterdammuseum.nl/contact) ("Adres locaties: Huis Willet-Holthuysen, Herengracht 605, 1017 CE Amsterdam") | **Severe:** Duplicated Zilvermuseum Schoonhoven address. Venue is on the Herengracht in Amsterdam. |
| **9** | **Nationaal Monument Oranjehotel** | `nationaal-monument-oranjehotel` | Postcode: *297 BP* | Postcode: **2597 BP**<br>Address: Van Alkemadelaan 1258, 2597 BP Den Haag | [oranjehotel.org/contact](https://www.oranjehotel.org/nl/contact/) ("Van Alkemadelaan 1258, 2597 BP Den Haag") | **Medium:** Typo missing the initial digit '5'. Causes route planners and GPS navigation systems to fail. |
| **10** | **Forum Groningen / Storyworld** | `forum-groningen`<br>`storyworld` | Postcode: *99712 KN* | Postcode: **9712 KN**<br>Address: Nieuwe Markt 1, 9712 KN Groningen | [forum.nl/contact](https://forum.nl/nl/contact) ("Nieuwe Markt 1, 9712 KN Groningen") | **Medium:** Typo with duplicate digit '9' yielding an invalid 5-digit Dutch postcode. |
| **11** | **Kunstmuseum Den Haag** | `kunstmuseum-den-haag` | Postcode: *2717 HV* | Postcode: **2517 HV**<br>Address: Stadhouderslaan 41, 2517 HV Den Haag | [kunstmuseum.nl/bezoek](https://www.kunstmuseum.nl/nl/bezoek) ("Stadhouderslaan 41, 2517 HV Den Haag") | **Medium:** Typo ('2717' instead of '2517'). |
| **12** | **Museum Tachtigjarige Oorlog** | `museum-tachtigjarige-oorlog` | Province: *Groningen* | Province: **Gelderland**<br>Address: Mattelierstraat 5, 7141 BP Groenlo | [nmto.nl/contact](https://www.nmto.nl/contact) ("Oude Calixtuskerk, Mattelierstraat 5, 7141 BP Groenlo") | **Medium:** Groenlo is in the Achterhoek (Gelderland), but listed under province Groningen in the CMS taxonomy filter. |
| **13** | **KoepelKathedraal Haarlem** | `koepelkathedraal` | Address: *Haarlem* (street and postcode omitted) | Address: **Leidsevaart 146, 2014 HE Haarlem**<br>Website: `https://koepelkathedraal.nl/` | [koepelkathedraal.nl](https://koepelkathedraal.nl/) ("Leidsevaart 146 2014 HE Haarlem") | **Medium:** Missing street address in CMS record. |
| **14** | **ARTIS-Groote Museum** | `artis-groote-museum` | Address: *Plantage Kerklaan 36, 1018 CZ* (city omitted) | City: **Amsterdam**<br>Address: Plantage Kerklaan 36, 1018 CZ Amsterdam | [artis.nl](https://www.artis.nl/nl/plan-je-bezoek/bereikbaarheid-parkeren) ("Plantage Kerklaan 36, Amsterdam") | **Low:** City name omitted in address block. |
| **15** | **Museum Prinsenhof Delft** | `museumprinsenhofdelft` | Status: active / open; Address: *Sint Agathaplein 4* | Status: **Tijdelijk gesloten voor renovatie**<br>Building address: Sint Agathaplein 1, 2611 HR Delft | [museumprinsenhofdelft.nl](https://www.museumprinsenhofdelft.nl/plan-je-bezoek) ("Museum Prinsenhof Delft is tijdelijk gesloten voor verbouwing en vernieuwing.") | **High:** The museum is undergoing a comprehensive multi-year renovation until ~2027. Sint Agathaplein 4 is the temporary info office. Visitors without prior warning may travel to Delft expecting an open museum. |
| **16** | **Missing Websites (10 active venues)** | *(Multiple slugs)* | Website: *(null / empty)* | See section 3 below for full list of verified official website URLs. | Official websites verified by identity tokens. | **High:** Prevents visitors from accessing ticket booking, accessibility information, and live opening times. |

---

## 3. Missing Museum Websites: Verified URLs

The following 10 active participating museums currently lack an official homepage link in their CMS record. We have verified their official websites:

1. **H’ART Museum** (`HaRT-Museum1`):  
   `https://hartmuseum.nl/` (formerly Hermitage Amsterdam, Amstel 51, Amsterdam)
2. **Museum Tromp’s Huys** (`Museum-Tromps-Huys`):  
   `https://trompshuys.nl/` (Dorpsstraat 99, Oost-Vlieland)
3. **Museumhuis Sloëtjes** (`Museumhuis-sloetjes1`):  
   `https://www.hendrickdekeyser.nl/museumbezoek/huis-sloetjes` (Lindenheuvel 1, Hilversum)
4. **TextielMuseum** (`Textiel-museum`):  
   `https://textielmuseum.nl/` (Goirkestraat 96, Tilburg)
5. **Czaar Peterhuisje** (`czaar-peterhuisje`):  
   `https://zaansmuseum.nl/czaar-peterhuisje/` (Krimp 23, Zaandam)
6. **Huis Willet-Holthuysen** (`huis-willet-holthuysen`):  
   `https://www.willetholthuysen.nl/` or `https://www.amsterdammuseum.nl/locaties/huis-willet-holthuysen` (Herengracht 605, Amsterdam)
7. **Madurodam** (`madurodam`):  
   `https://madurodam.nl/` (George Maduroplein 1, Den Haag)
8. **Museum BroekerVeiling** (`museum-broekerveiling`):  
   `https://broekerveiling.nl/` (Museumweg 2, Broek op Langedijk)
9. **Museum Kaap Skil** (`museum-kaap-skil`):  
   `https://kaapskil.nl/` (Heemskerckstraat 9, Oudeschild, Texel)
10. **Nederlands Zilvermuseum Schoonhoven** (`nederlands-zilvermuseum-schoonhoven`):  
    `https://zilvermuseum.com/` (Kazerneplein 4, Schoonhoven)

---

## 4. Minor Slug & Formatting Recommendations

For CMS consistency and long-term URL stability:
- `HaRT-Museum1` → recommend slug `hart-museum` (remove capitalisation and draft number `1`).
- `Museum-Tromps-Huys` → recommend slug `museum-tromps-huys` (lowercase).
- `Museumhuis-sloetjes1` → recommend slug `museumhuis-sloetjes` (remove draft number `1`).
- `Textiel-museum` → recommend slug `textielmuseum` (lowercase without hyphen, matching official spelling).
