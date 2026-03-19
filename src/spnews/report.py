"""Markdown report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from .config import SPORT_NAMES, DEFAULT_TIMEZONE
from .fetcher import fetch_sport
from .cluster import cluster_articles
from .summarizer import summarize_event, generate_overview

_IMPORTANCE_ICON = {"high": "🔥 ", "medium": "", "low": ""}


def _source_links(articles: list[dict]) -> str:
    """Format source links inside a collapsible <details> block."""
    lines = []
    seen = set()
    for art in articles:
        if art["link"] not in seen:
            seen.add(art["link"])
            title = escape(f"{art['source_name']}: {art['title']}")
            link = escape(art["link"], quote=True)
            lines.append(
                f"<li><a href=\"{link}\" target=\"_blank\" rel=\"noopener noreferrer\">{title}</a></li>"
            )
    inner = "\n".join(lines)
    return (
        f"<details>\n"
        f"<summary>\u4fe1\u606f\u6765\u6e90({len(lines)})</summary>\n"
        f"<ul>\n{inner}\n</ul>\n"
        f"</details>"
    )


def build_sport_section(sport: str, hours: int = 24,
                        report_date: str = "") -> str | None:
    """Build the markdown section for a single sport. Returns None if no articles."""
    sport_name = SPORT_NAMES.get(sport, sport)
    print(f"\n{'='*50}")
    print(f"Processing: {sport_name}")
    print(f"{'='*50}")

    # 1. Fetch
    print(f"  Fetching feeds (past {hours}h)...")
    articles = fetch_sport(sport, hours)
    print(f"  Found {len(articles)} articles")

    if not articles:
        return None

    # 2. Cluster
    print("  Clustering articles...")
    clusters = cluster_articles(articles, sport_name)
    print(f"  Found {len(clusters)} events")

    # 3. Summarize each cluster
    md = f"## {sport_name}\n\n"

    for cluster in clusters:
        event = cluster["event"]
        importance = cluster.get("importance", "medium")
        indices = cluster["article_indices"]
        cluster_articles_list = [articles[i] for i in indices if i < len(articles)]

        if not cluster_articles_list:
            continue

        icon = _IMPORTANCE_ICON.get(importance, "")
        print(f"  Summarizing: {event} ({importance})...")

        summary = summarize_event(event, cluster_articles_list, importance,
                                  report_date=report_date)
        md += f"### {icon}{event}\n\n"
        md += summary + "\n\n"
        md += _source_links(cluster_articles_list) + "\n\n"

    return md


def build_full_report(sports: list[str] | None = None, hours: int = 24) -> str:
    """Build the complete daily report for all specified sports."""
    if sports is None:
        sports = list(SPORT_NAMES.keys())

    tz = ZoneInfo(DEFAULT_TIMEZONE)
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    report_date = f"{now.year}年{now.month}月{now.day}日"

    sport_sections = {}
    for sport in sports:
        section = build_sport_section(sport, hours, report_date=report_date)
        if section:
            sport_sections[sport] = section

    if not sport_sections:
        return f"---\n---\n\n# 体育早报 {date_str}\n\n暂无新闻。\n"

    sport_labels = {SPORT_NAMES.get(s, s): sec for s, sec in sport_sections.items()}

    # Generate overview
    print("\nGenerating overview...")
    overview = generate_overview(sport_labels)

    # Assemble report
    report = "---\n---\n\n"
    report += f"# 体育早报 {date_str}\n\n"
    report += f"{overview}\n\n"
    report += "---\n\n"
    for section in sport_sections.values():
        report += section + "---\n\n"

    report += f"*生成时间: {now.strftime('%Y-%m-%d %H:%M %Z')}*\n"
    report += f"*数据来源: RSS 自动抓取 + AI 总结，仅供参考*\n"
    return report
