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


def fetch_sport(sport: str, db_path: str | Path) -> int:
    """Fetch all RSS entries for a sport and save new ones to the database.

    Returns the number of newly inserted articles.
    """
    urls = RSS_SOURCES.get(sport, [])
    articles: list[dict] = []
    seen_links: set[str] = set()

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
            seen_links.add(art["link"])
            articles.append(art)

    if not articles:
        return 0

    return save_articles(db_path, articles, sport)
