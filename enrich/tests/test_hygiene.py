"""Hygiene and secret detection tests."""

from pathlib import Path
import re
import subprocess
from enrich.runner.traces import scrub_secrets

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_scrub_secrets_function():
    # Construct test secret patterns dynamically to avoid false positives in git grep
    bearer_token = "Bearer " + "sk-1234567890abcdef12345"
    tavily_key = "tvly-" + "dev-abcdef1234567890"
    sk_key = "sk-" + "abcdef1234567890"

    raw = {
        "headers": {"Authorization": bearer_token},
        "api_key": tavily_key,
        "nested": [
            f"Contact: {sk_key}",
            "Safe string without secrets",
        ],
    }
    scrubbed = scrub_secrets(raw)

    assert "Bearer sk-" not in json_str(scrubbed)
    assert "tvly-" not in json_str(scrubbed)
    assert "[SCRUBBED_SECRET]" in scrubbed["headers"]["Authorization"]
    assert "[SCRUBBED_SECRET]" in scrubbed["api_key"]
    assert "[SCRUBBED_SECRET]" in scrubbed["nested"][0]
    assert scrubbed["nested"][1] == "Safe string without secrets"


def json_str(obj):
    import json
    return json.dumps(obj)


def test_no_secrets_in_tracked_git_files():
    """Ensure no real API keys, bearer tokens, or user home paths are committed to git."""
    res = subprocess.run(
        [
            "git",
            "grep",
            "-I",
            "-iE",
            r"(tvly-[a-zA-Z0-9_-]{10,}|sk-[a-zA-Z0-9_-]{15,}|Bearer\s+[a-zA-Z0-9_.-]{15,})",
            "--",
            ":!enrich/tests/test_hygiene.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # Output should be empty (code 1 means grep found no matches)
    assert res.returncode == 1 or res.stdout.strip() == "", f"Found forbidden secret pattern in tracked files:\n{res.stdout}"

