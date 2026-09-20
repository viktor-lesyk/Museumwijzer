"""Identity audit tool: verifies that museum_website actually belongs to the museum.

Fetches each museum's homepage, extracts <title> and <h1>, and compares them with
the museum's name and city. Reports all suspicious records where the website
appears to belong to a different institution or contains no recognizable tokens.
"""

from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from .fetch import PoliteFetcher

logger = logging.getLogger("enrich.audit_identity")

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSEUMS_JSON_PATH = REPO_ROOT / "data" / "museums.json"
CACHE_DIR = REPO_ROOT / ".cache" / "enrichment" / "pages"
AUDIT_REPORT_PATH = REPO_ROOT / ".cache" / "enrichment" / "identity_audit.json"

STOPWORDS = {
    "de", "het", "een", "van", "en", "in", "op", "te", "met", "voor", "aan",
    "den", "der", "des", "bij", "uit", "om", "als", "is",
    "museum", "musea", "stichting", "nationaal", "koninklijk", "historisch",
    "stedelijk", "nederlands", "nederlandse", "the", "of", "and", "in", "at",
}


class MetaAndHeaderParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_chunks: List[str] = []
        self.h1_chunks: List[str] = []
        self.meta_description: str = ""
        self.body_text_chunks: List[str] = []
        self._current_tag: Optional[str] = None
        self._in_title = False
        self._in_h1 = False
        self._skip_tags = {"script", "style", "noscript", "svg"}
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        t = tag.lower()
        if t in self._skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if t == "title":
            self._in_title = True
        elif t == "h1":
            self._in_h1 = True
        elif t == "meta":
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            if attr_dict.get("name", "").lower() == "description":
                self.meta_description = attr_dict.get("content", "")

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if t == "title":
            self._in_title = False
        elif t == "h1":
            self._in_h1 = False

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        clean = data.strip()
        if not clean:
            return
        if self._in_title:
            self.title_chunks.append(clean)
        elif self._in_h1:
            self.h1_chunks.append(clean)
        elif len(self.body_text_chunks) < 50:
            self.body_text_chunks.append(clean)


def extract_page_identity(html: str) -> Dict[str, str]:
    parser = MetaAndHeaderParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    title = " ".join(parser.title_chunks).strip()
    h1 = " ".join(parser.h1_chunks).strip()
    desc = parser.meta_description.strip()
    preview = " ".join(parser.body_text_chunks[:20]).strip()
    return {
        "title": title,
        "h1": h1,
        "meta_description": desc,
        "body_preview": preview,
    }


import unicodedata


def normalize_token(t: str) -> str:
    """Decompose accents (e.g. ö -> o, é -> e) and remove non-alphanumeric chars."""
    decomposed = unicodedata.normalize("NFKD", t)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def get_distinctive_tokens(name: str, city: Optional[str]) -> Set[str]:
    """Extract distinctive tokens from name and city, decomposing accents and splitting hyphens."""
    # Replace hyphens/slashes with spaces to split compound parts
    split_name = name.replace("-", " ").replace("–", " ").replace("/", " ")
    raw_tokens = re.findall(r"\b\w+\b", split_name)
    tokens = set()
    for t in raw_tokens:
        norm = normalize_token(t)
        if len(norm) >= 3 and norm not in STOPWORDS:
            tokens.add(norm)

    # Also handle Dutch compound "museum" suffixes (e.g. "Molenmuseum" -> "molen")
    for t in list(tokens):
        if t.endswith("museum") and len(t) > 9:
            prefix = t[:-6]
            if len(prefix) >= 3 and prefix not in STOPWORDS:
                tokens.add(prefix)

    if city:
        split_city = city.replace("-", " ").replace("–", " ")
        city_tokens = re.findall(r"\b\w+\b", split_city)
        for ct in city_tokens:
            norm = normalize_token(ct)
            if len(norm) >= 3 and norm not in STOPWORDS:
                tokens.add(norm)
    return tokens


