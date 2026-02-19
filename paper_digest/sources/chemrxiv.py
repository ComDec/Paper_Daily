from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests

from paper_digest.config import ChemrxivConfig
from paper_digest.models import Paper


def _openalex_work_url(base_url: str, doi: str) -> str:
    doi_url = f"https://doi.org/{doi}"
    return f"{base_url.rstrip('/')}/works/{doi_url}"


def _reconstruct_abstract(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    pos_to_word: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            pos_to_word[int(p)] = str(word)
    if not pos_to_word:
        return ""
    words = [pos_to_word[i] for i in sorted(pos_to_word.keys())]
    return " ".join(words).strip()


def _crossref_query_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/works"


def fetch_chemrxiv(*, target_date: date, cfg: ChemrxivConfig) -> list[Paper]:
    from_date = target_date.isoformat()
    to_date = target_date.isoformat()

    params = {
        "filter": f"from-pub-date:{from_date},until-pub-date:{to_date},prefix:{cfg.doi_prefix}",
        "rows": str(cfg.crossref_rows),
    }
    headers = {
        "User-Agent": "paper-digest/0.1 (mailto:example@example.com)",
    }

    resp = requests.get(
        _crossref_query_url(cfg.crossref_base_url),
        params=params,
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    items: list[dict[str, Any]] = data.get("message", {}).get("items", []) or []

    papers: list[Paper] = []
    for it in items:
        doi = str(it.get("DOI") or "").strip().lower()
        if not doi:
            continue

        oa_resp = requests.get(
            _openalex_work_url(cfg.openalex_base_url, doi), timeout=60
        )
        if oa_resp.status_code != 200:
            logging.warning(
                "OpenAlex lookup failed for DOI %s: HTTP %s", doi, oa_resp.status_code
            )
            continue
        oa: dict[str, Any] = oa_resp.json()

        title = (
            str(oa.get("title") or "").strip()
            or str((it.get("title") or [""])[0]).strip()
        )
        abstract = _reconstruct_abstract(oa.get("abstract_inverted_index"))

        authors = []
        for a in oa.get("authorships", []) or []:
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(str(name))

        published = None
        pub_date = str(oa.get("publication_date") or "").strip()
        if pub_date:
            try:
                published = datetime.strptime(pub_date, "%Y-%m-%d")
            except ValueError:
                published = None

        papers.append(
            Paper(
                uid=f"doi:{doi}",
                source="chemrxiv",
                title=title,
                abstract=abstract,
                url=f"https://doi.org/{doi}",
                pdf_url=None,
                authors=authors,
                categories=[],
                published=published,
                updated=None,
                extra={"doi": doi},
            )
        )

    logging.info("ChemRxiv fetched %d items", len(papers))
    return papers
