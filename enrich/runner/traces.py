"""Audit trace logging with automatic secret scrubbing."""

import json
from pathlib import Path
import re
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRACES_DIR = REPO_ROOT / ".cache" / "enrichment" / "traces"

SECRET_PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{10,}",
    r"tvly-[a-zA-Z0-9_-]{10,}",
    r"Bearer\s+[a-zA-Z0-9_.-]{10,}",
    r"(?i)(api[_-]?key|auth[_-]?token)\s*[:=]\s*['\"]?[a-zA-Z0-9_.-]{10,}['\"]?",
]


def scrub_secrets(obj: Any) -> Any:
    """Recursively scrub known API key patterns from strings, dictionaries, and lists."""
    if isinstance(obj, str):
        cleaned = obj
        for pat in SECRET_PATTERNS:
            cleaned = re.sub(pat, "[SCRUBBED_SECRET]", cleaned)
        return cleaned
    elif isinstance(obj, dict):
        return {k: scrub_secrets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [scrub_secrets(item) for item in obj]
    return obj


def save_trace(slug: str, trace_data: Dict[str, Any], traces_dir: Path = TRACES_DIR) -> Path:
    """Save scrubbed trace to disk for auditability."""
    traces_dir.mkdir(parents=True, exist_ok=True)
    safe_trace = scrub_secrets(trace_data)
    trace_path = traces_dir / f"{slug}.json"
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(safe_trace, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return trace_path
