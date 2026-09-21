"""Tests for job specifications and loading."""

import pytest
from enrich.jobs.base import JobDefinition, list_available_jobs


def test_list_available_jobs():
    jobs = list_available_jobs()
    assert "price_adult" in jobs


def test_load_price_adult_job():
    job = JobDefinition.load("price_adult")
    assert job.field == "price_adult"
    assert "Single-Entry Adult" in job.title
    assert job.refresh_interval_days == 540

    props = job.output_schema.get("properties", {})
    assert "status" in props
    assert "primary_adult_eur" in props
    assert "free_for" in props
    assert "offerings" in props
    assert "quote" in props
    assert "entered_by" in props

    plaus = job.plausibility
    assert plaus.get("min_paid_eur") == 1.00
    assert plaus.get("max_paid_eur") == 45.00
    assert "duo" in plaus.get("forbidden_quote_keywords", [])


def test_load_nonexistent_job():
    with pytest.raises(FileNotFoundError):
        JobDefinition.load("non_existent_job_xyz")
