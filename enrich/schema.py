"""Data models for museum enrichment pilot (pricing and categories)."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PriceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adult_eur: Optional[float] = None
    note: Optional[str] = None
    source_url: Optional[str] = None
    quote: Optional[str] = None
    checked_on: Optional[str] = None
    confidence: Optional[str] = Field(default=None, description="high, medium, low, or blocked_by_robots")

    @field_validator("quote")
    @classmethod
    def validate_quote_word_count(cls, v: Optional[str]) -> Optional[str]:
        if v:
            words = v.split()
            if len(words) > 15:
                raise ValueError(f"Quote exceeds 15 words limit: '{v}' ({len(words)} words)")
        return v


class MuseumEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    categories: Optional[List[str]] = None
    price: Optional[PriceInfo] = None


class EnrichmentFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pilot_version: str = "1.0"
    random_seed: int = 42
    total_pilot_museums: int = 20
    museums: List[MuseumEnrichment]
