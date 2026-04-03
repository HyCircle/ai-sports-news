"""RSS feed fetching with database-driven deduplication."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
from dateutil import parser as dateparser

from .config import RSS_SOURCES
from .db import save_articles


def _parse_time(entry) -> datetime | None:
    """Extract publish time from an RSS entry."""
    for field in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, field, None)
        if tp:
            from calendar import timegm
            return datetime.fromtimestamp(timegm(tp), tz=timezone.utc)
    for field in ("published", "updated"):
        raw = getattr(entry, field, None)
        if raw:
            try:
                return dateparser.parse(raw).astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def _clean_html(raw: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(text).strip()


def _extract_entry(entry, source_name: str) -> dict:
    """Convert a feedparser entry to a clean dict."""
    return {
        "title": entry.get("title", "").strip(),
        "link": entry.get("link", ""),
        "summary": _clean_html(entry.get("summary", entry.get("description", ""))),
        "published": _parse_time(entry),
        "source_name": source_name,
    }


def fetch_sport(sport: str, db_path: str | Path,
                max_age_days: int = 0) -> int:
    """Fetch all RSS entries for a sport and save new ones to the database.

    Only entries published within the last *max_age_days* days are considered
    (entries with no published date are always included).
    Pass max_age_days=0 to disable the age filter.

    Returns the number of newly inserted articles.
    """
    from datetime import timedelta
    urls = RSS_SOURCES.get(sport, [])
    articles: list[dict] = []
    seen_links: set[str] = set()

    cutoff: datetime | None = None
    if max_age_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    for url in urls:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  [WARN] Failed to fetch {url}: {e}")
            continue

        source_name = feed.feed.get("title", url)
        for entry in feed.entries:
            art = _extract_entry(entry, source_name)
            if not art["link"] or art["link"] in seen_links:
                continue
            # Age filter: skip entries older than cutoff (keep entries with no date)
            if cutoff and art["published"] is not None and art["published"] < cutoff:
                continue
            seen_links.add(art["link"])
            articles.append(art)

    if not articles:
        return 0

    return save_articles(db_path, articles, sport)
