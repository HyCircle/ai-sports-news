"""Article and event vectorization using OpenRouter qwen/qwen3-embedding-8b."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

from .config import Settings
from .db import get_articles_needing_embed, save_article_embeddings
from .llm import EmbedClient

logger = logging.getLogger("spnews.embed")


def format_article_for_embed(article: dict[str, Any]) -> str:
    """Build a uniform-length text representation to avoid short-vs-long cosine skew."""
    title = (article.get("title") or "").strip()
    snippet = (article.get("summary") or "").strip()
    if not snippet:
        snippet = (article.get("content_from_rss") or "").strip()[:350]
    else:
        snippet = snippet[:350]
    return f"{title}\n{snippet}".strip() if snippet else title


def format_event_for_embed(event_title: str, summary_md: str) -> str:
    """Build a compact event representation for 14-day historical memory recall."""
    return f"{event_title}\n{summary_md[:450]}".strip()


async def embed_pending_articles(
    settings: Settings,
    embed_client: EmbedClient,
    sports: list[str] | None = None,
) -> int:
    """Vectorize all pending articles missing an embedding and save to PostgreSQL."""
    rows = await asyncio.to_thread(
        get_articles_needing_embed, settings.spnews_database_url, sports
    )
    if not rows:
        return 0
    texts = [format_article_for_embed(r) for r in rows]
    vectors = await embed_client.embed(texts)
    pairs: list[tuple[int, np.ndarray]] = [
        (int(row["id"]), vec) for row, vec in zip(rows, vectors, strict=True)
    ]
    await asyncio.to_thread(save_article_embeddings, settings.spnews_database_url, pairs)
    logger.info("Embedded %d pending articles", len(pairs))
    return len(pairs)
