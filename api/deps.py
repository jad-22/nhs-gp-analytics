"""Shared request-level helpers: pagination, licence metadata, structured errors."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Query

from api import db
from api.config import (
    API_PREFIX,
    ATTRIBUTION,
    DEFAULT_PAGE_SIZE,
    LICENCE_NAME,
    LICENCE_URL,
    MAX_PAGE_SIZE,
)


@dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def envelope(self, total: int) -> dict:
        pages = max(1, -(-total // self.page_size))  # ceiling division
        return {"page": self.page, "page_size": self.page_size, "total": total, "pages": pages}


def pagination(
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Results per page (max {MAX_PAGE_SIZE}).",
    ),
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


def source_meta() -> dict:
    """The licence and vintage block attached to every successful response."""

    return {
        "source": ATTRIBUTION,
        "licence": LICENCE_NAME,
        "licence_url": LICENCE_URL,
        "caveats_url": f"{API_PREFIX}/meta",
        "run_id": db.run_id(),
    }


def not_found(detail: str, code: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail, headers={"X-Error-Code": code})
