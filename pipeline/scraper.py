"""NHS Digital publication-page scraping and download helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .config import FILES_HOST, MAPPING_STEM, TOTALS_STEM
from .utils import build_page_url


LEGACY_TOTALS_STEMS = ("gp_practice_counts",)
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"


@dataclass(frozen=True)
class TargetLink:
    """Resolved download link for one dataset."""

    name: str
    href: str


class PageNotFoundError(RuntimeError):
    """Raised when the monthly publication page does not exist yet."""


class LinksNotFoundError(RuntimeError):
    """Raised when expected dataset links are absent from a publication page."""


class DownloadError(RuntimeError):
    """Raised when a file download fails after retries."""


def publication_url(month: str, year: int) -> str:
    """Return the NHS publication page URL for a month/year pair."""

    return build_page_url(month, year)


def make_session(user_agent: str | None = None) -> requests.Session:
    """Create an HTTP session with a deterministic user agent."""

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent
            or DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    return session


def fetch_html(session: requests.Session, url: str, timeout: int = 30) -> str:
    """Fetch page HTML, converting 404s into a typed pipeline error."""

    response = session.get(url, timeout=timeout)
    if response.status_code == 404:
        raise PageNotFoundError(f"Publication page not found: {url}")
    if response.status_code == 403:
        original_user_agent = session.headers.get("User-Agent")
        if original_user_agent != DEFAULT_USER_AGENT:
            session.headers["User-Agent"] = DEFAULT_USER_AGENT
            try:
                response = session.get(url, timeout=timeout)
                if response.status_code == 404:
                    raise PageNotFoundError(f"Publication page not found: {url}")
            finally:
                if original_user_agent is None:
                    session.headers.pop("User-Agent", None)
                else:
                    session.headers["User-Agent"] = original_user_agent
    response.raise_for_status()
    return response.text


def find_target_links(html: str) -> dict[str, TargetLink]:
    """Resolve totals and mapping links from publication page HTML."""

    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    found: dict[str, TargetLink] = {}

    for anchor in anchors:
        href = anchor["href"].strip()
        href_lower = href.lower()

        if TOTALS_STEM in href_lower and (href_lower.endswith(".zip") or href_lower.endswith(".csv")):
            found["totals"] = TargetLink(name="totals", href=resolve_files_host_url(href))
        if MAPPING_STEM in href_lower and (href_lower.endswith(".zip") or href_lower.endswith(".csv")):
            found["mapping"] = TargetLink(name="mapping", href=resolve_files_host_url(href))

        if "totals" not in found:
            for legacy_stem in LEGACY_TOTALS_STEMS:
                if legacy_stem in href_lower and (href_lower.endswith(".zip") or href_lower.endswith(".csv")):
                    found["totals"] = TargetLink(name="totals", href=resolve_files_host_url(href))
                    break

    if "totals" not in found or "mapping" not in found:
        for anchor in anchors:
            href = resolve_files_host_url(anchor["href"].strip())
            href_lower = href.lower()
            text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
            is_data_file = href_lower.endswith(".zip") or href_lower.endswith(".csv")

            if "totals" not in found and is_data_file and ("totals" in text or "list size" in text):
                found["totals"] = TargetLink(name="totals", href=href)
            if "mapping" not in found and is_data_file and "mapping" in text:
                found["mapping"] = TargetLink(name="mapping", href=href)

    missing = [name for name in ("totals", "mapping") if name not in found]
    if missing == ["mapping"] and "totals" in found:
        # Transitional historical publications sometimes expose only one practice-level file.
        found["mapping"] = TargetLink(name="mapping", href=found["totals"].href)
        missing = []

    if missing:
        raise LinksNotFoundError(f"Could not resolve expected link(s): {', '.join(missing)}")
    return found


def resolve_files_host_url(path: str) -> str:
    """Normalise a relative files.digital.nhs.uk path to an absolute URL."""

    if path.startswith("http://") or path.startswith("https://"):
        return path
    return FILES_HOST.rstrip("/") + "/" + path.lstrip("/")


def filename_from_url(url: str) -> str:
    """Extract a safe filename from a download URL."""

    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or "download.bin"


def download_file(
    session: requests.Session,
    url: str,
    destination: Path,
    timeout: int = 60,
    retries: int = 3,
    backoff_seconds: float = 1.5,
) -> None:
    """Download a file with retries and streaming writes."""

    destination.parent.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            handle.write(chunk)
            return
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= retries:
                break
            delay = backoff_seconds ** attempt
            import time

            time.sleep(delay)

    raise DownloadError(f"Failed to download {url}: {last_error}")


__all__ = [
    "DownloadError",
    "LinksNotFoundError",
    "PageNotFoundError",
    "TargetLink",
    "download_file",
    "fetch_html",
    "filename_from_url",
    "find_target_links",
    "make_session",
    "publication_url",
    "resolve_files_host_url",
]