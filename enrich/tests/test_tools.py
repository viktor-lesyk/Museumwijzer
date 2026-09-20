"""Tests for allowlisted tools, robots checking, and prompt injection defense."""

from enrich.fetch import LinkExtractor, PoliteFetcher
from enrich.robots import RobotsChecker
from enrich.tools.fetch_page import sanitize_html_for_agent, execute_fetch_page
from enrich.tools.web_search import execute_web_search


def test_link_extractor():
    html = """
    <html>
      <body>
        <a href="/tickets">Tickets</a>
        <a href="https://example.com/plan">Plan your visit</a>
        <a href="mailto:info@example.com">Email</a>
      </body>
    </html>
    """
    extractor = LinkExtractor(base_url="https://example.com/home")
    extractor.feed(html)
    assert "https://example.com/tickets" in extractor.links
    assert "https://example.com/plan" in extractor.links
    assert not any(l.startswith("mailto:") for l in extractor.links)


def test_sanitize_html_and_injection_delimiters():
    html = """
    <html>
      <head><title>Test Museum</title><style>.hidden { display: none; }</style></head>
      <body>
        <script>alert('malicious')</script>
        <h1>Welcome to Test Museum</h1>
        <p>Volwassenen ticket: € 15,00</p>
        <a href="/tickets">Tickets info</a>
      </body>
    </html>
    """
    sanitized = sanitize_html_for_agent(html, "https://testmuseum.nl/")
    text = sanitized["text"]
    assert "alert('malicious')" not in text
    assert "display: none" not in text
    assert "Volwassenen ticket: € 15,00" in text


def test_execute_fetch_page_delimiters():
    class DummyFetcher:
        def fetch(self, url):
            return True, "<h1>Price</h1><p>Adult: € 10</p>", None

    res = execute_fetch_page("https://example.com/tickets", DummyFetcher())
    assert res["status"] == "success"
    assert "<untrusted_web_content url=\"https://example.com/tickets\">" in res["content"]
    assert "</untrusted_web_content>" in res["content"]


def test_robots_bot_protection_detection():
    checker = RobotsChecker()
    # Test cloudflare detection logic
    is_cf = checker._is_cloudflare_challenge(403, {"server": "cloudflare"}, "error 1020")
    assert is_cf is True

    is_cf_ray = checker._is_cloudflare_challenge(503, {"cf-ray": "12345"}, "Just a moment...")
    assert is_cf_ray is True


def test_web_search_fallback():
    # Calling web_search without api keys returns safe fallback
    res = execute_web_search("Rijksmuseum tickets")
    assert "results" in res
    assert "note" in res
    assert "POINTERS ONLY" in res["note"] or "not configured" in res["note"]
