from pipeline.scraper import find_target_links, publication_url, resolve_files_host_url


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
