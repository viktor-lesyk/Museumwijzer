"""Allowlisted tool: fetch_page. Fetches and sanitizes web pages for LLM consumption."""

from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from enrich.fetch import PoliteFetcher


class TextAndLinksParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.text_chunks: List[str] = []
        self.links: List[Tuple[str, str]] = []  # (href, text)
        self._skip_depth = 0
        self._skip_tags = {"script", "style", "noscript", "svg", "header", "footer", "nav"}
        self._current_a_href: Optional[str] = None
        self._current_a_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        t = tag.lower()
        if t in self._skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if t == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    clean = v.strip().split("#")[0]
                    if clean and not clean.startswith(("mailto:", "tel:", "javascript:")):
                        self._current_a_href = urljoin(self.base_url, clean)
                        self._current_a_text = []

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if t == "a" and self._current_a_href:
            link_text = " ".join(self._current_a_text).strip()
            self.links.append((self._current_a_href, link_text))
            self._current_a_href = None
            self._current_a_text = []

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        clean = data.strip()
        if clean:
            self.text_chunks.append(clean)
            if self._current_a_href is not None:
                self._current_a_text.append(clean)


FETCH_PAGE_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "fetch_page",
        "description": "Fetch a webpage URL, returning sanitized text content and relevant links. Respects robots.txt and rate limits.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The exact HTTP or HTTPS URL to fetch."
                }
            },
            "required": ["url"]
        }
    }
}


def sanitize_html_for_agent(html: str, base_url: str, max_chars: int = 15000) -> Dict[str, Any]:
    parser = TextAndLinksParser(base_url)
    try:
        parser.feed(html)
    except Exception:
        pass

    full_text = "\n".join(parser.text_chunks)
    # Compress multiple whitespaces
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n... [content truncated for brevity]"

    # Filter discovered links for pricing/visiting hints
    base_netloc = urlparse(base_url).netloc.lower()
    keywords = ["ticket", "kaart", "toegang", "tarief", "prijs", "prijzen", "admission", "bezoek", "plan", "praktisch", "open"]
    relevant_links = []
    seen = set()

    for href, link_text in parser.links:
        parsed = urlparse(href)
        # stay on same host
        if parsed.netloc.lower() == base_netloc or parsed.netloc.lower().endswith("." + base_netloc):
            combined = f"{href} {link_text}".lower()
            if any(k in combined for k in keywords) and href not in seen and href != base_url:
                seen.add(href)
                relevant_links.append({"url": href, "text": link_text[:50]})
                if len(relevant_links) >= 8:
                    break

    return {
        "text": full_text,
        "suggested_links": relevant_links,
    }


def execute_fetch_page(url: str, fetcher: PoliteFetcher) -> Dict[str, Any]:
    """Execute fetch_page tool returning payload wrapped with injection defense delimiters."""
    success, html, err = fetcher.fetch(url)
    if not success or not html:
        return {
            "url": url,
            "status": "error",
            "error": err or "Failed to retrieve page content",
        }

    parsed = sanitize_html_for_agent(html, url)
    # Wrap text in prompt injection delimiters
    safe_content = f"<untrusted_web_content url=\"{url}\">\n{parsed['text']}\n</untrusted_web_content>"

    return {
        "url": url,
        "status": "success",
        "content": safe_content,
        "suggested_links": parsed["suggested_links"],
    }
