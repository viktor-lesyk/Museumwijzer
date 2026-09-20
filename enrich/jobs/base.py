"""Base classes and loaders for enrichment job specifications."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

JOBS_DIR = Path(__file__).resolve().parent


@dataclass
class JobDefinition:
    field: str
    title: str
    description_en: str
    description_nl: str
    output_schema: Dict[str, Any]
    plausibility: Dict[str, Any]
    confidence_rules: Dict[str, str]
    refresh_interval_days: int
    raw: Dict[str, Any]

    @classmethod
    def load(cls, job_name: str) -> "JobDefinition":
        clean_name = job_name.replace(".yaml", "").replace(".yml", "")
        file_path = JOBS_DIR / f"{clean_name}.yaml"
        if not file_path.exists():
            raise FileNotFoundError(f"Job definition '{job_name}' not found at {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            field=data.get("field", clean_name),
            title=data.get("title", clean_name),
            description_en=data.get("description_en", ""),
            description_nl=data.get("description_nl", ""),
            output_schema=data.get("output_schema", {}),
            plausibility=data.get("plausibility", {}),
            confidence_rules=data.get("confidence_rules", {}),
            refresh_interval_days=int(data.get("refresh_interval_days", 540)),
            raw=data,
        )


def list_available_jobs() -> List[str]:
    return [p.stem for p in JOBS_DIR.glob("*.yaml")]
