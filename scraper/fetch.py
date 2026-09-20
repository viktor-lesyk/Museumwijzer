import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional, Tuple
import requests

from .config import (
    HTTP_CACHE_DIR,
    MIN_REQUEST_INTERVAL,
    SOURCE_BASE_URL,
    SOURCE_LIST_URL,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class Fetcher:
    """Polite HTTP fetcher with rate limiting, conditional caching, and Next.js fallback."""

    def __init__(self, cache_dir=HTTP_CACHE_DIR, min_interval: float = MIN_REQUEST_INTERVAL):
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self) -> None:
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def _get_cache_paths(self, url: str) -> Tuple[Path, Path]:
        from pathlib import Path
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        meta_path = self.cache_dir / f"{cache_key}.meta.json"
        data_path = self.cache_dir / f"{cache_key}.data"
        return meta_path, data_path

    def fetch_url(self, url: str, use_cache: bool = True) -> Tuple[int, bytes, Dict[str, str]]:
        """Fetch URL with ETag / Last-Modified caching and rate limiting."""
        meta_path, data_path = self._get_cache_paths(url)
        headers: Dict[str, str] = {}

        if use_cache and meta_path.exists() and data_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if "etag" in meta:
                    headers["If-None-Match"] = meta["etag"]
                if "last_modified" in meta:
                    headers["If-Modified-Since"] = meta["last_modified"]
            except Exception as e:
                logger.warning(f"Error reading cache metadata for {url}: {e}")

        self._rate_limit()

        try:
            resp = self.session.get(url, headers=headers, timeout=20)
        except requests.RequestException as e:
            logger.error(f"Network error fetching {url}: {e}")
            # If network error but cache exists, return cached data as fallback
            if data_path.exists():
                logger.info(f"Using stale cached response for {url}")
                with open(data_path, "rb") as f:
                    return 200, f.read(), {}
            raise

        if resp.status_code == 304 and data_path.exists():
            logger.debug(f"Cache hit (304 Not Modified): {url}")
            with open(data_path, "rb") as f:
                return 200, f.read(), resp.headers

        if resp.status_code == 200 and use_cache:
            try:
                with open(data_path, "wb") as f:
                    f.write(resp.content)
                meta = {
                    "url": url,
                    "etag": resp.headers.get("ETag"),
                    "last_modified": resp.headers.get("Last-Modified"),
                    "fetched_at": time.time(),
                }
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write cache for {url}: {e}")

        return resp.status_code, resp.content, resp.headers

    def fetch_list_page(self) -> Tuple[str, Dict[str, Any]]:
        """Fetch list page HTML and extract the __NEXT_DATA__ JSON payload and buildId."""
        status_code, content, _ = self.fetch_url(SOURCE_LIST_URL)
        if status_code != 200:
            raise RuntimeError(f"Failed to fetch list page: HTTP {status_code}")

        html = content.decode("utf-8")
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not match:
            raise ValueError("Could not find __NEXT_DATA__ script in list page HTML")

        next_data = json.loads(match.group(1))
        build_id = next_data.get("buildId", "")
        return build_id, next_data

    def fetch_detail_story(self, slug: str, build_id: str) -> Optional[Dict[str, Any]]:
        """Fetch museum detail story via _next/data JSON with retry and HTML fallback."""
        # 1. Try _next/data JSON
        json_url = f"{SOURCE_BASE_URL}/_next/data/{build_id}/nl/musea/{slug}.json"
        try:
            status, content, _ = self.fetch_url(json_url)
            if status == 200:
                data = json.loads(content.decode("utf-8"))
                story = data.get("pageProps", {}).get("story")
                if story:
                    return story
        except Exception as e:
            logger.warning(f"Failed to fetch {json_url}: {e}")

        # 2. If 404 or missing story, refresh buildId and retry once
        logger.info(f"Retrying {slug} with refreshed buildId...")
        try:
            new_build_id, _ = self.fetch_list_page()
            if new_build_id and new_build_id != build_id:
                retry_url = f"{SOURCE_BASE_URL}/_next/data/{new_build_id}/nl/musea/{slug}.json"
                status, content, _ = self.fetch_url(retry_url)
                if status == 200:
                    data = json.loads(content.decode("utf-8"))
                    story = data.get("pageProps", {}).get("story")
                    if story:
                        return story
        except Exception as e:
            logger.warning(f"Error during buildId refresh for {slug}: {e}")

        # 3. Fallback: fetch detail page HTML and extract __NEXT_DATA__
        html_url = f"{SOURCE_BASE_URL}/nl/musea/{slug}/"
        logger.info(f"Falling back to HTML fetch for {slug}: {html_url}")
        try:
            status, content, _ = self.fetch_url(html_url)
            if status == 200:
                html = content.decode("utf-8")
                match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
                if match:
                    data = json.loads(match.group(1))
                    story = data.get("props", {}).get("pageProps", {}).get("story")
                    if story:
                        return story
        except Exception as e:
            logger.error(f"HTML fallback failed for {slug}: {e}")

        return None
