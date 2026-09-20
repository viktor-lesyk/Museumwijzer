import os
from pathlib import Path

# Paths (relative to repository root to avoid baking in absolute user paths)
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = REPO_ROOT / ".cache"
HTTP_CACHE_DIR = CACHE_DIR / "http"

MUSEUMS_JSON_PATH = DATA_DIR / "museums.json"
META_JSON_PATH = DATA_DIR / "meta.json"
CHANGELOG_JSON_PATH = DATA_DIR / "changelog.json"
GEOCODE_CACHE_PATH = DATA_DIR / "geocode-cache.json"
OVERRIDES_PATH = DATA_DIR / "overrides.yaml"
CITY_ALIASES_PATH = DATA_DIR / "city-aliases.yaml"

# Source endpoints
SOURCE_HOST = "welkominhetmuseum.vriendenloterij.nl"
SOURCE_BASE_URL = f"https://{SOURCE_HOST}"
SOURCE_LIST_URL = f"{SOURCE_BASE_URL}/nl/deelnemende-musea/"
CANONICAL_LOCALE = "nl"
SUPPORTED_LOCALES = ["nl", "en", "uk"]

# Scraper etiquette
CONTACT_EMAIL = os.environ.get("MUSEUMWIJZER_CONTACT", "contact-email-not-configured")
PROJECT_REPO_URL = os.environ.get("MUSEUMWIJZER_REPO_URL", "https://github.com/museumwijzer/museumwijzer")
USER_AGENT = f"Museumwijzer/1.0 (+{PROJECT_REPO_URL}; contact: {CONTACT_EMAIL})"
MIN_REQUEST_INTERVAL = 1.0  # seconds between requests (G-6)

# PDOK Locatieserver (free Dutch government geocoder)
PDOK_SEARCH_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"

# Geographic bounding box for the Netherlands (excluding overseas territories)
NL_LAT_MIN = 50.70
NL_LAT_MAX = 53.75
NL_LON_MIN = 3.20
NL_LON_MAX = 7.30

# Validation thresholds (§8.2)
MIN_MUSEUM_COUNT = 100
EXPECTED_BASELINE_COUNT = 195
MAX_COUNT_CHANGE_PERCENT = 20.0
MAX_TURNOVER_PERCENT = 10.0
MIN_COMPLETE_GEO_PERCENT = 95.0
