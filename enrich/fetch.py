"""Polite, rate-limited HTTP fetcher for museum enrichment with raw caching and provenance tracking."""

from html.parser import HTMLParser
import hashlib
import logging
import os
from pathlib import Path
import re
import time
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
import requests

from .robots import RobotsChecker

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "enrichment" / "pages"
PROJECT_REPO_URL = os.environ.get("MUSEUMWIJZER_REPO_URL", "https://github.com/museumwijzer/museumwijzer")
CONTACT_EMAIL = os.environ.get("MUSEUMWIJZER_CONTACT", "contact-email-not-configured")
DEFAULT_USER_AGENT = f"Museumwijzer/1.0 (+{PROJECT_REPO_URL}; contact: {CONTACT_EMAIL})"
MIN_REQUEST_INTERVAL = 1.0  # seconds between requests per host


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        if tag.lower() == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    clean = v.strip().split("#")[0]
                    if clean and not clean.startswith(("mailto:", "tel:", "javascript:")):
                        full = urljoin(self.base_url, clean)
                        self.links.append(full)


class PoliteFetcher:
    def __init__(
        self,
        user_agent: Optional[str] = None,
        cache_dir: Path = CACHE_DIR,
        min_interval: float = MIN_REQUEST_INTERVAL,
    ):
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.robots = RobotsChecker(user_agent=self.user_agent)
        self._last_request_time: Dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl,en;q=0.8",
        })
        # Provenance: map of source_url -> set of discovered target_urls
        self.link_graph: Dict[str, Set[str]] = {}

    def _wait_for_rate_limit(self, target_url: str):
        host = urlparse(target_url).netloc.lower()
        now = time.time()
        last = self._last_request_time.get(host, 0.0)
        elapsed = now - last
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            time.sleep(sleep_time)
        self._last_request_time[host] = time.time()

    def _cache_key(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        host = urlparse(url).netloc.lower().replace(":", "_")
        return self.cache_dir / f"{host}_{h}.html"

    def _record_links(self, page_url: str, html: str):
        parser = LinkExtractor(base_url=page_url)
        try:
            parser.feed(html)
        except Exception:
            pass
        self.link_graph[page_url] = set(parser.links)

    def is_reached_from(self, target_url: str, origin_url: str, max_depth: int = 2) -> bool:
        """Check if target_url was reached by following links starting at origin_url."""
        norm_target = target_url.rstrip("/").lower()
        norm_origin = origin_url.rstrip("/").lower()
        if norm_target == norm_origin:
            return True

        # BFS over link graph
        visited = set()
        queue = [(origin_url, 0)]
        while queue:
            curr, depth = queue.pop(0)
            if curr in visited or depth >= max_depth:
                continue
            visited.add(curr)
            for neighbor in self.link_graph.get(curr, set()):
                if neighbor.rstrip("/").lower() == norm_target:
                    return True
                if depth + 1 < max_depth:
                    queue.append((neighbor, depth + 1))
        return False

    def fetch(self, url: str, force: bool = False) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Fetch a URL respecting robots.txt, bot protections, and rate limits.
        Returns (success, content_str, error_or_skip_reason).
        """
        # 1. Check robots.txt and known bot-protection
        allowed, reason = self.robots.check_access(url)
        if not allowed:
            logger.warning(f"Robots check disallowed URL {url}: {reason}")
            return False, None, reason

        # 2. Check disk cache
        cache_file = self._cache_key(url)
        if not force and cache_file.exists():
            try:
                content = cache_file.read_text(encoding="utf-8", errors="ignore")
                self._record_links(url, content)
                return True, content, None
            except Exception as e:
                logger.warning(f"Cache read error for {url}: {e}")

        # 3. Rate-limit wait
        self._wait_for_rate_limit(url)

        # 4. Perform HTTP GET
        try:
            logger.info(f"Fetching {url}...")
            resp = self.session.get(url, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                text = resp.text
                cache_file.write_text(text, encoding="utf-8")
                self._record_links(url, text)
                return True, text, None
            elif resp.status_code in (401, 403):
                logger.warning(f"HTTP {resp.status_code} for {url} (bot protection).")
                return False, None, "blocked_by_bot_protection"
            else:
                msg = f"HTTP {resp.status_code}"
                return False, None, msg
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return False, None, str(e)
