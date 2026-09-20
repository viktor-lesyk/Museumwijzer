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
        "programmes": ["welkom-in-het-museum"],
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


def test_validate_missing_programmes():
    dataset = [make_valid_museum(f"museum-{i}") for i in range(195)]
    dataset[0]["programmes"] = []
    is_valid, errors = validate_dataset(dataset)
    assert not is_valid
    assert any("Missing or invalid programmes array" in err for err in errors)


def test_removed_museums_excluded_from_active_count():
    """Removed museums do not count toward the active total; 195 active + 5 removed = still valid."""
    dataset = [make_valid_museum(f"museum-{i}") for i in range(195)]
    for i in range(5):
        removed = make_valid_museum(f"old-museum-{i}")
        removed["status"] = "removed"
        dataset.append(removed)
    is_valid, errors = validate_dataset(dataset)
    assert is_valid, f"Expected valid dataset, got errors: {errors}"


def test_removed_museums_excluded_from_turnover():
    """A museum going from active→removed does NOT trigger the turnover alarm because
    turnover is computed on active slugs only.  The slug simply disappears from the
    active set, which is the normal expected behaviour."""
    prev_active = [make_valid_museum(f"museum-{i}") for i in range(195)]
    # Simulate a new run where museum-0 is soft-deleted (removed from active set)
    curr_active = [make_valid_museum(f"museum-{i}") for i in range(1, 195)]  # 194 active
    removed_record = make_valid_museum("museum-0")
    removed_record["status"] = "removed"
    curr_full = curr_active + [removed_record]

    previous_dataset = {"museums": prev_active}
    # 1 removed out of 195 = 0.51%, well below 10% threshold
    is_valid, errors = validate_dataset(curr_full, previous_dataset)
    assert is_valid, f"Expected valid dataset after soft-delete, got errors: {errors}"


def test_active_count_below_minimum_with_removed_records():
    """If too many active museums are removed so active count < 100, validation fails."""
    dataset = [make_valid_museum(f"museum-{i}") for i in range(90)]  # 90 active
    for i in range(200):
        removed = make_valid_museum(f"old-{i}")
        removed["status"] = "removed"
        dataset.append(removed)
    is_valid, errors = validate_dataset(dataset)
    assert not is_valid
    assert any("below minimum required" in err for err in errors)


def test_shared_resources_audit_whitelist():
    from scraper.validate import check_shared_resources

    # Whitelisted shared site
    m1 = make_valid_museum("huygens-museum-hofwijck")
    m1["museum_website"] = "https://huygensmuseum.nl/"
    m1["address"] = {"street": "Westeinde 2", "postcode": "2275 AD", "city": "Voorburg"}
    m2 = make_valid_museum("huygens-museum-notarishuis")
    m2["museum_website"] = "https://huygensmuseum.nl/"
    m2["address"] = {"street": "Herenstraat 101", "postcode": "2271 CA", "city": "Voorburg"}

    # Whitelisted shared address
    m3 = make_valid_museum("domunder")
    m3["address"] = {"street": "Domplein 9", "postcode": "3512 JC", "city": "Utrecht"}
    m4 = make_valid_museum("paleis-lofen")
    m4["address"] = {"street": "Domplein 9", "postcode": "3512 JC", "city": "Utrecht"}

    warnings = check_shared_resources([m1, m2, m3, m4])
    assert len(warnings) == 0, f"Expected zero warnings for whitelisted cases, got {warnings}"


def test_shared_resources_audit_unexpected():
    from scraper.validate import check_shared_resources

    m1 = make_valid_museum("museum-a")
    m1["museum_website"] = "https://example.com/site"
    m2 = make_valid_museum("museum-b")
    m2["museum_website"] = "https://example.com/site"
    m2["address"] = m1["address"]  # duplicate address

    warnings = check_shared_resources([m1, m2])
    assert len(warnings) == 2
    assert any("Unexpected shared museum_website" in w for w in warnings)
    assert any("Unexpected shared address" in w for w in warnings)
