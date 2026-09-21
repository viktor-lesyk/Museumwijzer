"""Data models for museum enrichment (pricing and offerings)."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OfferingInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    audience: str
    amount_eur: Optional[float] = None
    label: str
    conditions: Optional[str] = None


class PriceInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "unknown"
    primary_adult_eur: Optional[float] = None
    adult_eur: Optional[float] = None
    free_for: List[str] = Field(default_factory=list)
    combo_available: Optional[bool] = None
    offerings: List[OfferingInfo] = Field(default_factory=list)
    quote: Optional[str] = None
    source_url: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    confidence: Optional[str] = Field(default=None, description="high, medium, low, or blocked_by_bot_protection")
    entered_by: Optional[str] = "agent"
    mode: Optional[str] = None
    extractor_model: Optional[str] = None
    verifier_model: Optional[str] = None
    checked_on: Optional[str] = None

    @field_validator("quote")
    @classmethod
    def validate_quote_word_count(cls, v: Optional[str]) -> Optional[str]:
        if v:
            words = v.split()
            if len(words) > 15:
                raise ValueError(f"Quote exceeds 15 words limit: '{v}' ({len(words)} words)")
        return v


class MuseumEnrichment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    name: str
    categories: Optional[List[str]] = None
    price: Optional[PriceInfo] = None


class EnrichmentFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str = "1.0"
    random_seed: int = 42
    total_pilot_museums: int = 20
    museums: List[MuseumEnrichment]
