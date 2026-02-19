from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests

from paper_digest.config import BiorxivConfig
from paper_digest.models import Paper


def _authors_list(authors: str) -> list[str]:
    parts = [p.strip() for p in (authors or "").split(";")]
    return [p for p in parts if p]


def _pdf_url(doi: str, version: str) -> str:
    return f"https://www.biorxiv.org/content/{doi}v{version}.full.pdf"


def _landing_url(doi: str, version: str) -> str:
    return f"https://www.biorxiv.org/content/{doi}v{version}"


def _fetch_endpoint(server: str, from_date: str, to_date: str, cursor: int) -> str:
    return f"https://api.biorxiv.org/details/{server}/{from_date}/{to_date}/{cursor}"


def fetch_biorxiv(*, target_date: date, cfg: BiorxivConfig) -> list[Paper]:
    server = cfg.server.lower().strip()
    if server not in {"biorxiv", "medrxiv"}:
        raise ValueError(f"Unsupported bioRxiv server: {cfg.server}")

    from_date = target_date.isoformat()
    to_date = target_date.isoformat()

    categories = cfg.categories or [None]
    all_papers: list[Paper] = []

    for cat in categories:
        cursor = 0
        while True:
            url = _fetch_endpoint(server, from_date, to_date, cursor)
            params = {}
            if cat:
                params["category"] = cat
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            items: list[dict[str, Any]] = data.get("collection") or []
            if not items:
                break

            for it in items:
                doi = str(it.get("doi") or "").strip()
                if not doi:
                    continue
                version = str(it.get("version") or "").strip() or "1"
                title = str(it.get("title") or "").strip()
                abstract = str(it.get("abstract") or "").strip()
                authors = _authors_list(str(it.get("authors") or ""))

                published = None
                date_str = str(it.get("date") or "").strip()
                if date_str:
                    try:
                        published = datetime.strptime(date_str, "%Y-%m-%d")
                    except ValueError:
                        published = None

                all_papers.append(
                    Paper(
                        uid=f"doi:{doi}",
                        source="biorxiv",
                        title=title,
                        abstract=abstract,
                        url=_landing_url(doi, version),
                        pdf_url=_pdf_url(doi, version),
                        authors=authors,
                        categories=[str(it.get("category") or "").strip()]
                        if it.get("category")
                        else [],
                        published=published,
                        updated=None,
                        extra={
                            "doi": doi,
                            "version": version,
                            "server": server,
                            "type": it.get("type"),
                            "license": it.get("license"),
                        },
                    )
                )

            cursor += len(items)

    logging.info("bioRxiv fetched %d items", len(all_papers))
    return all_papers
