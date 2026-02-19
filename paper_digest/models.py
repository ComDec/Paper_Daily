from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


def _dt_to_iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


@dataclass(slots=True)
class Paper:
    uid: str
    source: str
    title: str
    abstract: str
    url: str
    pdf_url: str | None = None
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    published: datetime | None = None
    updated: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        d["published"] = _dt_to_iso(self.published)
        d["updated"] = _dt_to_iso(self.updated)
        return d
