import json
from pathlib import Path
import pytest

from scraper.parse import parse_museum_story, build_official_urls

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_build_official_urls():
    canonical, localized = build_official_urls("huis-zypendaal")
    assert canonical == "https://welkominhetmuseum.vriendenloterij.nl/nl/musea/huis-zypendaal/"
    assert localized["nl"] == "https://welkominhetmuseum.vriendenloterij.nl/nl/musea/huis-zypendaal/"
    assert localized["en"] == "https://welkominhetmuseum.vriendenloterij.nl/en/musea/huis-zypendaal/"
    assert localized["uk"] == "https://welkominhetmuseum.vriendenloterij.nl/uk/musea/huis-zypendaal/"


def test_parse_huis_zypendaal_fixture():
    fixture_path = FIXTURES_DIR / "detail_huis_zypendaal_sanitized.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    story = data["pageProps"]["story"]
    parsed = parse_museum_story(story)

    assert parsed.slug == "huis-zypendaal"
    assert parsed.name == "Huis Zypendaal"
    assert parsed.province == "Gelderland"
    assert parsed.street == "Zijpendaalseweg 44"
    assert parsed.postcode == "6814 CL"
    assert parsed.city == "Arnhem"
    assert parsed.museum_website == "https://www.glk.nl/zypendaal/huis-zypendaal"
    assert parsed.official_url == "https://welkominhetmuseum.vriendenloterij.nl/nl/musea/huis-zypendaal/"
    assert parsed.official_urls["en"] == "https://welkominhetmuseum.vriendenloterij.nl/en/musea/huis-zypendaal/"
    assert parsed.official_urls["uk"] == "https://welkominhetmuseum.vriendenloterij.nl/uk/musea/huis-zypendaal/"
    assert parsed.programmes == ["welkom-in-het-museum"]

    # Whitelist check: ensure creative fields are not present on model
    dict_repr = parsed.model_dump()
    forbidden_keys = {"teaser", "image", "content", "description", "ankeilerImage"}
    for key in forbidden_keys:
        assert key not in dict_repr


def test_parse_van_gogh_museum_fixture():
    fixture_path = FIXTURES_DIR / "detail_van_gogh_museum_sanitized.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    story = data["pageProps"]["story"]
    parsed = parse_museum_story(story)

    assert parsed.slug == "van-gogh-museum"
    assert parsed.name == "Van Gogh Museum"
    assert parsed.province == "Noord-Holland"
    assert parsed.street == "Museumplein 6"
    assert parsed.postcode == "1071 DJ"
    assert parsed.city == "Amsterdam"
    assert parsed.museum_website == "https://www.vangoghmuseum.nl/nl"


def test_parse_watersnoodmuseum_fixture():
    fixture_path = FIXTURES_DIR / "detail_watersnoodmuseum_sanitized.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    story = data["pageProps"]["story"]
    parsed = parse_museum_story(story)

    assert parsed.slug == "watersnoodmuseum"
    assert parsed.name == "Watersnoodmuseum"
    assert parsed.province == "Zeeland"
    assert parsed.street == "Weg van de Buitenlandse Pers 5"
    assert parsed.postcode == "4305 RJ"
    assert parsed.city == "Ouwerkerk"
    assert parsed.museum_website == "https://watersnoodmuseum.nl/"
