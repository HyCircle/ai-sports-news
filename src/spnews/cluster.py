"""Hybrid clustering: vector average-linkage micro-clustering + pgvector memory + LLM refinement."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from .config import Settings
from .db import search_similar_events
from .llm import ChatClient

logger = logging.getLogger("spnews.cluster")

_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


class ClusterDecision(BaseModel):
    title: str = Field(min_length=2, max_length=60)
    importance: Literal["high", "medium", "low"]
    micro_cluster_ids: list[int] = Field(min_length=1)
    parent_event_id: int | None = None


class ClusteringOutput(BaseModel):
    events: list[ClusterDecision]


@dataclass
class FinalEventCluster:
    title: str
    importance: Literal["high", "medium", "low"]
    articles: list[dict[str, Any]]
    parent_event: dict[str, Any] | None = None


def _to_float32(vec: Any) -> np.ndarray:
    if hasattr(vec, "to_numpy"):
        return np.asarray(vec.to_numpy(), dtype=np.float32)
    return np.asarray(vec, dtype=np.float32)


def centroid_vector(vectors: list[np.ndarray]) -> np.ndarray:
    """Compute the L2-normalized centroid of a non-empty list of vectors."""
    stacked = np.vstack([_to_float32(v) for v in vectors])
    mean = stacked.mean(axis=0)
    norm = float(np.linalg.norm(mean))
    return mean / norm if norm > 0 else mean


def micro_cluster_embeddings(
    embeddings: list[np.ndarray | None],
    threshold: float = 0.72,
) -> list[list[int]]:
    """Deterministic average-linkage agglomerative clustering on cosine similarity.

    Avoids single-linkage chaining while keeping high precision (preferring
    splitting over falsely merging distinct stories about the same team).
    Returns groups of indices into the input list, ordered by size desc then first index asc.
    """
    n = len(embeddings)
    if n == 0:
        return []

    valid_idx = [i for i, v in enumerate(embeddings) if v is not None]
    missing_idx = [i for i, v in enumerate(embeddings) if v is None]

    groups: list[list[int]] = []
    if valid_idx:
        mat = np.vstack([_to_float32(embeddings[i]) for i in valid_idx])
        # Ensure L2 normalization for exact cosine similarity via dot product
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        mat = mat / norms
        sim = mat @ mat.T  # shape (m, m)

        clusters: list[list[int]] = [[k] for k in range(len(valid_idx))]
        while len(clusters) > 1:
            best_sim = -1.0
            best_pair = (-1, -1)
            for a in range(len(clusters)):
                idx_a = clusters[a]
                for b in range(a + 1, len(clusters)):
                    idx_b = clusters[b]
                    avg_s = float(sim[np.ix_(idx_a, idx_b)].mean())
                    if avg_s > best_sim:
                        best_sim = avg_s
                        best_pair = (a, b)
            if best_sim < threshold:
                break
            a, b = best_pair
            clusters[a] = clusters[a] + clusters[b]
            clusters.pop(b)

        for c in clusters:
            groups.append(sorted(valid_idx[k] for k in c))

    for i in missing_idx:
        groups.append([i])

    groups.sort(key=lambda g: (-len(g), g[0]))
    return groups


def _recall_memory_sync(
    dsn: str,
    sport: str,
    articles: list[dict[str, Any]],
    micro_clusters: list[list[int]],
    memory_days: int,
    min_similarity: float,
) -> tuple[dict[int, dict[str, Any]], dict[int, list[int]]]:
    """Query pgvector for recent historical events matching each micro-cluster centroid.

    Returns:
        memory_by_id: {event_id: event_row}
        cluster_hints: {micro_cluster_id: [matched_event_ids]}
    """
    memory_by_id: dict[int, dict[str, Any]] = {}
    cluster_hints: dict[int, list[int]] = {}
    for mc_id, indices in enumerate(micro_clusters):
        vecs = [articles[i]["embedding"] for i in indices if articles[i].get("embedding") is not None]
        if not vecs:
            continue
        centroid = centroid_vector(vecs)
        hits = search_similar_events(
            dsn,
            sport=sport,
            query_vec=centroid,
            days=memory_days,
            limit=3,
            min_similarity=min_similarity,
        )
        if hits:
            cluster_hints[mc_id] = [int(h["id"]) for h in hits]
            for h in hits:
                eid = int(h["id"])
                if eid not in memory_by_id or h["similarity"] > memory_by_id[eid]["similarity"]:
                    memory_by_id[eid] = h
    return memory_by_id, cluster_hints


def _format_micro_clusters_prompt(
    articles: list[dict[str, Any]],
    micro_clusters: list[list[int]],
    cluster_hints: dict[int, list[int]],
) -> str:
    lines: list[str] = []
    for mc_id, indices in enumerate(micro_clusters):
        hint_str = ""
        if mc_id in cluster_hints:
            hint_str = f" [向量相近历史事件ID: {cluster_hints[mc_id]}]"
        lines.append(f"[M{mc_id}] ({len(indices)}篇){hint_str}")
        for idx in indices[:6]:
            art = articles[idx]
            snippet = (art.get("summary") or "")[:180]
            lines.append(f"  - ({art['source_name']}) {art['title']}")
            if snippet:
                lines.append(f"    {snippet}")
        if len(indices) > 6:
            lines.append(f"  - ... 其余 {len(indices) - 6} 篇同源/相近报道")
    return "\n".join(lines)


def _format_memory_prompt(memory_by_id: dict[int, dict[str, Any]]) -> str:
    if not memory_by_id:
        return ""
    lines = ["\n--- 近期历史已报道事件（通过向量召回，用于判断是否为后续进展） ---"]
    for eid, ev in sorted(
        memory_by_id.items(),
        key=lambda kv: (str(kv[1]["report_date"]), kv[0]),
        reverse=True,
    ):
        lines.append(
            f"- [ID={eid}] ({ev['report_date']}) {ev['title']} ({ev['importance']})\n"
            f"  {ev['summary_md'][:180]}"
        )
    return "\n".join(lines)


async def cluster_sport_articles(
    settings: Settings,
    chat_client: ChatClient,
    sport: str,
    sport_name: str,
    articles: list[dict[str, Any]],
) -> tuple[list[FinalEventCluster], dict[str, Any]]:
    """Run hybrid vector + LLM clustering for one sport."""
    if not articles:
        return [], {"pending": 0, "micro_clusters": 0, "memory_hits": 0, "final_events": 0}

    embeddings = [art.get("embedding") for art in articles]
    micro_clusters = micro_cluster_embeddings(
        embeddings, threshold=settings.micro_cluster_threshold
    )

    memory_by_id, cluster_hints = await asyncio.to_thread(
        _recall_memory_sync,
        settings.spnews_database_url,
        sport,
        articles,
        micro_clusters,
        settings.memory_days,
        settings.memory_sim_threshold,
    )

    mc_block = _format_micro_clusters_prompt(articles, micro_clusters, cluster_hints)
    mem_block = _format_memory_prompt(memory_by_id)

    system = (
        "你是一位严谨的体育新闻总编。你需要把按语义预聚类后的候选微簇整理成当日日报事件清单，"
        "并严格输出符合要求的 JSON 对象。"
    )
    user = f"""以下是今天待整理的【{sport_name}】新闻候选微簇（共 {len(micro_clusters)} 个微簇，来自 {len(articles)} 篇文章）：

