"""Utility helpers shared across the pipeline scaffold."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .config import MONTHS, PIPELINE_LOG_PATH, PUBLICATION_PAGE_TEMPLATE, ensure_data_directories


def normalize_month(month: str) -> str:
    """Normalize month aliases to a lowercase month name."""

    value = month.strip().lower()
    if value not in MONTHS:
        raise ValueError(f"Unrecognized month '{month}'. Use a month name or number.")
    return MONTHS[value]


def build_page_url(month: str, year: int) -> str:
    """Build the NHS Digital publication page URL for a month/year pair."""

    slug = f"{normalize_month(month)}-{int(year)}"
    return PUBLICATION_PAGE_TEMPLATE.format(slug=slug)


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def setup_logging(name: str) -> logging.Logger:
    """Create a basic stdout logger for local development."""

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def append_pipeline_log(record: dict) -> None:
    """Append a pipeline run record to the JSON log."""

    ensure_data_directories()
    records: list[dict] = []
    if PIPELINE_LOG_PATH.exists():
        try:
            records = json.loads(PIPELINE_LOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            records = []
    records.append(record)
    PIPELINE_LOG_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def resolve_repo_path(*parts: str) -> Path:
    """Resolve a path relative to the repository root."""

    from .config import REPO_ROOT

    return REPO_ROOT.joinpath(*parts)