def check_identity(
    name: str,
    city: Optional[str],
    website_url: str,
    page_data: Dict[str, str],
) -> Tuple[str, Optional[str]]:
    """
    Check if fetched page identity matches museum name and city.
    Returns (status, reason):
      status in ('match', 'weak_match', 'suspicious', 'blocked_by_bot_protection', 'fetch_failed')
    """
    title = page_data.get("title", "")
    h1 = page_data.get("h1", "")
    desc = page_data.get("meta_description", "")
    preview = page_data.get("body_preview", "")

    norm_haystack_strong = normalize_token(f"{title} {h1}")
    norm_haystack_weak = normalize_token(f"{title} {h1} {desc} {preview}")

    tokens = get_distinctive_tokens(name, city)
    if not tokens:
        return "weak_match", "No distinctive tokens to verify against"

    # Check for direct matches in strong signals (title or H1)
    strong_hits = [t for t in tokens if t in norm_haystack_strong]
    if strong_hits:
        return "match", None

    # Check for match in weak signals (meta description or first paragraph)
    weak_hits = [t for t in tokens if t in norm_haystack_weak]
    if weak_hits:
        return "weak_match", f"Token(s) {weak_hits} found in meta description / body text only"

    # Nothing matched: flag as suspicious
    title_display = title if title else "(no title)"
    h1_display = h1 if h1 else "(no h1)"
    return "suspicious", (
        f"Neither distinctive name tokens {sorted(tokens)} nor city appear in "
        f"title: '{title_display}' or H1: '{h1_display}'"
    )


def run_identity_audit(limit: Optional[int] = None) -> Dict[str, Any]:
    """Run identity audit over active museums in data/museums.json."""
    if not MUSEUMS_JSON_PATH.exists():
        raise FileNotFoundError(f"{MUSEUMS_JSON_PATH} not found")

    with open(MUSEUMS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    museums = [m for m in data.get("museums", []) if m.get("status", "active") != "removed"]
    if limit:
        museums = museums[:limit]

    fetcher = PoliteFetcher()
    results = []
    suspicious = []
    missing_site = []

    print(f"Auditing identity for {len(museums)} active museums...")

    for i, m in enumerate(museums, 1):
        slug = m["slug"]
        name = m["name"]
        city = m.get("city")
        website = m.get("museum_website")

        if not website:
            missing_site.append({
                "slug": slug,
                "name": name,
                "city": city,
                "issue": "Missing museum_website",
            })
            results.append({
                "slug": slug,
                "name": name,
                "city": city,
                "website": None,
                "status": "missing_website",
                "details": "No website configured",
            })
            continue

        success, html, err = fetcher.fetch(website)
        if not success or not html:
            status = "blocked_by_bot_protection" if err == "blocked_by_bot_protection" else "fetch_failed"
            results.append({
                "slug": slug,
                "name": name,
                "city": city,
                "website": website,
                "status": status,
                "details": err,
            })
            continue

        page_data = extract_page_identity(html)
        status, reason = check_identity(name, city, website, page_data)

        rec = {
            "slug": slug,
            "name": name,
            "city": city,
            "website": website,
            "status": status,
            "title": page_data["title"],
            "h1": page_data["h1"],
            "details": reason,
        }
        results.append(rec)

        if status == "suspicious":
            suspicious.append(rec)
            print(f"  [!] SUSPICIOUS: {slug} ('{name}', {city}) -> {website}")
            print(f"      Title: {page_data['title']}")
            print(f"      H1:    {page_data['h1']}")

    summary = {
        "total_audited": len(museums),
        "matches": sum(1 for r in results if r["status"] == "match"),
        "weak_matches": sum(1 for r in results if r["status"] == "weak_match"),
        "missing_website": len(missing_site),
        "suspicious_count": len(suspicious),
        "fetch_failed_or_blocked": sum(1 for r in results if r["status"] in ("fetch_failed", "blocked_by_bot_protection")),
        "suspicious_records": suspicious,
        "missing_website_records": missing_site,
    }

    AUDIT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("=== IDENTITY AUDIT SUMMARY ===")
    print(f"Total museums checked:    {summary['total_audited']}")
    print(f"Confirmed matches:        {summary['matches']}")
    print(f"Weak matches:             {summary['weak_matches']}")
    print(f"Missing website:          {summary['missing_website']}")
    print(f"Fetch failed / protected: {summary['fetch_failed_or_blocked']}")
    print(f"Suspicious mismatches:    {summary['suspicious_count']}")
    print("=" * 60)

    if suspicious:
        print("\nSUSPICIOUS RECORDS:")
        for s in suspicious:
            print(f" - {s['slug']} ({s['name']}, {s['city']})")
            print(f"   URL:   {s['website']}")
            print(f"   Title: {s.get('title')}")
            print(f"   Issue: {s.get('details')}\n")

    return summary


if __name__ == "__main__":
    run_identity_audit()
