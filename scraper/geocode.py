from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional, Tuple
import requests

from .config import (
    GEOCODE_CACHE_PATH,
    NL_LAT_MAX,
    NL_LAT_MIN,
    NL_LON_MAX,
    NL_LON_MIN,
    PDOK_SEARCH_URL,
    USER_AGENT,
)
from .normalise import normalise_province

logger = logging.getLogger(__name__)


class GeocodeResult:
    def __init__(
        self,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        woonplaats: Optional[str] = None,
        municipality: Optional[str] = None,
        province: Optional[str] = None,
        weergavenaam: Optional[str] = None,
    ):
        self.lat = lat
        self.lon = lon
        self.woonplaats = woonplaats
        self.municipality = municipality
        self.province = province
        self.weergavenaam = weergavenaam


class Geocoder:
    """Geocode Dutch museum addresses using PDOK Locatieserver with persistent caching."""

    def __init__(self, cache_path: Path = GEOCODE_CACHE_PATH, min_interval: float = 1.0):
        self.cache_path = cache_path
        self.min_interval = min_interval
        self.last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cache: Dict[str, Any] = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"Could not load geocode cache: {e}")
            return {}

    def save_cache(self) -> None:
        """Save geocode cache to disk with deterministic key ordering."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, sort_keys=True, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save geocode cache: {e}")

    def _rate_limit(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def _query_pdok(self, query: str, prefer_adres: bool = True) -> Optional[Dict[str, Any]]:
        self._rate_limit()
        try:
            params = {"q": query, "rows": 5}
            if prefer_adres and re.search(r"\b[1-9]\d{3}\s*[A-Z]{2}\b", query):
                params["fq"] = "type:(adres OR postcode)"

            resp = self.session.get(
                PDOK_SEARCH_URL,
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get("response", {}).get("docs", [])
                if docs:
                    # Prefer type == 'adres' first, then 'postcode'
                    for doc in docs:
                        if doc.get("type") == "adres":
                            return doc
                    for doc in docs:
                        if doc.get("type") == "postcode":
                            return doc
                    return docs[0]
            else:
                logger.warning(f"PDOK search returned HTTP {resp.status_code} for '{query}'")
        except Exception as e:
            logger.error(f"PDOK search exception for '{query}': {e}")
        return None

    def _extract_coords(self, doc: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        point_str = doc.get("centroide_ll", "")
        m = re.search(r"POINT\(\s*([0-9.]+)\s+([0-9.]+)\s*\)", point_str)
        if m:
            lon = round(float(m.group(1)), 6)
            lat = round(float(m.group(2)), 6)
            if NL_LAT_MIN <= lat <= NL_LAT_MAX and NL_LON_MIN <= lon <= NL_LON_MAX:
                return lat, lon
            else:
                logger.warning(f"Coordinates ({lat}, {lon}) outside Netherlands bounds")
        return None, None

    def geocode_museum(
        self,
        slug: str,
        name: str,
        street: Optional[str],
        postcode: Optional[str],
        city: Optional[str],
    ) -> GeocodeResult:
        """
        Geocode museum address.
        Returns GeocodeResult with lat, lon, woonplaats, municipality, province, weergavenaam.
        """
        address_sig = f"{postcode or ''}|{street or ''}|{city or ''}"

        # Check cache
        cached = self.cache.get(slug)
        if cached and cached.get("address_sig") == address_sig:
            lat = cached.get("lat")
            lon = cached.get("lon")
            if lat is not None and lon is not None:
                return GeocodeResult(
                    lat=lat,
                    lon=lon,
                    woonplaats=cached.get("city") or cached.get("woonplaats"),
                    municipality=cached.get("municipality"),
                    province=cached.get("province"),
                    weergavenaam=cached.get("weergavenaam"),
                )

        # Build queries in order of precision:
        queries = []

        # 1. Postcode + house number
        house_num = None
        if street:
            m_num = re.search(r"\b(\d+[a-zA-Z0-9\-/]*)\b", street)
            if m_num:
                house_num = m_num.group(1)

        if postcode and house_num:
            queries.append(f"{postcode} {house_num}")

        # 2. Street + city
        if street and city:
            queries.append(f"{street}, {city}")

        # 3. Postcode + city
        if postcode and city:
            queries.append(f"{postcode} {city}")

        # 4. Name + city
        if name and city:
            queries.append(f"{name}, {city}")

        for q in queries:
            doc = self._query_pdok(q)
            if doc:
                lat, lon = self._extract_coords(doc)
                if lat is not None and lon is not None:
                    woonplaats = doc.get("woonplaatsnaam") or city
                    municipality = doc.get("gemeentenaam") or woonplaats
                    province = doc.get("provincienaam")
                    weergavenaam = doc.get("weergavenaam", "")

                    self.cache[slug] = {
                        "address_sig": address_sig,
                        "query": q,
                        "lat": lat,
                        "lon": lon,
                        "city": woonplaats,
                        "woonplaats": woonplaats,
                        "municipality": municipality,
                        "province": province,
                        "weergavenaam": weergavenaam,
                        "geocoded_at": datetime.now(timezone.utc).isoformat(),
                    }
                    return GeocodeResult(
                        lat=lat,
                        lon=lon,
                        woonplaats=woonplaats,
                        municipality=municipality,
                        province=province,
                        weergavenaam=weergavenaam,
                    )

        logger.warning(f"Could not geocode '{slug}' with queries: {queries}")
        return GeocodeResult(lat=None, lon=None, woonplaats=city, municipality=None, province=None)

    def check_sanity(
        self,
        slug: str,
        lat: Optional[float],
        lon: Optional[float],
        source_province: str,
        pdok_province: Optional[str],
        source_city: Optional[str] = None,
        pdok_woonplaats: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform sanity checks on geocoded results and flag any anomalies."""
        issues = []
        is_outlier = False

        # Province comparison with Friesland = Fryslân normalisation
        norm_source = normalise_province(source_province)
        norm_pdok = normalise_province(pdok_province)
        if norm_source and norm_pdok and norm_source.lower() != norm_pdok.lower():
            issues.append(f"Province mismatch: source='{source_province}', PDOK='{pdok_province}'")

        # Netherlands-wide geographic bounds check
        if lat is not None and lon is not None:
            if not (NL_LAT_MIN <= lat <= NL_LAT_MAX and NL_LON_MIN <= lon <= NL_LON_MAX):
                issues.append(
                    f"Coordinate outlier outside Netherlands bounds: ({lat}, {lon}) "
                    f"expected [{NL_LAT_MIN}-{NL_LAT_MAX}, {NL_LON_MIN}-{NL_LON_MAX}]"
                )
                is_outlier = True

        return {
            "slug": slug,
            "has_issues": len(issues) > 0,
            "is_outlier": is_outlier,
            "issues": issues,
        }
