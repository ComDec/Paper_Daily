from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import arxiv

from paper_digest.config import ArxivConfig
from paper_digest.models import Paper


def _fmt_submitted(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def _quote_term(term: str) -> str:
    t = term.replace('"', '\\"').strip()
    if not t:
        return ""
    if any(ch.isspace() for ch in t) or any(ch in t for ch in [":", "-", "/"]):
        return f'all:"{t}"'
    return f"all:{t}"


def build_arxiv_query(*, category: str, target_date: date, cfg: ArxivConfig) -> str:
    end_utc = datetime.combine(target_date, time.min, tzinfo=timezone.utc) + timedelta(
        hours=cfg.submitted_date_offset_hours
    )
    start_utc = end_utc - timedelta(days=1)

    submitted = (
        f"submittedDate:[{_fmt_submitted(start_utc)} TO {_fmt_submitted(end_utc)}]"
    )
    cat = f"cat:{category}"

    terms = [
        _quote_term(t) for t in cfg.query_terms if isinstance(t, str) and t.strip()
    ]
    if terms:
        return f"{cat} AND {submitted} AND (" + " OR ".join(terms) + ")"
    return f"{cat} AND {submitted}"


def fetch_arxiv_for_category(
    *, category: str, target_date: date, cfg: ArxivConfig
) -> list[Paper]:
    query = build_arxiv_query(category=category, target_date=target_date, cfg=cfg)
    logging.info("arXiv query: %s", query)

    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=cfg.max_results_per_category,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )

    papers: list[Paper] = []
    try:
        for r in client.results(search):
            uid = f"arxiv:{r.get_short_id()}"
            url = str(r.entry_id)
            pdf_url = None
            try:
                pdf_url = str(r.pdf_url)
            except Exception:  # noqa: BLE001
                pdf_url = None

            papers.append(
                Paper(
                    uid=uid,
                    source="arxiv",
                    title=str(r.title).strip(),
                    abstract=str(r.summary).strip(),
                    url=url,
                    pdf_url=pdf_url,
                    authors=[a.name for a in r.authors],
                    categories=list(r.categories or []),
                    published=r.published,
                    updated=r.updated,
                    extra={"primary_category": getattr(r, "primary_category", None)},
                )
            )
    except arxiv.arxiv.UnexpectedEmptyPageError as e:
        logging.warning("arXiv empty page: %s", e)
    except arxiv.arxiv.HTTPError as e:
        logging.error("arXiv HTTP error: %s", e)
    except Exception as e:  # noqa: BLE001
        logging.error("arXiv unexpected error: %s", e, exc_info=True)

    return papers