{mc_block}
{mem_block}

请完成以下编排任务：
1. **合并同事件微簇**：若多个微簇明显报道同一具体事件，将它们的编号合并到同一条事件中。不要把“同队但完全不同的事件”或“整个赛事周末互不相干的 20 条花絮”强行揉成一个大杂烩。
2. **剔除低价值杂讯**：明显属于投注/赔率/幻想体育推荐、纯视频或播客预告、无实质信息的口水榜单或与本运动无关的条目，直接忽略（不要出现在结果中）。
3. **写简明中文事件标题**（6–28 字，准确具体）。
4. **标注重要度**：
   - `high`：重大赛果、季后赛/争冠关键战、重磅交易/签约/解雇、核心球星重大伤病、重大规则/联盟变故。
   - `medium`：常规重要赛果、轮换/伤病更新、有实质内容的人事或赛场动态。
   - `low`：次要动态或简讯。
5. **跨天连续性关联**：如果某事件是上方历史事件列表的直接后续进展，将 `parent_event_id` 设为对应历史事件的整数 ID；若为全新事件则填 `null`。
6. **数量控制**：总事件数不超过 {settings.max_events_per_sport} 条，按重要度从高到低排序。

请严格输出如下 JSON 对象：
{{
  "events": [
    {{
      "title": "中文事件标题",
      "importance": "high",
      "micro_cluster_ids": [0, 2],
      "parent_event_id": null
    }}
  ]
}}

约束：
- `micro_cluster_ids` 中的整数必须在 0 到 {len(micro_clusters) - 1} 之间，且每个微簇最多归属 1 个事件。
- `parent_event_id` 只能是 `null` 或上方历史事件列表里真实出现的整数 ID。"""

    output = await chat_client.chat_json(user, ClusteringOutput, system=system, temperature=0.1)

    valid_mc_range = range(len(micro_clusters))
    claimed_mcs: set[int] = set()
    final_clusters: list[FinalEventCluster] = []

    for decision in output.events:
        usable_mcs: list[int] = []
        for mc_id in decision.micro_cluster_ids:
            if mc_id not in valid_mc_range:
                logger.warning("[%s] Ignoring out-of-range micro_cluster_id=%s", sport, mc_id)
                continue
            if mc_id in claimed_mcs:
                logger.warning("[%s] Ignoring duplicate micro_cluster_id=%s", sport, mc_id)
                continue
            claimed_mcs.add(mc_id)
            usable_mcs.append(mc_id)

        if not usable_mcs:
            continue

        cluster_articles: list[dict[str, Any]] = []
        for mc_id in usable_mcs:
            for art_idx in micro_clusters[mc_id]:
                cluster_articles.append(articles[art_idx])

        parent_ev = None
        if decision.parent_event_id is not None:
            parent_ev = memory_by_id.get(decision.parent_event_id)
            if parent_ev is None:
                logger.warning(
                    "[%s] LLM referenced unknown parent_event_id=%s, clearing",
                    sport,
                    decision.parent_event_id,
                )

        final_clusters.append(
            FinalEventCluster(
                title=decision.title.strip(),
                importance=decision.importance,
                articles=cluster_articles,
                parent_event=parent_ev,
            )
        )

    final_clusters.sort(key=lambda c: _IMPORTANCE_ORDER[c.importance])
    final_clusters = final_clusters[: settings.max_events_per_sport]

    stats = {
        "pending": len(articles),
        "micro_clusters": len(micro_clusters),
        "memory_hits": len(memory_by_id),
        "final_events": len(final_clusters),
    }
    return final_clusters, stats
