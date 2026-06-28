"""Download or stage enrichment datasets used by the pipeline.

This script supports two modes:
1. Download mode: provide URLs for prepared enrichment files.
2. Staging mode: provide local file paths and copy into data/enrichment
   using canonical parquet filenames.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import requests


REPO_ROOT = Path(__file__).resolve().parent.parent
ENRICHMENT_DIR = REPO_ROOT / "data" / "enrichment"
IMD_FILENAME = "imd_2025.parquet"
ONSPD_FILENAME = "onspd_postcode_lookup.parquet"


def _looks_like_html(path: Path) -> bool:
    head = path.read_text(encoding="utf-8", errors="ignore")[:4096].lower().lstrip()
    html_markers = ("<!doctype html", "<html", "<head", "<body")
    return any(marker in head for marker in html_markers)


def _download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)

    if "html" in content_type or _looks_like_html(destination):
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"Downloaded content from {url} looks like HTML, not a data file. "
            "Use a direct data file URL or stage local files instead."
        )


def _copy_file(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Local enrichment file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _resolve_target_paths() -> tuple[Path, Path]:
    return ENRICHMENT_DIR / IMD_FILENAME, ENRICHMENT_DIR / ONSPD_FILENAME


def main() -> int:
    parser = argparse.ArgumentParser(description="Download or stage enrichment data")
    parser.add_argument(
        "--imd-url",
        default=None,
        help="Direct URL to prepared IMD dataset (prefer parquet)",
    )
    parser.add_argument(
        "--onspd-url",
        default=None,
        help="Direct URL to prepared ONSPD dataset (prefer parquet)",
    )
    parser.add_argument(
        "--imd-local",
        default=None,
        help="Local path to prepared IMD dataset (prefer parquet)",
    )
    parser.add_argument(
        "--onspd-local",
        default=None,
        help="Local path to prepared ONSPD dataset (prefer parquet)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing enrichment files if present",
    )
    args = parser.parse_args()

    imd_target, onspd_target = _resolve_target_paths()

    if not args.force and (imd_target.exists() or onspd_target.exists()):
        print("Enrichment targets already exist. Use --force to overwrite.")
        print(f"- {imd_target}")
        print(f"- {onspd_target}")
        return 0

    if args.imd_local and args.onspd_local:
        _copy_file(Path(args.imd_local), imd_target)
        _copy_file(Path(args.onspd_local), onspd_target)
        print("Staged local enrichment files:")
        print(f"- {imd_target}")
        print(f"- {onspd_target}")
        return 0

    if args.imd_url and args.onspd_url:
        _download_file(args.imd_url, imd_target)
        _download_file(args.onspd_url, onspd_target)
        print("Downloaded enrichment files:")
        print(f"- {imd_target}")
        print(f"- {onspd_target}")
        return 0

    print("Provide either both --imd-local/--onspd-local or both --imd-url/--onspd-url.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
