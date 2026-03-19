"""RSS feed fetching with time filtering."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import feedparser
from dateutil import parser as dateparser

from .config import RSS_SOURCES


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


def _extract_entry(entry) -> dict:
    """Convert a feedparser entry to a clean dict."""
    return {
        "title": entry.get("title", "").strip(),
        "link": entry.get("link", ""),
        "summary": _clean_html(entry.get("summary", entry.get("description", ""))),
        "published": _parse_time(entry),
        "source": entry.get("link", ""),
    }


def fetch_sport(sport: str, hours: int = 24) -> list[dict]:
    """Fetch recent articles for a sport within the given time window."""
    urls = RSS_SOURCES.get(sport, [])
    cutoff = datetime.now(timezone.utc).replace(microsecond=0)
    from datetime import timedelta
    cutoff = cutoff - timedelta(hours=hours)

    articles = []
    seen_links = set()

    for url in urls:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  [WARN] Failed to fetch {url}: {e}")
            continue

        source_name = feed.feed.get("title", url)
        for entry in feed.entries:
            art = _extract_entry(entry)
            art["source_name"] = source_name

            # Deduplicate by link
            if art["link"] in seen_links:
                continue
            seen_links.add(art["link"])

            # Time filter: keep if within window or unknown time
            if art["published"] and art["published"] < cutoff:
                continue

            articles.append(art)

    # Sort by time (newest first), unknowns at end
    articles.sort(key=lambda a: a["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return articles
