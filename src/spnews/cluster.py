"""Hybrid clustering: vector average-linkage micro-clustering + pgvector memory + LLM refinement."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal
from zoneinfo import ZoneInfo

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


def enforce_high_quota(
    clusters: list[FinalEventCluster],
    max_high: int,
) -> list[FinalEventCluster]:
    """Deterministically enforce per-sport cap on high-importance events."""
    clusters.sort(key=lambda c: _IMPORTANCE_ORDER[c.importance])
    high_seen = 0
    for c in clusters:
        if c.importance == "high":
            high_seen += 1
            if high_seen > max_high:
                c.importance = "medium"
    return clusters


def _recall_memory_sync(
    dsn: str,
    sport: str,
    articles: list[dict[str, Any]],
    micro_clusters: list[list[int]],
    memory_days: int,
    min_similarity: float,
    exclude_report_date: str | None = None,
) -> tuple[dict[int, dict[str, Any]], dict[int, list[int]]]:
    """Query pgvector for recent historical events matching each micro-cluster centroid."""
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
            exclude_report_date=exclude_report_date,
        )
        if hits:
            cluster_hints[mc_id] = [int(h["id"]) for h in hits]
            for h in hits:
                eid = int(h["id"])
                if eid not in memory_by_id or h["similarity"] > memory_by_id[eid]["similarity"]:
                    memory_by_id[eid] = h
    return memory_by_id, cluster_hints


def _short_date(dt: Any, tz: ZoneInfo | None) -> str:
    if dt is None:
        return "??-??"
    if tz is not None and getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone(tz)
    return dt.strftime("%m-%d")


def _format_micro_clusters_prompt(
    articles: list[dict[str, Any]],
    micro_clusters: list[list[int]],
    cluster_hints: dict[int, list[int]],
    tz: ZoneInfo | None = None,
) -> str:
    lines: list[str] = []
    for mc_id, indices in enumerate(micro_clusters):
        hint_str = ""
        if mc_id in cluster_hints:
            hint_str = f" [向量相近历史事件ID: {cluster_hints[mc_id]}]"
        ordered = sorted(
            indices,
            key=lambda i: articles[i]["published_at"].timestamp()
            if articles[i].get("published_at") is not None
            else 0.0,
            reverse=True,
        )
        lines.append(f"[M{mc_id}] ({len(ordered)}篇){hint_str}")
        for idx in ordered[:6]:
            art = articles[idx]
            d_str = _short_date(art.get("published_at"), tz)
            snippet = (art.get("summary") or "")[:160]
            lines.append(f"  - [{d_str}] ({art['source_name']}) {art['title']}")
            if snippet:
                lines.append(f"    {snippet}")
        if len(ordered) > 6:
            lines.append(f"  - ... 其余 {len(ordered) - 6} 篇同源/相近报道")
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
    *,
    report_date: str | None = None,
    tz: ZoneInfo | None = None,
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
        report_date,
    )

    mc_block = _format_micro_clusters_prompt(articles, micro_clusters, cluster_hints, tz=tz)
    mem_block = _format_memory_prompt(memory_by_id)
    date_line = f"日报日期：{report_date}\n" if report_date else ""

    system = (
        "你是严谨的体育新闻总编。将语义预聚类后的候选微簇整理为当日事件清单，"
        "严格输出符合 Schema 的 JSON。"
    )
    user = f"""{date_line}以下是待整理的【{sport_name}】新闻候选微簇（共 {len(micro_clusters)} 个微簇，来自 {len(articles)} 篇文章）：

{mc_block}
{mem_block}

编排要求：
1. **合并同事件多角度**：同一具体比赛/分站赛/重磅官宣/同一场联盟会议的多角度报道，合并到同一事件（例如同一场 F1 分站赛的赛果与超车争议、同一场 FIFA 会议官宣多届主办权），不要拆成重复条目；但也不要把不同球队或互不相干的花絮硬凑成大杂烩。
2. **注意时间先后与过期内容**：对照每条文章前的 [MM-DD] 日期，忽略已过时的赛前前瞻/排位预告（若正赛结果已出），不要把冲突/事故发生前的旧采访误当成事后回应合并进来。
3. **剔除低价值杂讯**：预测/盘口/幻想体育、口水榜单/实力榜、纯视频/播客、无实质新进展的猜测文章直接忽略。
4. **临时主题标签**：写简明准确的中文主题标签（终稿标题会在读完全文后定稿）。
5. **严格控制重要度配额**：
   - `high`（每项运动 **最多 {settings.max_high_per_sport} 条**）：真正具有跨圈影响力的重磅交易/签约/解雇、冠军或焦点大赛结果、核心球星重伤、重大联盟规则或裁决；**单篇评论/猜测稿不标 `high`**。
   - `medium`：常规重要赛果、轮换/伤病更新、有实质进展的人事或赛场动态。
   - `low`：次要简讯。
6. **跨天连续性**：若为上方历史事件的直接新进展，填对应 `parent_event_id`；否则填 `null`。
7. **数量上限**：总事件数不超过 {settings.max_events_per_sport} 条，按重要度从高到低排列。

严格输出 JSON：
{{
  "events": [
    {{
      "title": "事件主题标签",
      "importance": "high",
      "micro_cluster_ids": [0, 2],
      "parent_event_id": null
    }}
  ]
}}

约束：`micro_cluster_ids` 仅含 0 到 {len(micro_clusters) - 1} 的整数且不可重复分配；`parent_event_id` 只能为 `null` 或上方真实历史事件 ID。"""

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

        # Keep cluster articles ordered newest-first for downstream enrichment & display
        cluster_articles.sort(
            key=lambda a: a["published_at"].timestamp()
            if a.get("published_at") is not None
            else 0.0,
            reverse=True,
        )

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

    final_clusters = enforce_high_quota(final_clusters, settings.max_high_per_sport)
    final_clusters = final_clusters[: settings.max_events_per_sport]

    stats = {
        "pending": len(articles),
        "micro_clusters": len(micro_clusters),
        "memory_hits": len(memory_by_id),
        "final_events": len(final_clusters),
    }
    return final_clusters, stats
