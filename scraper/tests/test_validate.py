import pytest
from scraper.validate import validate_dataset


def make_valid_museum(slug: str, city: str = "Amsterdam", lat: float = 52.3579, lon: float = 4.8813):
    return {
        "slug": slug,
        "name": f"Museum {slug}",
        "province": "Noord-Holland",
        "city": city,
        "address": {"street": "Main Street 1", "postcode": "1000 AA", "city": city},
        "lat": lat,
        "lon": lon,
        "official_url": f"https://welkominhetmuseum.vriendenloterij.nl/nl/musea/{slug}/",
        "official_urls": {
            "nl": f"https://welkominhetmuseum.vriendenloterij.nl/nl/musea/{slug}/",
            "en": f"https://welkominhetmuseum.vriendenloterij.nl/en/musea/{slug}/",
            "uk": f"https://welkominhetmuseum.vriendenloterij.nl/uk/musea/{slug}/",
        },
        "first_seen": "2026-09-19",
        "last_seen": "2026-09-19",
    }


def test_validate_valid_dataset():
    # 195 museums
    dataset = [make_valid_museum(f"museum-{i}") for i in range(195)]
    is_valid, errors = validate_dataset(dataset)
    assert is_valid
    assert len(errors) == 0


def test_validate_count_too_low():
    # Only 50 museums (below 100 minimum)
    dataset = [make_valid_museum(f"museum-{i}") for i in range(50)]
    is_valid, errors = validate_dataset(dataset)
    assert not is_valid
    assert any("below minimum required" in err for err in errors)


def test_validate_duplicate_slugs():
    dataset = [make_valid_museum(f"museum-{i}") for i in range(194)]
    dataset.append(make_valid_museum("museum-0"))  # duplicate
    is_valid, errors = validate_dataset(dataset)
    assert not is_valid
    assert any("Duplicate" in err for err in errors)


def test_validate_low_geocoding_completeness():
    # 195 museums, but 20 missing coords (completeness ~89.7% < 95%)
    dataset = [make_valid_museum(f"museum-{i}") for i in range(195)]
    for i in range(20):
        dataset[i]["lat"] = None
        dataset[i]["lon"] = None

    is_valid, errors = validate_dataset(dataset)
    assert not is_valid
    assert any("minimum required: 95.0%" in err for err in errors)


def test_validate_invalid_official_host():
    dataset = [make_valid_museum(f"museum-{i}") for i in range(195)]
    dataset[0]["official_url"] = "https://phishing-site.example.com/musea/museum-0/"
    is_valid, errors = validate_dataset(dataset)
    assert not is_valid
    assert any("Invalid official_url host" in err for err in errors)
