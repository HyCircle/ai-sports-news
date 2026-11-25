"""Async RSS feed ingestion with URL canonicalization and deterministic noise filtering."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from calendar import timegm
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx
from dateutil import parser as dateparser

from .config import Settings
from .db import save_articles
from .sources import ALL_SPORT_KEYS, SPORT_MAP, canonicalize_url, classify_noise

logger = logging.getLogger("spnews.ingest")

_USER_AGENT = "spnews/0.2 (+https://sports.yhao.dev)"
_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|li|h[1-6]|blockquote)\b[^>]*>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def clean_html(raw: str, preserve_paragraphs: bool = False) -> str:
    """Strip HTML tags and decode entities cleanly."""
    if not raw:
        return ""
    text = raw
    if preserve_paragraphs:
        text = _BLOCK_TAG_RE.sub("\n\n", text)
    text = _ANY_TAG_RE.sub("", text)
    text = html.unescape(text)
    if preserve_paragraphs:
        lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
        return _MULTI_NEWLINE_RE.sub("\n\n", "\n".join(lines)).strip()
    return _MULTI_SPACE_RE.sub(" ", text).replace("\n", " ").strip()


def parse_entry_time(entry: Any) -> datetime | None:
    """Parse an RSS entry timestamp into timezone-aware UTC."""
    for field in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, field, None)
        if tp:
            return datetime.fromtimestamp(timegm(tp), tz=UTC)
    for field in ("published", "updated"):
        raw = getattr(entry, field, None)
        if raw:
            try:
                dt = dateparser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except (ValueError, TypeError):
                continue
    return None


def _extract_rss_content(entry: Any) -> str:
    """Extract embedded full-text content from RSS <content:encoded> when provided."""
    contents = entry.get("content") or []
    parts = [
        clean_html(item.get("value", ""), preserve_paragraphs=True)
        for item in contents
        if isinstance(item, dict) and item.get("value")
    ]
    return "\n\n".join(p for p in parts if p)


async def _fetch_feed(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    sport: str,
    url: str,
) -> tuple[str, str, bytes | None, str | None]:
    try:
        async with sem:
            resp = await client.get(url)
            resp.raise_for_status()
            return sport, url, resp.content, None
    except httpx.HTTPError as exc:
        logger.warning("Feed fetch failed [%s] %s: %s", sport, url, exc)
        return sport, url, None, str(exc)


async def ingest_sports(
    settings: Settings,
    sports: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch all RSS feeds concurrently, filter noise, and persist into PostgreSQL."""
    target_sports = list(sports) if sports else list(ALL_SPORT_KEYS)
    cutoff: datetime | None = None
    if settings.rss_fetch_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=settings.rss_fetch_days)

    sem = asyncio.Semaphore(settings.http_concurrency)
    tasks = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        for sport in target_sports:
            for url in SPORT_MAP[sport].feeds:
                tasks.append(_fetch_feed(client, sem, sport, url))
        results = await asyncio.gather(*tasks)

    by_sport_rows: dict[str, list[dict[str, Any]]] = {s: [] for s in target_sports}
    seen_urls: set[str] = set()
    stats: dict[str, Any] = {
        "feeds_ok": 0,
        "feeds_failed": [],
        "raw_entries": 0,
        "invalid_url": 0,
        "too_old": 0,
        "inserted_pending": 0,
        "inserted_filtered": 0,
        "filter_reasons": Counter(),
        "by_sport": {},
    }

    for sport, url, raw_bytes, err in results:
        if err is not None or raw_bytes is None:
            stats["feeds_failed"].append({"sport": sport, "url": url, "error": err})
            continue
        stats["feeds_ok"] += 1
        feed = feedparser.parse(raw_bytes)
        source_name = (feed.feed.get("title") or url).strip()

        for entry in feed.entries:
            stats["raw_entries"] += 1
            canon = canonicalize_url(entry.get("link", ""))
            if not canon:
                stats["invalid_url"] += 1
                continue
            if canon in seen_urls:
                continue
            published = parse_entry_time(entry)
            if cutoff and published is not None and published < cutoff:
                stats["too_old"] += 1
                continue

            seen_urls.add(canon)
            title = clean_html(entry.get("title", ""))
            if not title:
                continue
            summary = clean_html(entry.get("summary") or entry.get("description") or "")
            content_rss = _extract_rss_content(entry)
            reason = classify_noise(canon, title)
            if reason:
                stats["filter_reasons"][reason] += 1

            by_sport_rows[sport].append(
                {
                    "canonical_url": canon,
                    "sport": sport,
                    "source_name": source_name,
                    "title": title,
                    "summary": summary,
                    "content_from_rss": content_rss,
                    "published_at": published,
                    "status": "filtered" if reason else "pending",
                    "filter_reason": reason,
                }
            )

    for sport in target_sports:
        pending_n, filtered_n = await asyncio.to_thread(
            save_articles, settings.spnews_database_url, by_sport_rows[sport]
        )
        stats["inserted_pending"] += pending_n
        stats["inserted_filtered"] += filtered_n
        stats["by_sport"][sport] = {
            "candidates": len(by_sport_rows[sport]),
            "inserted_pending": pending_n,
            "inserted_filtered": filtered_n,
        }

    stats["filter_reasons"] = dict(stats["filter_reasons"])
    return stats
