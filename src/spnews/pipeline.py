"""End-to-end daily sports report pipeline orchestration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .cluster import FinalEventCluster, cluster_sport_articles
from .config import Settings
from .db import (
    commit_report_run,
    finish_run,
    get_pending_articles,
    init_db,
    start_run,
)
from .embed import embed_pending_articles, format_event_for_embed
from .enrich import enrich_clusters
from .ingest import ingest_sports
from .llm import ChatClient, EmbedClient
from .sources import ALL_SPORT_KEYS, SPORT_MAP
from .summarize import build_calendar_reference, generate_overview, summarize_sport_clusters

logger = logging.getLogger("spnews.pipeline")


async def run_ingest_and_embed(
    settings: Settings,
    sports: list[str] | None = None,
) -> dict[str, Any]:
    """Stage 1 + Stage 2a: fetch RSS feeds and vectorize pending articles."""
    target_sports = list(sports) if sports else list(ALL_SPORT_KEYS)
    ingest_stats = await ingest_sports(settings, target_sports)

    async with EmbedClient(
        base_url=settings.embed_base_url,
        model=settings.embed_model,
        api_key=settings.resolved_embed_api_key(),
        dim=settings.embed_dim,
    ) as embed_client:
        embedded_n = await embed_pending_articles(settings, embed_client, target_sports)
        embed_usage = embed_client.usage.as_dict()

    return {
        "ingest": ingest_stats,
        "embedded_articles": embedded_n,
        "embed_usage": embed_usage,
    }


async def run_generate(
    settings: Settings,
    sports: list[str] | None = None,
    *,
    dry_run: bool = False,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stage 2b + Stage 3: hybrid cluster, on-demand enrich, summarize, and optionally commit.

    In dry_run mode, reads pending articles from PostgreSQL and builds the full
    structured report without marking articles done or saving to events/reports.
    """
    target_sports = list(sports) if sports else list(ALL_SPORT_KEYS)
    effective_base = llm_base_url or settings.llm_base_url
    effective_model = llm_model or settings.llm_model
    effective_settings = settings.model_copy(
        update={"llm_base_url": effective_base, "llm_model": effective_model}
    )

    tz = ZoneInfo(effective_settings.timezone)
    now = datetime.now(tz)
    report_date = now.strftime("%Y-%m-%d")
    calendar_ref = build_calendar_reference(now, days=14)

    pending_by_sport: dict[str, list[dict[str, Any]]] = {}
    for sport in target_sports:
        pending_by_sport[sport] = await asyncio.to_thread(
            get_pending_articles, effective_settings.spnews_database_url, sport
        )

    stats: dict[str, Any] = {
        "report_date": report_date,
        "dry_run": dry_run,
        "llm_model": effective_model,
        "llm_base_url": effective_base,
        "cluster_by_sport": {},
        "enrich": {},
    }

    async with ChatClient(
        base_url=effective_base,
        model=effective_model,
        api_key=effective_settings.resolved_llm_api_key(),
        concurrency=effective_settings.llm_concurrency,
    ) as chat_client:
        # 1. Hybrid clustering per sport (concurrently across sports)
        async def _cluster_one(sport: str) -> tuple[str, list[FinalEventCluster], dict[str, Any]]:
            arts = pending_by_sport[sport]
            if not arts:
                return sport, [], {"pending": 0, "micro_clusters": 0, "memory_hits": 0, "final_events": 0}
            meta = SPORT_MAP[sport]
            clusters, c_stats = await cluster_sport_articles(
                effective_settings, chat_client, sport, meta.name, arts
            )
            return sport, clusters, c_stats

        cluster_results = await asyncio.gather(*(_cluster_one(s) for s in target_sports))

        clusters_by_sport: dict[str, list[FinalEventCluster]] = {}
        all_clusters: list[FinalEventCluster] = []
        for sport, clusters, c_stats in cluster_results:
            clusters_by_sport[sport] = clusters
            stats["cluster_by_sport"][sport] = c_stats
            all_clusters.extend(clusters)

        # 2. On-demand full-text enrichment for selected representative articles
        stats["enrich"] = await enrich_clusters(
            effective_settings, all_clusters, persist_cache=True
        )

        # 3. Concurrent event summarization across all sports
        async def _summarize_sport(sport: str) -> tuple[str, list[str]]:
            clusters = clusters_by_sport[sport]
            summaries = await summarize_sport_clusters(chat_client, clusters, calendar_ref, tz)
            return sport, summaries

        summary_results = await asyncio.gather(*(_summarize_sport(s) for s in target_sports))
        summaries_by_sport = dict(summary_results)

        # 4. Assemble structured report sections
        sections: list[dict[str, Any]] = []
        events_to_save: list[dict[str, Any]] = []
        used_article_ids: set[int] = set()
        ignored_article_ids: set[int] = set()

        for sport in target_sports:
            clusters = clusters_by_sport[sport]
            summaries = summaries_by_sport[sport]
            meta = SPORT_MAP[sport]
            sport_used_ids: set[int] = set()

            event_items: list[dict[str, Any]] = []
            for cluster, summary_md in zip(clusters, summaries, strict=True):
                art_ids = [int(a["id"]) for a in cluster.articles]
                sport_used_ids.update(art_ids)
                used_article_ids.update(art_ids)

                sources = []
                seen_urls: set[str] = set()
                for art in cluster.articles:
                    url = art["canonical_url"]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    sources.append(
                        {
                            "title": art["title"],
                            "source_name": art["source_name"],
                            "url": url,
                            "published_at": (
                                art["published_at"].isoformat() if art.get("published_at") else None
                            ),
                        }
                    )

                parent_ref = None
                parent_event_id = None
                if cluster.parent_event:
                    parent_event_id = int(cluster.parent_event["id"])
                    parent_ref = {
                        "id": parent_event_id,
                        "report_date": str(cluster.parent_event["report_date"]),
                        "title": cluster.parent_event["title"],
                    }

                event_items.append(
                    {
                        "id": None,
                        "title": cluster.title,
                        "importance": cluster.importance,
                        "summary_md": summary_md,
                        "parent_event": parent_ref,
                        "sources": sources,
                    }
                )
                events_to_save.append(
                    {
                        "sport": sport,
                        "title": cluster.title,
                        "importance": cluster.importance,
                        "summary_md": summary_md,
                        "article_ids": art_ids,
                        "parent_event_id": parent_event_id,
                    }
                )

            if event_items:
                sections.append(
                    {
                        "sport": sport,
                        "sport_name": meta.name,
                        "badge": meta.badge,
                        "events": event_items,
                    }
                )

            for art in pending_by_sport[sport]:
                aid = int(art["id"])
                if aid not in sport_used_ids:
                    ignored_article_ids.add(aid)

        # 5. Cross-sport overview bullets
        overview_bullets = await generate_overview(chat_client, sections) if sections else []
        stats["llm_usage"] = chat_client.usage.as_dict()

    report_json: dict[str, Any] = {
        "report_date": report_date,
        "generated_at": now.isoformat(),
        "timezone": now.tzname() or effective_settings.timezone,
        "llm_model": effective_model,
        "overview_bullets": overview_bullets,
        "sections": sections,
        "counts": {
            "sports": len(sections),
            "events": len(events_to_save),
            "high_events": sum(1 for e in events_to_save if e["importance"] == "high"),
            "articles_used": len(used_article_ids),
            "articles_ignored": len(ignored_article_ids),
        },
    }

    if not dry_run and (events_to_save or ignored_article_ids):
        # Embed generated events so future days can recall them via pgvector
        if events_to_save:
            async with EmbedClient(
                base_url=effective_settings.embed_base_url,
                model=effective_settings.embed_model,
                api_key=effective_settings.resolved_embed_api_key(),
                dim=effective_settings.embed_dim,
            ) as embed_client:
                ev_texts = [
                    format_event_for_embed(e["title"], e["summary_md"]) for e in events_to_save
                ]
                ev_vecs = await embed_client.embed(ev_texts)
                for ev, vec in zip(events_to_save, ev_vecs, strict=True):
                    ev["embedding"] = vec
                stats["event_embed_usage"] = embed_client.usage.as_dict()

        await asyncio.to_thread(
            commit_report_run,
            effective_settings.spnews_database_url,
            report_date,
            overview_bullets,
            report_json,
            events_to_save,
            sorted(used_article_ids),
            sorted(ignored_article_ids),
        )
        stats["committed"] = True
    else:
        stats["committed"] = False

    return report_json, stats


async def run_full_pipeline(
    settings: Settings,
    sports: list[str] | None = None,
    *,
    dry_run: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run init_db -> ingest+embed -> generate with runs table tracking."""
    await asyncio.to_thread(init_db, settings)
    run_id = None if dry_run else await asyncio.to_thread(start_run, settings.spnews_database_url)
    combined_stats: dict[str, Any] = {}
    try:
        stage1 = await run_ingest_and_embed(settings, sports)
        combined_stats.update(stage1)
        report_json, stage2 = await run_generate(settings, sports, dry_run=dry_run)
        combined_stats["generate"] = stage2
        if run_id is not None:
            await asyncio.to_thread(
                finish_run, settings.spnews_database_url, run_id, "success", combined_stats
            )
        return report_json, combined_stats
    except Exception as exc:
        if run_id is not None:
            await asyncio.to_thread(
                finish_run,
                settings.spnews_database_url,
                run_id,
                "failed",
                combined_stats,
                str(exc),
            )
        raise
