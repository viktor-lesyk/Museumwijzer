import pytest
from scraper.normalise import (
    normalise_city,
    normalise_postcode,
    normalise_province,
    normalise_text,
)


def test_normalise_text():
    assert normalise_text("  Huis   Zypendaal \n ") == "Huis Zypendaal"
    assert normalise_text("zypendaa\u0301l") == "zypendaál"
    assert normalise_text("") is None
    assert normalise_text(None) is None


def test_normalise_postcode():
    assert normalise_postcode("6814CL") == "6814 CL"
    assert normalise_postcode("6814  cl") == "6814 CL"
    assert normalise_postcode(" 1071 DJ ") == "1071 DJ"
    assert normalise_postcode("297 bp") == "297 BP"
    assert normalise_postcode(None) is None


def test_normalise_province():
    assert normalise_province("gelderland") == "Gelderland"
    assert normalise_province("Noord-Holland") == "Noord-Holland"
    assert normalise_province("  zuid-holland ") == "Zuid-Holland"
    assert normalise_province(None) is None


def test_normalise_city():
    aliases = {
        "'s-Gravenhage": "Den Haag",
        "The Hague": "Den Haag",
        "'s-Hertogenbosch": "Den Bosch",
    }
    assert normalise_city("'s-Gravenhage", aliases=aliases) == "Den Haag"
    assert normalise_city("the hague", aliases=aliases) == "Den Haag"
    assert normalise_city("Den Haag", aliases=aliases) == "Den Haag"
    assert normalise_city("'s-Hertogenbosch", aliases=aliases) == "Den Bosch"
    assert normalise_city("Amsterdam", aliases=aliases) == "Amsterdam"
    assert normalise_city("  Arnhem  ", aliases=aliases) == "Arnhem"
    assert normalise_city(None, aliases=aliases) is None
