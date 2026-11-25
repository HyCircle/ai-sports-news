"""Static site, JSON API, and RSS 2.0 feed generator (Jinja2 + vanilla CSS/JS)."""

from __future__ import annotations

import html
import json
import re
import shutil
from collections import OrderedDict
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Settings
from .db import list_reports

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_WORD_RE = re.compile(r"[a-z0-9]{2,}")


def _extract_match_tokens(text: str) -> set[str]:
    """Extract lowercase ASCII tokens and CJK character bigrams for deterministic matching."""
    plain = _LINK_RE.sub(r"\1", text or "")
    plain = plain.replace("**", "").replace("*", "").lower()
    tokens: set[str] = set(_LATIN_WORD_RE.findall(plain))
    for run in _CJK_RUN_RE.findall(plain):
        if len(run) == 1:
            tokens.add(run)
        else:
            for i in range(len(run) - 1):
                tokens.add(run[i : i + 2])
    return tokens


def _match_overview_bullets(
    bullets: list[str],
    sections_view: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministically link each overview bullet to its best matching event anchor."""
    candidates: list[dict[str, Any]] = []
    for sec in sections_view:
        badge = sec.get("badge", "")
        for ev in sec.get("events", []):
            candidates.append(
                {
                    "anchor": ev["anchor"],
                    "badge": badge,
                    "importance": ev.get("importance", "medium"),
                    "title_tokens": _extract_match_tokens(ev.get("title", "")),
                    "body_tokens": _extract_match_tokens((ev.get("summary_md") or "")[:360]),
                }
            )

    used_anchors: set[str] = set()
    items: list[dict[str, Any]] = []
    for bullet in bullets:
        b_tokens = _extract_match_tokens(bullet)
        best: dict[str, Any] | None = None
        best_score = 0.0
        if b_tokens:
            for cand in candidates:
                if cand["anchor"] in used_anchors:
                    continue
                t_hits = len(b_tokens & cand["title_tokens"])
                b_hits = len(b_tokens & cand["body_tokens"])
                # Title overlap carries higher weight than body overlap
                title_ratio = t_hits / max(1, min(len(b_tokens), len(cand["title_tokens"])))
                body_ratio = b_hits / len(b_tokens)
                score = 0.65 * title_ratio + 0.35 * body_ratio
                if cand["importance"] == "high":
                    score += 0.05
                if score > best_score:
                    best_score = score
                    best = cand

        if best is not None and best_score >= 0.25:
            used_anchors.add(best["anchor"])
            items.append(
                {
                    "html": render_inline_md(bullet),
                    "anchor": best["anchor"],
                    "badge": best["badge"],
                }
            )
        else:
            items.append(
                {
                    "html": render_inline_md(bullet),
                    "anchor": None,
                    "badge": None,
                }
            )
    return items


def render_inline_md(text: str) -> str:
    """Safely render inline Markdown (**bold**, *italic*, [label](url)) with HTML escaping."""
    escaped = html.escape(text, quote=True)
    escaped = _LINK_RE.sub(
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', escaped
    )
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    return escaped


def render_summary_html(md_text: str) -> str:
    """Safely convert event summary Markdown (paragraphs + bullet lists) into HTML."""
    blocks = re.split(r"\n\s*\n", (md_text or "").strip())
    html_parts: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.startswith(("- ", "* ")) for line in lines):
            items = "".join(f"<li>{render_inline_md(line[2:].strip())}</li>" for line in lines)
            html_parts.append(f"<ul>{items}</ul>")
        else:
            # Handle mixed paragraph + bullet list within one block cleanly
            para_buf: list[str] = []
            list_buf: list[str] = []
            for line in lines:
                if line.startswith(("- ", "* ")):
                    if para_buf:
                        html_parts.append(f"<p>{render_inline_md(' '.join(para_buf))}</p>")
                        para_buf.clear()
                    list_buf.append(line[2:].strip())
                else:
                    if list_buf:
                        items = "".join(f"<li>{render_inline_md(i)}</li>" for i in list_buf)
                        html_parts.append(f"<ul>{items}</ul>")
                        list_buf.clear()
                    para_buf.append(line)
            if para_buf:
                html_parts.append(f"<p>{render_inline_md(' '.join(para_buf))}</p>")
            if list_buf:
                items = "".join(f"<li>{render_inline_md(i)}</li>" for i in list_buf)
                html_parts.append(f"<ul>{items}</ul>")
    return "\n".join(html_parts)


def _format_rfc822(iso_str: str | None, fallback_date: str) -> str:
    if iso_str:
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return format_datetime(dt.astimezone(UTC))
        except ValueError:
            pass
    dt = datetime.strptime(fallback_date, "%Y-%m-%d").replace(tzinfo=UTC)
    return format_datetime(dt)


def _prepare_report_view(report_json: dict[str, Any]) -> dict[str, Any]:
    """Enrich a stored report JSON dict with pre-rendered HTML for templates & RSS."""
    view = dict(report_json)
    bullets = report_json.get("overview_bullets", [])
    view["overview_html"] = [render_inline_md(b) for b in bullets]
    sections_view = []
    for sec in report_json.get("sections", []):
        sec_copy = dict(sec)
        events_view = []
        for idx, ev in enumerate(sec.get("events", []), 1):
            ev_copy = dict(ev)
            ev_copy["anchor"] = f"event-{ev['id']}" if ev.get("id") else f"{sec['sport']}-{idx}"
            ev_copy["summary_html"] = render_summary_html(ev.get("summary_md", ""))
            ev_copy["search_blob"] = " ".join(
                [
                    ev.get("title", ""),
                    ev.get("summary_md", ""),
                    sec.get("badge", ""),
                    sec.get("sport_name", ""),
                ]
            ).lower()
            events_view.append(ev_copy)
        sec_copy["events"] = events_view
        sections_view.append(sec_copy)
    view["sections"] = sections_view
    view["overview_items"] = _match_overview_bullets(bullets, sections_view)
    view["pub_rfc822"] = _format_rfc822(
        report_json.get("generated_at"), report_json["report_date"]
    )
    return view


def _build_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_site_from_reports(
    reports: list[dict[str, Any]],
    output_dir: Path,
    site_url: str = "https://sports.yhao.dev",
) -> dict[str, Any]:
    """Render static HTML site, structured JSON files, and RSS 2.0 feed to output_dir."""
    site_url = site_url.rstrip("/")
    env = _build_jinja_env()

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy static assets
    assets_out = output_dir / "assets"
    shutil.copytree(_STATIC_DIR, assets_out)

    # Sort reports newest first
    ordered_reports = sorted(reports, key=lambda r: r["report_date"], reverse=True)
    views = [_prepare_report_view(r) for r in ordered_reports]

    report_tpl = env.get_template("report.html")
    archives_tpl = env.get_template("archives.html")
    rss_tpl = env.get_template("rss.xml")

    data_dir = output_dir / "data"
    data_reports_dir = data_dir / "reports"
    data_reports_dir.mkdir(parents=True, exist_ok=True)

    index_entries: list[dict[str, Any]] = []
    months: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    for i, view in enumerate(views):
        rdate = view["report_date"]
        prev_date = views[i + 1]["report_date"] if i + 1 < len(views) else None
        next_date = views[i - 1]["report_date"] if i > 0 else None

        # Per-day permalink: /reports/YYYY-MM-DD/index.html
        day_dir = output_dir / "reports" / rdate
        day_dir.mkdir(parents=True, exist_ok=True)
        day_html = report_tpl.render(
            site_url=site_url,
            canonical_url=f"{site_url}/reports/{rdate}/",
            report=view,
            is_home=False,
            prev_date=prev_date,
            next_date=next_date,
            total_reports=len(views),
            page_title=f"体育日报 {rdate} · spnews",
        )
        (day_dir / "index.html").write_text(day_html, encoding="utf-8")

        # Per-day raw JSON
        raw_json = ordered_reports[i]
        (data_reports_dir / f"{rdate}.json").write_text(
            json.dumps(raw_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Archive metadata
        badges = [s["badge"] for s in view["sections"]]
        titles = [ev["title"] for s in view["sections"] for ev in s["events"]]
        entry = {
            "report_date": rdate,
            "url": f"/reports/{rdate}/",
            "badges": badges,
            "event_count": len(titles),
            "high_count": sum(
                1 for s in view["sections"] for ev in s["events"] if ev["importance"] == "high"
            ),
            "lead": (view.get("overview_bullets") or [""])[0],
            "search_blob": " ".join([rdate, *badges, *titles]).lower(),
        }
        index_entries.append(entry)
        month_key = rdate[:7]
        months.setdefault(month_key, []).append(entry)

    # Homepage: latest report (or clean empty state)
    if views:
        home_html = report_tpl.render(
            site_url=site_url,
            canonical_url=f"{site_url}/",
            report=views[0],
            is_home=True,
            prev_date=views[1]["report_date"] if len(views) > 1 else None,
            next_date=None,
            total_reports=len(views),
            page_title=f"spnews · 体育日报 {views[0]['report_date']}",
        )
        (data_dir / "latest.json").write_text(
            json.dumps(ordered_reports[0], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        home_html = report_tpl.render(
            site_url=site_url,
            canonical_url=f"{site_url}/",
            report=None,
            is_home=True,
            prev_date=None,
            next_date=None,
            total_reports=0,
            page_title="spnews · 体育日报",
        )
    (output_dir / "index.html").write_text(home_html, encoding="utf-8")

    # Archives page
    archives_dir = output_dir / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)
    archives_html = archives_tpl.render(
        site_url=site_url,
        canonical_url=f"{site_url}/archives/",
        months=list(months.items()),
        total_reports=len(views),
        page_title="历史归档 · spnews",
    )
    (archives_dir / "index.html").write_text(archives_html, encoding="utf-8")

    # Index JSON
    (data_dir / "index.json").write_text(
        json.dumps(
            {
                "site_url": site_url,
                "updated_at": datetime.now(UTC).isoformat(),
                "total_reports": len(index_entries),
                "reports": [
                    {k: v for k, v in e.items() if k != "search_blob"} for e in index_entries
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # RSS 2.0 feed (most recent 30 reports)
    rss_xml = rss_tpl.render(
        site_url=site_url,
        build_date=format_datetime(datetime.now(UTC)),
        reports=views[:30],
    )
    (output_dir / "rss.xml").write_text(rss_xml, encoding="utf-8")

    return {
        "output_dir": str(output_dir),
        "reports_rendered": len(views),
        "latest_date": views[0]["report_date"] if views else None,
    }


def build_site(settings: Settings, output_dir: Path = Path("dist")) -> dict[str, Any]:
    """Load all reports from PostgreSQL and render the static site."""
    rows = list_reports(settings.spnews_database_url)
    reports = [r["report_json"] for r in rows]
    return build_site_from_reports(reports, output_dir=output_dir, site_url=settings.site_url)
