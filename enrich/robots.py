"""Robots.txt parser and checker for museum sites with bot protection detection."""

import logging
from pathlib import Path
from typing import Dict, Optional, Set, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import requests

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ROBOTS_CACHE_DIR = REPO_ROOT / ".cache" / "enrichment" / "robots"


class RobotsChecker:
    def __init__(self, user_agent: str = "Museumwijzer/1.0", cache_dir: Path = ROBOTS_CACHE_DIR):
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._parsers: Dict[str, RobotFileParser] = {}
        self._bot_protected_hosts: Set[str] = set()

    def _get_robots_url(self, target_url: str) -> str:
        parsed = urlparse(target_url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _is_cloudflare_challenge(self, status_code: int, headers: Dict[str, str], body: str) -> bool:
        if status_code in (403, 503):
            server = headers.get("server", "").lower()
            if "cloudflare" in server:
                return True
            if "cf-ray" in [k.lower() for k in headers.keys()]:
                return True
            if "attention required! | cloudflare" in body.lower() or "just a moment..." in body.lower():
                return True
            return True  # 403 on robots.txt is bot-protection barrier
        return False

    def get_parser_for_host(self, target_url: str) -> Tuple[RobotFileParser, Optional[str]]:
        parsed = urlparse(target_url)
        host_key = parsed.netloc.lower()
        if host_key in self._bot_protected_hosts:
            rp = RobotFileParser()
            rp.parse(["User-agent: *", "Disallow: /"])
            return rp, "blocked_by_bot_protection"

        if host_key in self._parsers:
            return self._parsers[host_key], None

        rp = RobotFileParser()
        robots_url = self._get_robots_url(target_url)
        cache_file = self.cache_dir / f"{host_key}.txt"

        if cache_file.exists():
            try:
                content = cache_file.read_text(encoding="utf-8", errors="ignore")
                if content.startswith("# BLOCKED_BY_BOT_PROTECTION"):
                    self._bot_protected_hosts.add(host_key)
                    rp.parse(["User-agent: *", "Disallow: /"])
                    return rp, "blocked_by_bot_protection"
                rp.parse(content.splitlines())
                self._parsers[host_key] = rp
                return rp, None
            except Exception as e:
                logger.warning(f"Error reading cached robots.txt for {host_key}: {e}")

        # Fetch live robots.txt
        try:
            logger.info(f"Fetching robots.txt from {robots_url}...")
            resp = requests.get(robots_url, headers={"User-Agent": self.user_agent}, timeout=10)
            if self._is_cloudflare_challenge(resp.status_code, dict(resp.headers), resp.text):
                logger.warning(f"Host {host_key} returned HTTP {resp.status_code} on robots.txt (bot protection).")
                self._bot_protected_hosts.add(host_key)
                cache_file.write_text("# BLOCKED_BY_BOT_PROTECTION\nUser-agent: *\nDisallow: /\n", encoding="utf-8")
                rp.parse(["User-agent: *", "Disallow: /"])
                return rp, "blocked_by_bot_protection"
            elif resp.status_code == 200:
                content = resp.text
                cache_file.write_text(content, encoding="utf-8")
                rp.parse(content.splitlines())
            else:
                # 404 or other 4xx means no robots restriction
                rp.allow_all = True
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt for {host_key} ({e}). Assuming allowed.")
            rp.allow_all = True

        self._parsers[host_key] = rp
        return rp, None

    def check_access(self, target_url: str) -> Tuple[bool, Optional[str]]:
        """
        Check whether fetching target_url is allowed.
        Returns (allowed, skip_reason). If allowed=False, skip_reason is 'blocked_by_bot_protection'
        or 'blocked_by_robots'.
        """
        rp, bot_reason = self.get_parser_for_host(target_url)
        if bot_reason:
            return False, bot_reason

        allowed = rp.can_fetch(self.user_agent, target_url) or rp.can_fetch("*", target_url)
        if not allowed:
            return False, "blocked_by_robots"
        return True, None

    def is_allowed(self, target_url: str) -> bool:
        allowed, _ = self.check_access(target_url)
        return allowed
