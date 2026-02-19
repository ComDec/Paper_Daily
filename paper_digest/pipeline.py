from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from paper_digest.config import Config
from paper_digest.llm.openrouter import LLMError, OpenRouterClient
from paper_digest.models import Paper
from paper_digest.site import generate_daily_html, generate_site_indexes, update_reports
from paper_digest.sources.arxiv import fetch_arxiv_for_category
from paper_digest.sources.biorxiv import fetch_biorxiv
from paper_digest.sources.chemrxiv import fetch_chemrxiv


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _keyword_match(text: str, terms: list[str]) -> bool:
    t = _norm_text(text)
    for term in terms:
        if not term:
            continue
        if _norm_text(term) in t:
            return True
    return False


def _dedupe(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        key = p.uid or p.url or _norm_text(p.title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _keyword_prefilter(cfg: Config, papers: list[Paper]) -> list[Paper]:
    kp = cfg.filter.keyword_prefilter
    if not kp.enabled:
        return papers

    include = [t.strip() for t in kp.include if t and t.strip()]
    exclude = [t.strip() for t in kp.exclude if t and t.strip()]
    if not include and not exclude:
        return papers

    out: list[Paper] = []
    for p in papers:
        text = f"{p.title}\n{p.abstract}"
        if exclude and _keyword_match(text, exclude):
            continue
        if include and not _keyword_match(text, include):
            continue
        out.append(p)
    return out


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "..."


def _batch(iterable: list[Paper], size: int) -> list[list[Paper]]:
    if size <= 0:
        return [iterable]
    return [iterable[i : i + size] for i in range(0, len(iterable), size)]


def _llm_filter(
    cfg: Config, client: OpenRouterClient, papers: list[Paper]
) -> list[Paper]:
    if not papers:
        return []

    interests = "; ".join(cfg.filter.interests)
    kept: list[Paper] = []

    for chunk in _batch(papers, cfg.filter.llm_batch_size):
        items = []
        for p in chunk:
            items.append(
                {
                    "id": p.uid,
                    "title": p.title,
                    "abstract": _truncate(p.abstract, cfg.filter.max_abstract_chars),
                }
            )

        prompt = (
            "Interests: "
            + interests
            + "\n\n"
            + "For each item, output a JSON object mapping id -> 1 or 0. "
            + "Use 1 only if the paper is primarily about any interest. Output JSON only.\n\n"
            + json.dumps(items, ensure_ascii=True)
        )

        resp = client.chat_json(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
        )

        for p in chunk:
            v = resp.get(p.uid)
            if v in (1, "1", True, "true", "True"):
                kept.append(p)

    return kept


def _llm_rate(
    cfg: Config, client: OpenRouterClient, papers: list[Paper]
) -> list[dict[str, Any]]:
    if not cfg.rating.enabled:
        return [p.to_jsonable() for p in papers]

    interests = "; ".join(cfg.filter.interests)
    rated: list[dict[str, Any]] = []

    for i, p in enumerate(papers[: cfg.rating.max_papers]):
        prompt = (
            "Interests: "
            + interests
            + "\n\n"
            + "Return JSON only, English only, using this schema:\n"
            + "{"
            + '"tldr":"",'
            + '"relevance_score":0,'
            + '"novelty_claim_score":0,'
            + '"clarity_score":0,'
            + '"potential_impact_score":0,'
            + '"overall_priority_score":0'
            + "}\n"
            + "Constraints: scores are integers 1-10; TLDR is <= 240 characters.\n\n"
            + f"Title: {p.title}\n"
            + f"Abstract: {_truncate(p.abstract, cfg.rating.max_abstract_chars)}\n"
        )

        try:
            resp = client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=cfg.rating.max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            logging.warning("Rating failed for %s: %s", p.uid, e)
            resp = {}

        d = p.to_jsonable()
        d.update(
            {
                "tldr": resp.get("tldr"),
                "relevance_score": resp.get("relevance_score"),
                "novelty_claim_score": resp.get("novelty_claim_score"),
                "clarity_score": resp.get("clarity_score"),
                "potential_impact_score": resp.get("potential_impact_score"),
                "overall_priority_score": resp.get("overall_priority_score"),
            }
        )
        rated.append(d)
        logging.info(
            "Rated %d/%d: %s", i + 1, min(len(papers), cfg.rating.max_papers), p.uid
        )

    for p in papers[cfg.rating.max_papers :]:
        rated.append(p.to_jsonable())

    return rated


def _sort_papers(papers: list[dict[str, Any]]) -> None:
    papers.sort(key=lambda x: (x.get("overall_priority_score") or 0), reverse=True)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_source(url: str) -> str | None:
    u = (url or "").lower()
    if "arxiv.org" in u:
        return "arxiv"
    if "biorxiv.org" in u:
        return "biorxiv"
    if "medrxiv.org" in u:
        return "biorxiv"
    if "chemrxiv" in u:
        return "chemrxiv"
    if u.startswith("https://doi.org/"):
        return "doi"
    return None


def _normalize_loaded_papers(data: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(data, list):
        return ([], False)

    changed = False
    out: list[dict[str, Any]] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        d = dict(it)

        if "abstract" not in d and "summary" in d:
            d["abstract"] = d.get("summary")
            changed = True

        if "published" not in d and "published_date" in d:
            d["published"] = d.get("published_date")
            changed = True

        if "updated" not in d and "updated_date" in d:
            d["updated"] = d.get("updated_date")
            changed = True

        if "tldr_zh" in d:
            d.pop("tldr_zh", None)
            changed = True

        if "source" not in d:
            src = _infer_source(str(d.get("url") or ""))
            if src:
                d["source"] = src
                changed = True

        out.append(d)

    return (out, changed)


def _flatten_tiers(tiers: list[list[str]], *, max_tiers: int) -> list[str]:
    out: list[str] = []
    for tier_i, tier in enumerate(tiers):
        if tier_i >= max_tiers:
            break
        out.extend([c for c in tier if c])
    return out


def _fetch_all_sources(cfg: Config, target_date: date) -> list[Paper]:
    papers: list[Paper] = []

    if cfg.sources.arxiv.enabled:
        categories = _flatten_tiers(
            cfg.sources.arxiv.category_tiers,
            max_tiers=max(
                1,
                cfg.sources.adaptive_scope.max_tiers
                if cfg.sources.adaptive_scope.enabled
                else 999,
            ),
        )
        if not categories:
            categories = ["cs.CV"]

        fetched: list[Paper] = []
        for cat in categories:
            fetched.extend(
                fetch_arxiv_for_category(
                    category=cat, target_date=target_date, cfg=cfg.sources.arxiv
                )
            )
            fetched = _dedupe(fetched)

            if cfg.sources.adaptive_scope.enabled:
                candidates = _keyword_prefilter(cfg, fetched)
                if (
                    len(candidates)
                    >= cfg.sources.adaptive_scope.min_candidates_after_keyword_prefilter
                ):
                    break

        papers.extend(fetched)

    if cfg.sources.biorxiv.enabled:
        papers.extend(fetch_biorxiv(target_date=target_date, cfg=cfg.sources.biorxiv))

    if cfg.sources.chemrxiv.enabled:
        papers.extend(fetch_chemrxiv(target_date=target_date, cfg=cfg.sources.chemrxiv))

    return _dedupe(papers)


def run_pipeline(
    cfg: Config, *, target_date: date, days_back: int, force: bool
) -> None:
    client: OpenRouterClient | None
    try:
        client = OpenRouterClient(cfg.llm)
    except LLMError as e:
        logging.warning("LLM disabled: %s", e)
        client = None

    for delta in range(days_back, -1, -1):
        d = target_date - timedelta(days=delta)

        json_path = cfg.output.json_dir / f"{d.isoformat()}.json"
        if json_path.exists() and not force:
            logging.info("JSON exists, skipping compute: %s", json_path)
            loaded = _load_json(json_path)
            papers_json, changed = _normalize_loaded_papers(loaded)
            if changed:
                _write_json(json_path, papers_json)
        else:
            logging.info("Processing date: %s", d.isoformat())
            raw = _fetch_all_sources(cfg, d)
            logging.info("Fetched %d unique papers", len(raw))

            pre = _keyword_prefilter(cfg, raw)
            logging.info("Keyword prefilter: %d -> %d", len(raw), len(pre))

            if client is None:
                rel = pre
                logging.info("LLM relevance filter skipped")
                rated = [p.to_jsonable() for p in rel]
            else:
                rel = _llm_filter(cfg, client, pre)
                logging.info("LLM relevance filter: %d -> %d", len(pre), len(rel))
                rated = _llm_rate(cfg, client, rel)
            _sort_papers(rated)
            _write_json(json_path, rated)
            papers_json = rated

        html_path = generate_daily_html(
            papers=papers_json, report_date=d, output=cfg.output
        )
        logging.info("Wrote HTML: %s", html_path)

        reports = update_reports(
            report_date=d, paper_count=len(papers_json), output=cfg.output
        )
        generate_site_indexes(reports=reports, output=cfg.output)
        logging.info("Updated site index pages")
