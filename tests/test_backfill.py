from unittest.mock import MagicMock

import requests

from pipeline.backfill import MonthTarget, run_target


def test_run_target_returns_failed_result_on_persistent_http_error(monkeypatch) -> None:
    # Regression test: requests.exceptions.HTTPError used to escape run_target's
    # except clause entirely (it only caught RuntimeError/ValueError/friends),
    # crashing main() with a raw traceback before pipeline_log.json was ever
    # written. A transient block from NHS Digital's edge should degrade to a
    # clean "failed" RunResult like any other pipeline error.
    monkeypatch.setattr(
        "pipeline.backfill.fetch_html",
        MagicMock(side_effect=requests.exceptions.HTTPError("403 Client Error: Forbidden")),
    )

    result = run_target(MonthTarget(month="july", year=2026))

    assert result.status == "failed"
    assert "403" in result.error
