from pathlib import Path
import pytest
from scraper.geocode import Geocoder


def test_geocoder_extract_coords():
    geocoder = Geocoder(cache_path=Path("/tmp/test-geocode-cache.json"))
    # Valid doc in NL
    doc_nl = {"centroide_ll": "POINT(4.881323 52.357925)"}
    lat, lon = geocoder._extract_coords(doc_nl)
    assert lat == 52.357925
    assert lon == 4.881323

    # Coordinates outside NL (e.g. Paris, France)
    doc_foreign = {"centroide_ll": "POINT(2.3522 48.8566)"}
    lat_f, lon_f = geocoder._extract_coords(doc_foreign)
    assert lat_f is None
    assert lon_f is None


def test_geocoder_cache(tmp_path):
    cache_file = tmp_path / "geocode-cache.json"
    geocoder = Geocoder(cache_path=cache_file)

    # Pre-populate cache
    slug = "test-museum"
    geocoder.cache[slug] = {
        "address_sig": "1071 DJ|Museumplein 6|Amsterdam",
        "lat": 52.357925,
        "lon": 4.881323,
        "city": "Amsterdam",
        "weergavenaam": "Museumplein 6, 1071DJ Amsterdam",
    }
    geocoder.save_cache()

    # Re-instantiate and verify cache read
    new_geocoder = Geocoder(cache_path=cache_file)
    res = new_geocoder.geocode_museum(
        slug=slug,
        name="Test Museum",
        street="Museumplein 6",
        postcode="1071 DJ",
        city="Amsterdam",
    )
    assert res.lat == 52.357925
    assert res.lon == 4.881323
    assert res.woonplaats == "Amsterdam"


def test_sanity_checks_leerdam():
    geocoder = Geocoder(cache_path=Path("/tmp/test-geocode-cache.json"))
    # Leerdam: southern border of Utrecht (Vijfheerenlanden), lat 51.890, lon 5.093
    res = geocoder.check_sanity(
        slug="nationaal-glasmuseum",
        lat=51.890196,
        lon=5.093885,
        source_province="Utrecht",
        pdok_province="Utrecht",
    )
    assert res["has_issues"] is False
    assert res["is_outlier"] is False
    assert len(res["issues"]) == 0


def test_sanity_checks_vlieland():
    geocoder = Geocoder(cache_path=Path("/tmp/test-geocode-cache.json"))
    # Vlieland: westernmost Wadden island, lon 5.067, Fryslân vs Friesland normalisation
    res = geocoder.check_sanity(
        slug="Museum-Tromps-Huys",
        lat=53.29539,
        lon=5.06742,
        source_province="Friesland",
        pdok_province="Fryslân",
    )
    assert res["has_issues"] is False
    assert res["is_outlier"] is False
    assert len(res["issues"]) == 0


def test_sanity_checks_groenlo_mismatch():
    geocoder = Geocoder(cache_path=Path("/tmp/test-geocode-cache.json"))
    # Groenlo: upstream source tagged province as 'Groningen', but PDOK returns 'Gelderland'
    res_mismatch = geocoder.check_sanity(
        slug="museum-tachtigjarige-oorlog",
        lat=52.042346,
        lon=6.617773,
        source_province="Groningen",
        pdok_province="Gelderland",
    )
    assert res_mismatch["has_issues"] is True
    assert any("Province mismatch" in msg for msg in res_mismatch["issues"])

    # When corrected to Gelderland via override, sanity check passes
    res_corrected = geocoder.check_sanity(
        slug="museum-tachtigjarige-oorlog",
        lat=52.042346,
        lon=6.617773,
        source_province="Gelderland",
        pdok_province="Gelderland",
    )
    assert res_corrected["has_issues"] is False

