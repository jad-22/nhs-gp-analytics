"""Dataset extraction helpers for the pipeline scaffold."""

from __future__ import annotations

import zipfile
from pathlib import Path


class ExtractionError(RuntimeError):
    """Raised when archive extraction or file discovery fails."""


def safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    """Extract a zip file with Zip Slip protection."""

    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (extract_dir / member.filename).resolve()
            if not str(destination).startswith(str(extract_root)):
                raise ExtractionError(f"Unsafe path in zip archive: {member.filename}")
        archive.extractall(extract_dir)


def find_extracted_dataset(extract_dir: Path, stem_prefix: str) -> Path:
    """Find the first extracted dataset file that matches the expected stem."""

    if not extract_dir.exists():
        raise ExtractionError(f"Extract directory does not exist: {extract_dir}")

    candidates: list[Path] = []
    for extension in ("xlsx", "xls", "csv"):
        candidates.extend(extract_dir.rglob(f"{stem_prefix}.{extension}"))
        candidates.extend(extract_dir.rglob(f"{stem_prefix}*.{extension}"))

    if not candidates:
        raise ExtractionError(
            f"Could not find a dataset starting with '{stem_prefix}' in {extract_dir}"
        )

    def score(path: Path) -> tuple[int, str]:
        priority = {".xlsx": 0, ".xls": 1, ".csv": 2}.get(path.suffix.lower(), 9)
        return priority, path.name

    return sorted({candidate for candidate in candidates}, key=score)[0]


__all__ = ["ExtractionError", "find_extracted_dataset", "safe_extract_zip"]