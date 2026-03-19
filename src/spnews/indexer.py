"""Homepage/archive index generation for GitHub Pages."""

from __future__ import annotations

from pathlib import Path
import re

_REPORT_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_sports_daily\.md$")

_REPORT_START = "<!-- REPORT_LIST_START -->"
_REPORT_END = "<!-- REPORT_LIST_END -->"

_ARCHIVE_START = "<!-- ARCHIVE_LIST_START -->"
_ARCHIVE_END = "<!-- ARCHIVE_LIST_END -->"


def _replace_between_markers(content: str, start: str, end: str, replacement: str) -> str:
    pattern = re.compile(rf"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)
    block = f"{start}\n{replacement}\n{end}"
    if pattern.search(content):
        return pattern.sub(block, content)
    return content + f"\n\n{block}\n"


def _sport_coverage(report_path: Path) -> str:
    text = report_path.read_text(encoding="utf-8")
    sports: list[str] = []
    if "## 棒球 (MLB)" in text:
        sports.append("MLB")
    if "## 橄榄球 (NFL)" in text:
        sports.append("NFL")
    if "## F1 赛车" in text:
        sports.append("F1")
    return " · ".join(sports) if sports else "-"


def _build_rows(reports: list[Path]) -> list[str]:
    rows: list[str] = []
    for report in reports:
        match = _REPORT_PATTERN.match(report.name)
        if not match:
            continue
        date = match.group(1)
        coverage = _sport_coverage(report)
        html_link = f"output/{report.stem}.html"
        rows.append(
            f"<tr><td><a href=\"{html_link}\">{date}</a></td><td>{coverage}</td></tr>"
        )
    return rows


def _all_reports(output_dir: Path) -> list[Path]:
    reports = []
    for path in output_dir.glob("*_sports_daily.md"):
        if _REPORT_PATTERN.match(path.name):
            reports.append(path)
    return sorted(reports, key=lambda p: p.name, reverse=True)


def _ensure_archives_page(path: Path) -> None:
    if path.exists():
        return
    content = """---
---

# Archived Sports Daily Reports

历史日报列表如下，按日期倒序排列。

<table>
    <thead>
        <tr><th>日期</th><th>涵盖运动</th></tr>
    </thead>
    <tbody>
<!-- ARCHIVE_LIST_START -->
<!-- ARCHIVE_LIST_END -->
    </tbody>
</table>

返回首页: [spnews 日报首页](./)
"""
    path.write_text(content, encoding="utf-8")


def update_report_indexes(project_root: Path | None = None, recent_limit: int = 10) -> None:
    root = project_root or Path.cwd()
    output_dir = root / "output"
    index_path = root / "index.md"
    archives_path = root / "archives.md"

    if not output_dir.exists() or not index_path.exists():
        return

    _ensure_archives_page(archives_path)

    reports = _all_reports(output_dir)
    recent = reports[:recent_limit]

    recent_rows = _build_rows(recent)
    all_rows = _build_rows(reports)

    recent_block = "\n".join([
        "<table>",
        "  <thead>",
        "    <tr><th>📅 日期</th><th>🏆 涵盖运动</th></tr>",
        "  </thead>",
        "  <tbody>",
        *recent_rows,
        "  </tbody>",
        "</table>",
        "",
        f"> 共 {len(reports)} 份日报，查看完整历史列表: [Archived Reports](archives.html)",
    ])

    archive_block = "\n".join([
        *all_rows,
    ])

    index_content = index_path.read_text(encoding="utf-8")
    index_content = _replace_between_markers(index_content, _REPORT_START, _REPORT_END, recent_block)
    index_path.write_text(index_content, encoding="utf-8")

    archive_content = archives_path.read_text(encoding="utf-8")
    archive_content = _replace_between_markers(archive_content, _ARCHIVE_START, _ARCHIVE_END, archive_block)
    archives_path.write_text(archive_content, encoding="utf-8")
