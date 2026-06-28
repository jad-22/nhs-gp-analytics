"""Shared paths, constants, and month mappings for the pipeline scaffold."""

from __future__ import annotations

from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_ENRICHMENT_DIR = DATA_DIR / "enrichment"
PIPELINE_LOG_PATH = DATA_DIR / "pipeline_log.json"
LIST_SIZE_PARQUET_PATH = DATA_PROCESSED_DIR / "list_size.parquet"
MAPPING_PARQUET_PATH = DATA_PROCESSED_DIR / "mapping.parquet"

PUBLICATION_PAGE_TEMPLATE = (
    "https://digital.nhs.uk/data-and-information/publications/statistical/"
    "patients-registered-at-a-gp-practice/{slug}"
)
FILES_HOST = "https://files.digital.nhs.uk/"
TOTALS_STEM = "gp-reg-pat-prac-all"
MAPPING_STEM = "gp-reg-pat-prac-map"

PDS_START = date(2023, 1, 1)
DEFAULT_BACKFILL_START = date(2015, 1, 1)

MONTHS: dict[str, str] = {
    "1": "january",
    "01": "january",
    "jan": "january",
    "january": "january",
    "2": "february",
    "02": "february",
    "feb": "february",
    "february": "february",
    "3": "march",
    "03": "march",
    "mar": "march",
    "march": "march",
    "4": "april",
    "04": "april",
    "apr": "april",
    "april": "april",
    "5": "may",
    "05": "may",
    "may": "may",
    "6": "june",
    "06": "june",
    "jun": "june",
    "june": "june",
    "7": "july",
    "07": "july",
    "jul": "july",
    "july": "july",
    "8": "august",
    "08": "august",
    "aug": "august",
    "august": "august",
    "9": "september",
    "09": "september",
    "sep": "september",
    "sept": "september",
    "september": "september",
    "10": "october",
    "oct": "october",
    "october": "october",
    "11": "november",
    "nov": "november",
    "november": "november",
    "12": "december",
    "dec": "december",
    "december": "december",
}

MONTH_TO_INT: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def ensure_data_directories() -> None:
    """Create the standard data directories if they do not exist."""

    for directory in (DATA_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR, DATA_ENRICHMENT_DIR):
        directory.mkdir(parents=True, exist_ok=True)