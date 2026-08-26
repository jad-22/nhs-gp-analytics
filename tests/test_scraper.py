from unittest.mock import MagicMock

import pytest
import requests

from pipeline.scraper import (
    PageNotFoundError,
    fetch_html,
    find_target_links,
    make_session,
    publication_url,
    resolve_files_host_url,
)


def _response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.raise_for_status.side_effect = (
        requests.exceptions.HTTPError(f"{status_code} error", response=response)
        if status_code >= 400
        else None
    )
    return response


def test_publication_url_builds_month_slug() -> None:
    url = publication_url("Jan", 2025)
    assert url.endswith("/patients-registered-at-a-gp-practice/january-2025")


def test_files_host_url_normalization() -> None:
    absolute = resolve_files_host_url("https://files.digital.nhs.uk/AA/BB/file.zip")
    relative = resolve_files_host_url("AA/BB/file.zip")
    assert absolute == "https://files.digital.nhs.uk/AA/BB/file.zip"
    assert relative == "https://files.digital.nhs.uk/AA/BB/file.zip"


def test_find_target_links_by_href() -> None:
        html = """
        <html>
            <body>
                <a href="/40/58F467/gp-reg-pat-prac-all.zip">Totals</a>
                <a href="/F5/3E6C88/gp-reg-pat-prac-map.zip">Mapping</a>
            </body>
        </html>
        """

        links = find_target_links(html)
        assert links["totals"].href.endswith("gp-reg-pat-prac-all.zip")
        assert links["mapping"].href.endswith("gp-reg-pat-prac-map.zip")


def test_find_target_links_legacy_counts_fallback() -> None:
        html = """
        <html>
            <body>
                <a href="https://files.digital.nhs.uk/publicationimport/pub16xxx/pub16357/gp_practice_counts.csv">Legacy counts</a>
            </body>
        </html>
        """
        links = find_target_links(html)
        assert links["totals"].href.endswith("gp_practice_counts.csv")
        assert links["mapping"].href.endswith("gp_practice_counts.csv")


def test_fetch_html_retries_transient_403_then_succeeds(monkeypatch) -> None:
    session = make_session()
    responses = [_response(403), _response(200, text="<html>ok</html>")]
    monkeypatch.setattr(session, "get", MagicMock(side_effect=responses))
    monkeypatch.setattr("pipeline.scraper.time.sleep", lambda _seconds: None)

    html = fetch_html(session, "https://digital.nhs.uk/some-page", retries=3, backoff_seconds=0.01)

    assert html == "<html>ok</html>"
    assert session.get.call_count == 2


def test_fetch_html_raises_after_exhausting_retries_on_403(monkeypatch) -> None:
    session = make_session()
    monkeypatch.setattr(session, "get", MagicMock(return_value=_response(403)))
    monkeypatch.setattr("pipeline.scraper.time.sleep", lambda _seconds: None)

    with pytest.raises(requests.exceptions.HTTPError):
        fetch_html(session, "https://digital.nhs.uk/some-page", retries=3, backoff_seconds=0.01)

    assert session.get.call_count == 3


def test_fetch_html_404_raises_immediately_without_retry(monkeypatch) -> None:
    session = make_session()
    monkeypatch.setattr(session, "get", MagicMock(return_value=_response(404)))

    with pytest.raises(PageNotFoundError):
        fetch_html(session, "https://digital.nhs.uk/some-page", retries=3, backoff_seconds=0.01)

    assert session.get.call_count == 1
