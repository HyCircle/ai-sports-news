"""Markdown report generation with database-driven workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import SPORT_NAMES, DEFAULT_TIMEZONE, DB_PATH
from .db import init_db, get_pending_articles, get_recent_events
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


def _build_sport_section(
    sport: str,
    articles: list[dict],
    report_date: str,
    recent_events: list[dict] | None = None,
) -> tuple[str | None, list[dict], list[str]]:
    """Build markdown for one sport.

    Returns (md_section, generated_events, used_links).
    md_section is None if no articles.
    """
    sport_name = SPORT_NAMES.get(sport, sport)
    print(f"\n{'='*50}")
    print(f"Processing: {sport_name}")
    print(f"{'='*50}")
    print(f"  {len(articles)} pending articles")

    if not articles:
        return None, [], []

    # 1. Cluster (with memory context)
    print("  Clustering articles...")
    clusters = cluster_articles(articles, sport_name, recent_events=recent_events)
    print(f"  Found {len(clusters)} events")

    # Build lookup for previous coverage
    prev_lookup: dict[str, str] = {}
    if recent_events:
        for ev in recent_events:
            prev_lookup[ev["event_name"]] = ev["summary_text"]

    # 2. Summarize each cluster and collect tracking data
    md = f"## {sport_name}\n\n"
    generated_events: list[dict] = []
    used_links: list[str] = []

    for cluster in clusters:
        event = cluster["event"]
        importance = cluster.get("importance", "medium")
        indices = cluster["article_indices"]
        cluster_arts = [articles[i] for i in indices if i < len(articles)]

        if not cluster_arts:
            continue

        # Find previous coverage if LLM linked to a prior event
        previous_coverage = None
        related = cluster.get("related_previous_event")
        if related and related in prev_lookup:
            previous_coverage = prev_lookup[related]

        icon = _IMPORTANCE_ICON.get(importance, "")
        print(f"  Summarizing: {event} ({importance})...")

        summary = summarize_event(
            event, cluster_arts, importance,
            report_date=report_date,
            previous_coverage=previous_coverage,
        )
        md += f"### {icon}{event}\n\n"
        md += summary + "\n\n"
        md += _source_links(cluster_arts) + "\n\n"

        # Track for DB closing update
        art_links = [a["link"] for a in cluster_arts]
        generated_events.append({
            "event_name": event,
            "importance": importance,
            "summary_text": summary,
            "article_links": art_links,
        })
        used_links.extend(art_links)

    return md, generated_events, used_links


def build_full_report(
    sports: list[str] | None = None,
    db_path: str | Path | None = None,
) -> tuple[str, dict[str, list[dict]], list[str]]:
    """Build the complete daily report using database-driven workflow.

    Returns (report_markdown, events_by_sport, all_used_links).
    The caller is responsible for the closing DB update after writing the file.
    """
    if sports is None:
        sports = list(SPORT_NAMES.keys())
    if db_path is None:
        db_path = DB_PATH

    # Initialize database
    init_db(db_path)

    tz = ZoneInfo(DEFAULT_TIMEZONE)
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    report_date = f"{now.year}年{now.month}月{now.day}日"

    sport_sections: dict[str, str] = {}
    all_events: dict[str, list[dict]] = {}
    all_used_links: list[str] = []

    for sport in sports:
        # 1. Incremental fetch → DB
        print(f"\n  Fetching RSS feeds for {sport}...")
        n_new = fetch_sport(sport, db_path)
        print(f"  {n_new} new articles saved to database")

        # 2. Get pending articles (report_date IS NULL)
        articles = get_pending_articles(db_path, sport)

        # 3. Get recent events for memory/continuity
        recent_events = get_recent_events(db_path, sport, days=3)

        # 4. Build section
        section, events, links = _build_sport_section(
            sport, articles, report_date, recent_events,
        )
        if section:
            sport_sections[sport] = section
            all_events[sport] = events
            all_used_links.extend(links)

    if not sport_sections:
        return f"---\n---\n\n# 体育日报 {date_str}\n\n暂无新闻。\n", {}, []

    sport_labels = {SPORT_NAMES.get(s, s): sec for s, sec in sport_sections.items()}

    # Generate overview
    print("\nGenerating overview...")
    overview = generate_overview(sport_labels)

    # Assemble report
    report = "---\n---\n\n"
    report += f"# 体育日报 {date_str}\n\n"
    report += f"{overview}\n\n"
    report += "---\n\n"
    for section in sport_sections.values():
        report += section + "---\n\n"

    report += f"*生成时间: {now.strftime('%Y-%m-%d %H:%M %Z')}*\n"
    report += f"*数据来源: RSS 自动抓取 + AI 总结，仅供参考*\n"
    return report, all_events, all_used_links
