"""Unit tests for the manual price recheck module."""

from unittest.mock import MagicMock, patch
import pytest

from enrich.fetch import PoliteFetcher
from enrich.recheck import verify_stored_source_url


def test_verify_stored_source_url_invalid_scheme():
    fetcher = MagicMock()
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "ftp://example.com", fetcher)
    assert ok is False
    assert "Invalid URL scheme" in reason

    ok, final_url, html, reason = verify_stored_source_url(museum, "", fetcher)
    assert ok is False
    assert "Missing or invalid" in reason


def test_verify_stored_source_url_disallowed_by_robots():
    fetcher = MagicMock()
    fetcher.robots.check_access.return_value = (False, "Disallowed by robots.txt")
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "https://example.com/tickets", fetcher)
    assert ok is False
    assert "Disallowed by robots.txt" in reason


def test_verify_stored_source_url_http_404():
    fetcher = MagicMock()
    fetcher.robots.check_access.return_value = (True, None)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    fetcher.session.get.return_value = mock_resp
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "https://example.com/tickets", fetcher)
    assert ok is False
    assert "HTTP 404" in reason


def test_verify_stored_source_url_redirect_external():
    fetcher = MagicMock()
    fetcher.robots.check_access.return_value = (True, None)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://external-ticket-seller.com/buy"
    fetcher.session.get.return_value = mock_resp
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "https://example.com/tickets", fetcher)
    assert ok is False
    assert "Redirected to external domain" in reason


def test_verify_stored_source_url_redirect_to_root():
    fetcher = MagicMock()
    fetcher.robots.check_access.return_value = (True, None)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/"
    fetcher.session.get.return_value = mock_resp
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "https://example.com/tickets/2024", fetcher)
    assert ok is False
    assert "Redirected from specific pricing page to homepage root" in reason


def test_verify_stored_source_url_no_price_keywords():
    fetcher = MagicMock()
    fetcher.robots.check_access.return_value = (True, None)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/tickets"
    mock_resp.text = "<html><body><h1>Over ons</h1><p>Wij zijn een kunstmuseum opgericht in 1950.</p></body></html>"
    fetcher.session.get.return_value = mock_resp
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "https://example.com/tickets", fetcher)
    assert ok is False
    assert "Page no longer contains pricing keywords" in reason


def test_verify_stored_source_url_success():
    fetcher = MagicMock()
    fetcher.robots.check_access.return_value = (True, None)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://tickets.example.com/prijzen"
    mock_resp.text = "<html><body><h1>Prijzen & Tickets</h1><p>Volwassenen entree: € 15,00 per persoon.</p></body></html>"
    fetcher.session.get.return_value = mock_resp
    museum = {"slug": "test-mus", "museum_website": "https://example.com"}

    ok, final_url, html, reason = verify_stored_source_url(museum, "https://tickets.example.com/prijzen", fetcher)
    assert ok is True
    assert final_url == "https://tickets.example.com/prijzen"
    assert "Volwassenen" in html
    assert reason is None
