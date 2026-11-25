"""On-demand full-text article extraction for selected event clusters."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from typing import Any

import httpx
import trafilatura

from .cluster import FinalEventCluster
from .config import Settings
from .db import save_fetched_bodies
from .ingest import clean_html

logger = logging.getLogger("spnews.enrich")

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_ESPN_STORY_ID_RE = re.compile(r"espn\.com/[^?]+?/(?:story|preview)/_/id/(\d+)", re.IGNORECASE)
_MIN_BODY_CHARS = 300
_MAX_BODY_CHARS = 4000


def _pick_representative_articles(
    articles: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Select up to *limit* articles preferring distinct sources and richer snippets."""
    selected: list[dict[str, Any]] = []
    seen_sources: set[str] = set()

    # Pass 1: one article per distinct source (prioritize those with existing content/summary)
    ranked = sorted(
        articles,
        key=lambda a: (
            len(a.get("fetched_body") or "") > 0,
            len(a.get("content_from_rss") or "") >= _MIN_BODY_CHARS,
            len(a.get("summary") or ""),
        ),
        reverse=True,
    )
    for art in ranked:
        if len(selected) >= limit:
            break
        src = art.get("source_name") or ""
        if src not in seen_sources:
            seen_sources.add(src)
            selected.append(art)

    # Pass 2: fill remaining slots if cluster has fewer distinct sources than limit
    if len(selected) < limit:
        selected_ids = {a["id"] for a in selected}
        for art in ranked:
            if len(selected) >= limit:
                break
            if art["id"] not in selected_ids:
                selected.append(art)
                selected_ids.add(art["id"])
    return selected


def _extract_trafilatura(html_text: str, url: str) -> str | None:
    extracted = trafilatura.extract(
        html_text,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
        deduplicate=True,
    )
    if not extracted:
        return None
    cleaned = extracted.strip()
    return cleaned[:_MAX_BODY_CHARS] if len(cleaned) >= _MIN_BODY_CHARS else None


async def _fetch_espn_api(client: httpx.AsyncClient, story_id: str) -> str | None:
    url = f"https://now.core.api.espn.com/v1/sports/news/{story_id}"
    try:
        resp = await client.get(url, timeout=12.0)
        if resp.status_code != 200:
            return None
        headlines = resp.json().get("headlines") or []
        if not headlines:
            return None
        raw_story = headlines[0].get("story") or ""
        if not raw_story:
            return None
        cleaned = clean_html(raw_story, preserve_paragraphs=True)
        return cleaned[:_MAX_BODY_CHARS] if len(cleaned) >= _MIN_BODY_CHARS else None
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("ESPN API fallback failed for id=%s: %s", story_id, exc)
        return None


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    art: dict[str, Any],
) -> tuple[int, str | None, str]:
    """Fetch full text for a single article. Returns (article_id, body_or_none, source_tag)."""
    aid = int(art["id"])
    url = art["canonical_url"]

    # Fast path 1: already cached in DB
    if art.get("fetched_body"):
        return aid, art["fetched_body"][:_MAX_BODY_CHARS], "cached"

    # Fast path 2: RSS feed already included full content (e.g. PFT, The Race)
    rss_content = (art.get("content_from_rss") or "").strip()
    if len(rss_content) >= _MIN_BODY_CHARS:
        return aid, rss_content[:_MAX_BODY_CHARS], "rss_content"

    async with sem:
        # Fast path 3: ESPN official public news JSON endpoint
        m = _ESPN_STORY_ID_RE.search(url)
        if m:
            espn_body = await _fetch_espn_api(client, m.group(1))
            if espn_body:
                return aid, espn_body, "espn_api"

        # General path: HTTP GET + trafilatura main-text extraction
        try:
            resp = await client.get(url, timeout=15.0)
            if resp.status_code != 200:
                logger.info("Full-text fetch HTTP %d for %s", resp.status_code, url)
                return aid, None, "failed"
            body = await asyncio.to_thread(_extract_trafilatura, resp.text, url)
            if body:
                return aid, body, "trafilatura"
            logger.info("Trafilatura extracted insufficient text for %s", url)
            return aid, None, "failed"
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            logger.info("Full-text fetch error for %s: %s", url, exc)
            return aid, None, "failed"


async def enrich_clusters(
    settings: Settings,
    clusters: list[FinalEventCluster],
    persist_cache: bool = True,
) -> dict[str, int]:
    """Fetch full-text bodies for representative articles across all clusters.

    Attaches `enriched_body` in-memory to each fetched article dict and optionally
    caches newly fetched bodies in PostgreSQL.
    """
    unique_targets: dict[int, dict[str, Any]] = {}
    for cluster in clusters:
        reps = _pick_representative_articles(cluster.articles, settings.max_enrich_per_event)
        for art in reps:
            unique_targets[int(art["id"])] = art

    if not unique_targets:
        return {}

    sem = asyncio.Semaphore(settings.http_concurrency)
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, sem, art) for art in unique_targets.values())
        )

    counts: Counter[str] = Counter()
    to_cache: dict[int, str] = {}
    for aid, body, tag in results:
        counts[tag] += 1
        if body:
            unique_targets[aid]["enriched_body"] = body
            if tag in ("espn_api", "trafilatura"):
                to_cache[aid] = body

    if persist_cache and to_cache:
        await asyncio.to_thread(save_fetched_bodies, settings.spnews_database_url, to_cache)

    return dict(counts)
