from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


def _require(d: dict[str, Any], key: str, *, path: str) -> Any:
    if key not in d:
        raise ConfigError(f"Missing required key: {path}.{key}")
    return d[key]


def _as_list(value: Any, *, path: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ConfigError(f"Expected list at {path}")


@dataclass(frozen=True, slots=True)
class RunConfig:
    days_back: int = 2


@dataclass(frozen=True, slots=True)
class OutputConfig:
    json_dir: Path
    html_dir: Path
    templates_dir: Path
    daily_template: str
    index_template: str
    list_template: str
    reports_json: Path
    index_html: Path
    list_html: Path
    retention_days: int = 365
    site_title: str = "Daily Preprint Digest"
    site_subtitle: str = ""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: str
    api_key_env: str
    base_url: str
    model: str
    temperature: float = 0.0
    timeout_s: int = 60
    max_retries: int = 2
    cache_dir: Path = Path(".cache/llm")


@dataclass(frozen=True, slots=True)
class KeywordPrefilterConfig:
    enabled: bool = True
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FilterConfig:
    interests: list[str]
    llm_batch_size: int = 15
    max_abstract_chars: int = 1600
    keyword_prefilter: KeywordPrefilterConfig = field(
        default_factory=KeywordPrefilterConfig
    )


@dataclass(frozen=True, slots=True)
class RatingConfig:
    enabled: bool = True
    max_papers: int = 80
    max_abstract_chars: int = 2000
    max_tokens: int = 320


@dataclass(frozen=True, slots=True)
class AdaptiveScopeConfig:
    enabled: bool = True
    min_candidates_after_keyword_prefilter: int = 120
    max_tiers: int = 3


@dataclass(frozen=True, slots=True)
class ArxivConfig:
    enabled: bool = True
    max_results_per_category: int = 300
    submitted_date_offset_hours: int = -6
    category_tiers: list[list[str]] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BiorxivConfig:
    enabled: bool = True
    server: str = "biorxiv"
    categories: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ChemrxivConfig:
    enabled: bool = True
    doi_prefix: str = "10.26434"
    crossref_rows: int = 1000
    openalex_base_url: str = "https://api.openalex.org"
    crossref_base_url: str = "https://api.crossref.org"


@dataclass(frozen=True, slots=True)
class SourcesConfig:
    arxiv: ArxivConfig
    biorxiv: BiorxivConfig
    chemrxiv: ChemrxivConfig
    adaptive_scope: AdaptiveScopeConfig = field(default_factory=AdaptiveScopeConfig)


@dataclass(frozen=True, slots=True)
class Config:
    run: RunConfig
    output: OutputConfig
    llm: LLMConfig
    filter: FilterConfig
    rating: RatingConfig
    sources: SourcesConfig


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("Config must be a YAML mapping")

    run_raw = raw.get("run", {})
    run = RunConfig(days_back=int(run_raw.get("days_back", 2)))

    output_raw = _require(raw, "output", path="config")
    output = OutputConfig(
        json_dir=Path(output_raw.get("json_dir", "daily_json")),
        html_dir=Path(output_raw.get("html_dir", "daily_html")),
        templates_dir=Path(output_raw.get("templates_dir", "templates")),
        daily_template=str(output_raw.get("daily_template", "paper_template.html")),
        index_template=str(output_raw.get("index_template", "index_template.html")),
        list_template=str(output_raw.get("list_template", "list_template.html")),
        reports_json=Path(output_raw.get("reports_json", "reports.json")),
        index_html=Path(output_raw.get("index_html", "index.html")),
        list_html=Path(output_raw.get("list_html", "list.html")),
        retention_days=int(output_raw.get("retention_days", 365)),
        site_title=str(output_raw.get("site_title", "Daily Preprint Digest")),
        site_subtitle=str(output_raw.get("site_subtitle", "")),
    )

    llm_raw = _require(raw, "llm", path="config")
    llm = LLMConfig(
        provider=str(llm_raw.get("provider", "openrouter")),
        api_key_env=str(llm_raw.get("api_key_env", "OPENROUTER_API_KEY")),
        base_url=str(
            llm_raw.get("base_url", "https://openrouter.ai/api/v1/chat/completions")
        ),
        model=str(_require(llm_raw, "model", path="config.llm")),
        temperature=float(llm_raw.get("temperature", 0.0)),
        timeout_s=int(llm_raw.get("timeout_s", 60)),
        max_retries=int(llm_raw.get("max_retries", 2)),
        cache_dir=Path(llm_raw.get("cache_dir", ".cache/llm")),
    )

    filter_raw = _require(raw, "filter", path="config")
    interests = [
        str(x)
        for x in _as_list(
            _require(filter_raw, "interests", path="config.filter"),
            path="config.filter.interests",
        )
    ]
    kp_raw = filter_raw.get("keyword_prefilter", {})
    keyword_prefilter = KeywordPrefilterConfig(
        enabled=bool(kp_raw.get("enabled", True)),
        include=[
            str(x)
            for x in _as_list(
                kp_raw.get("include", []),
                path="config.filter.keyword_prefilter.include",
            )
        ],
        exclude=[
            str(x)
            for x in _as_list(
                kp_raw.get("exclude", []),
                path="config.filter.keyword_prefilter.exclude",
            )
        ],
    )
    filt = FilterConfig(
        interests=interests,
        llm_batch_size=int(filter_raw.get("llm_batch_size", 15)),
        max_abstract_chars=int(filter_raw.get("max_abstract_chars", 1600)),
        keyword_prefilter=keyword_prefilter,
    )

    rating_raw = raw.get("rating", {})
    rating = RatingConfig(
        enabled=bool(rating_raw.get("enabled", True)),
        max_papers=int(rating_raw.get("max_papers", 80)),
        max_abstract_chars=int(rating_raw.get("max_abstract_chars", 2000)),
        max_tokens=int(rating_raw.get("max_tokens", 320)),
    )

    sources_raw = raw.get("sources", {})
    adaptive_raw = sources_raw.get("adaptive_scope", {})
    adaptive = AdaptiveScopeConfig(
        enabled=bool(adaptive_raw.get("enabled", True)),
        min_candidates_after_keyword_prefilter=int(
            adaptive_raw.get("min_candidates_after_keyword_prefilter", 120)
        ),
        max_tiers=int(adaptive_raw.get("max_tiers", 3)),
    )

    arxiv_raw = sources_raw.get("arxiv", {})
    arxiv = ArxivConfig(
        enabled=bool(arxiv_raw.get("enabled", True)),
        max_results_per_category=int(arxiv_raw.get("max_results_per_category", 300)),
        submitted_date_offset_hours=int(
            arxiv_raw.get("submitted_date_offset_hours", -6)
        ),
        category_tiers=[
            [str(y) for y in _as_list(x, path="config.sources.arxiv.category_tiers[]")]
            for x in _as_list(
                arxiv_raw.get("category_tiers", []),
                path="config.sources.arxiv.category_tiers",
            )
        ],
        query_terms=[
            str(x)
            for x in _as_list(
                arxiv_raw.get("query_terms", []),
                path="config.sources.arxiv.query_terms",
            )
        ],
    )

    biorxiv_raw = sources_raw.get("biorxiv", {})
    biorxiv = BiorxivConfig(
        enabled=bool(biorxiv_raw.get("enabled", True)),
        server=str(biorxiv_raw.get("server", "biorxiv")),
        categories=[
            str(x)
            for x in _as_list(
                biorxiv_raw.get("categories", []),
                path="config.sources.biorxiv.categories",
            )
        ],
    )

    chemrxiv_raw = sources_raw.get("chemrxiv", {})
    chemrxiv = ChemrxivConfig(
        enabled=bool(chemrxiv_raw.get("enabled", True)),
        doi_prefix=str(chemrxiv_raw.get("doi_prefix", "10.26434")),
        crossref_rows=int(chemrxiv_raw.get("crossref_rows", 1000)),
        openalex_base_url=str(
            chemrxiv_raw.get("openalex_base_url", "https://api.openalex.org")
        ),
        crossref_base_url=str(
            chemrxiv_raw.get("crossref_base_url", "https://api.crossref.org")
        ),
    )

    sources = SourcesConfig(
        arxiv=arxiv, biorxiv=biorxiv, chemrxiv=chemrxiv, adaptive_scope=adaptive
    )

    return Config(
        run=run, output=output, llm=llm, filter=filt, rating=rating, sources=sources
    )
