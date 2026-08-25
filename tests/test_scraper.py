from requests import HTTPError

from pipeline.scraper import (
    DEFAULT_USER_AGENT,
    fetch_html,
    find_target_links,
    make_session,
    publication_url,
    resolve_files_host_url,
)


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


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"status={self.status_code}")


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.headers = {"User-Agent": "custom-agent/1.0"}
        self.calls: list[str] = []
        self._responses = responses or [_FakeResponse(status_code=403), _FakeResponse(status_code=200, text="<html>ok</html>")]

    def get(self, _url: str, timeout: int = 30) -> _FakeResponse:  # noqa: ARG002
        self.calls.append(self.headers.get("User-Agent", ""))
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


def test_make_session_uses_browser_user_agent_by_default() -> None:
    session = make_session()
    assert session.headers["User-Agent"] == DEFAULT_USER_AGENT


def test_fetch_html_retries_forbidden_with_default_user_agent() -> None:
    session = _FakeSession()
    html = fetch_html(session, "https://example.com")
    assert html == "<html>ok</html>"
    assert session.calls == ["custom-agent/1.0", DEFAULT_USER_AGENT]
    assert session.headers["User-Agent"] == "custom-agent/1.0"


def test_fetch_html_raises_for_persistent_forbidden() -> None:
    session = _FakeSession(responses=[_FakeResponse(status_code=403), _FakeResponse(status_code=403)])
    try:
        fetch_html(session, "https://example.com")
        assert False, "Expected HTTPError for persistent 403"
    except HTTPError:
        pass
    assert session.calls == ["custom-agent/1.0", DEFAULT_USER_AGENT]
    assert session.headers["User-Agent"] == "custom-agent/1.0"
