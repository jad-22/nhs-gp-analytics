from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace

import pipeline.monthly as monthly


class _FakeDate(date):
    frozen_today = date(2026, 8, 20)

    @classmethod
    def today(cls) -> "_FakeDate":
        return cls(
            cls.frozen_today.year,
            cls.frozen_today.month,
            cls.frozen_today.day,
        )


def _run_main_and_capture_target(monkeypatch, *, today: date) -> monthly.MonthTarget:
    captured_target: monthly.MonthTarget | None = None
    _FakeDate.frozen_today = today

    def fake_run_target(target: monthly.MonthTarget, dry_run: bool = False, keep_raw: bool = False):
        nonlocal captured_target
        captured_target = target
        return SimpleNamespace(
            run_at="2026-01-01T00:00:00Z",
            month=target.month,
            year=target.year,
            status="success",
            totals_url=None,
            mapping_url=None,
            practices_ingested=None,
            error=None,
        )

    monkeypatch.setattr(monthly, "date", _FakeDate)
    monkeypatch.setattr(monthly, "run_target", fake_run_target)
    monkeypatch.setattr(monthly, "append_pipeline_log", lambda _record: None)
    monkeypatch.setattr(sys, "argv", ["pipeline.monthly"])

    assert monthly.main() == 0
    assert captured_target is not None
    return captured_target


def test_main_defaults_to_previous_month(monkeypatch) -> None:
    target = _run_main_and_capture_target(monkeypatch, today=date(2026, 8, 20))
    assert target.month == "july"
    assert target.year == 2026


def test_main_defaults_to_previous_month_across_year_boundary(monkeypatch) -> None:
    target = _run_main_and_capture_target(monkeypatch, today=date(2026, 1, 10))
    assert target.month == "december"
    assert target.year == 2025
