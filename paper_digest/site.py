from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from paper_digest.config import OutputConfig


@dataclass(frozen=True, slots=True)
class ReportItem:
    date: str
    html: str
    json: str
    paper_count: int


def _report_html_filename(d: date) -> str:
    return d.strftime("%Y_%m_%d.html")


def _report_json_filename(d: date) -> str:
    return f"{d.isoformat()}.json"


def generate_daily_html(
    *,
    papers: list[dict[str, Any]],
    report_date: date,
    output: OutputConfig,
) -> Path:
    env = Environment(loader=FileSystemLoader(str(output.templates_dir)))
    template = env.get_template(output.daily_template)

    generation_time = datetime.now(timezone.utc)
    title = f"{output.site_title} - {report_date.isoformat()}"

    html = template.render(
        papers=papers,
        title=title,
        report_date=report_date,
        generation_time=generation_time,
        site_title=output.site_title,
        site_subtitle=output.site_subtitle,
    )

    output.html_dir.mkdir(parents=True, exist_ok=True)
    out_path = output.html_dir / _report_html_filename(report_date)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def write_reports_json(*, reports: list[ReportItem], output: OutputConfig) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest": reports[0].html if reports else None,
        "reports": [
            {
                "date": r.date,
                "html": r.html,
                "json": r.json,
                "paper_count": r.paper_count,
            }
            for r in reports
        ],
    }
    output.reports_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
    )


def _load_existing_reports(output: OutputConfig) -> list[ReportItem]:
    if not output.reports_json.exists():
        return []

    try:
        raw = json.loads(output.reports_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    if isinstance(raw, list):
        items = []
        for html in raw:
            if not isinstance(html, str):
                continue
            date_str = html.replace(".html", "").replace("_", "-")
            items.append(
                ReportItem(
                    date=date_str, html=html, json=f"{date_str}.json", paper_count=0
                )
            )
        return items

    reports = []
    for it in raw.get("reports", []) or []:
        if not isinstance(it, dict):
            continue
        reports.append(
            ReportItem(
                date=str(it.get("date")),
                html=str(it.get("html")),
                json=str(it.get("json")),
                paper_count=int(it.get("paper_count") or 0),
            )
        )
    return reports


def update_reports(
    *,
    report_date: date,
    paper_count: int,
    output: OutputConfig,
) -> list[ReportItem]:
    existing = _load_existing_reports(output)
    date_str = report_date.isoformat()
    html = _report_html_filename(report_date)
    js = _report_json_filename(report_date)

    updated: list[ReportItem] = [r for r in existing if r.date != date_str]
    updated.append(
        ReportItem(date=date_str, html=html, json=js, paper_count=paper_count)
    )
    updated.sort(key=lambda r: r.date, reverse=True)

    write_reports_json(reports=updated, output=output)
    return updated


def generate_site_indexes(*, reports: list[ReportItem], output: OutputConfig) -> None:
    env = Environment(loader=FileSystemLoader(str(output.templates_dir)))

    index_tpl = env.get_template(output.index_template)
    list_tpl = env.get_template(output.list_template)

    latest = reports[0] if reports else None
    ctx = {
        "site_title": output.site_title,
        "site_subtitle": output.site_subtitle,
        "reports": [
            {
                "date": r.date,
                "html": r.html,
                "json": r.json,
                "paper_count": r.paper_count,
            }
            for r in reports
        ],
        "latest": (
            {
                "date": latest.date,
                "html": latest.html,
                "json": latest.json,
                "paper_count": latest.paper_count,
            }
            if latest
            else None
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    output.index_html.write_text(index_tpl.render(**ctx), encoding="utf-8")
    output.list_html.write_text(list_tpl.render(**ctx), encoding="utf-8")
