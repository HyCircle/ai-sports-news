"""Async event summarization and cross-sport overview generation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .cluster import FinalEventCluster
from .llm import ChatClient

_WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

_STYLE_GUIDE = """\
写作规范：
- 以客观、精炼的中文体育新闻风格撰写。
- 人名直接使用英文原名（如 Russell、Hamilton）；仅对知名度极高的球星首次出现时附中文注释（如 Ohtani（大谷翔平）、LeBron James（詹姆斯））。
- 队名首次出现用“中文 (English)”格式（如“洛杉矶湖人 (Los Angeles Lakers)”），后续用简称。
- 联赛与赛事缩写（NFL、MLB、NBA、F1、UFC、EPL 等）保持英文。
- 仅对核心数据（比分、金额、合同年限、排名、关键统计、伤缺时长）使用 **加粗**；年份、日期、序数词不加粗。
- 金额直接写标准美元符号（如 $45.75 million 或 $1.4亿），不要做任何反斜杠转义或放进反引号。
- 涉及多笔签约/交易/伤病名单时使用无序列表（- 开头）。
- **严格忠于原文事实**：严禁编造来源中未提及的比分、年份、身份、主帅/解说职务或推测性影响；若来源仅包含标题或简短摘要，请如实写 2–3 句简洁准确的事实快讯，切勿强行扩写。"""


class OverviewOutput(BaseModel):
    bullets: list[str] = Field(min_length=1, max_length=12)


def build_calendar_reference(now: datetime, days: int = 14) -> str:
    """Build an exact date-to-weekday lookup table so the LLM never guesses weekdays."""
    lines = ["近两周精确日历（严禁推算错星期几）："]
    for offset in range(days):
        d = now - timedelta(days=offset)
        label = "今天" if offset == 0 else ("昨天" if offset == 1 else f"{offset}天前")
        wd = _WEEKDAY_ZH[d.weekday()]
        lines.append(f"- {d.strftime('%Y-%m-%d')}（{wd}，{label}）")
    return "\n".join(lines)


def _format_pub_date(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "未知时间"
    local = dt.astimezone(tz)
    return f"{local.strftime('%Y-%m-%d %H:%M')} ({_WEEKDAY_ZH[local.weekday()]})"


def _format_sources_block(articles: list[dict[str, Any]], tz: ZoneInfo) -> str:
    blocks: list[str] = []
    # Put articles with enriched full text first
    ordered = sorted(
        articles,
        key=lambda a: len(a.get("enriched_body") or a.get("fetched_body") or ""),
        reverse=True,
    )
    for idx, art in enumerate(ordered[:8], 1):
        body = (
            art.get("enriched_body")
            or art.get("fetched_body")
            or art.get("content_from_rss")
            or ""
        ).strip()
        summary = (art.get("summary") or "").strip()
        pub_str = _format_pub_date(art.get("published_at"), tz)

        lines = [
            f"[{idx}] 标题: {art['title']}",
            f"    来源: {art['source_name']} | 发布时间: {pub_str}",
        ]
        if body:
            lines.append(f"    正文摘录:\n{body[:2200]}")
        elif summary:
            lines.append(f"    摘要: {summary[:600]}")
        else:
            lines.append("    （仅标题可用，无正文）")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _detail_instruction(importance: str, has_full_text: bool, n_sources: int) -> str:
    if not has_full_text:
        return "当前来源仅含简短摘要或标题，请写 1 段紧凑准确的事实简报（2–4 句），只陈述明确给出的事实，不要脑补背景。"
    if importance == "high":
        if n_sources >= 3:
            return "重大事件且素材充足：请写 2 段结构清晰的总结（每段 3–5 句），覆盖核心结果、关键数据/经过、必要背景与后续动向。"
        return "重大事件：请写 1–2 段充实总结，覆盖核心结果、关键细节与明确提及的后续影响。"
    if importance == "medium":
        return "常规重要事件：请写 1 段清晰完整的总结（4–6 句），交代核心事实、关键人物/数据与背景。"
    return "次要动态：请用 1 段简洁摘要（2–4 句）讲清事件核心事实。"


async def summarize_event(
    chat_client: ChatClient,
    cluster: FinalEventCluster,
    calendar_ref: str,
    tz: ZoneInfo,
) -> str:
    """Summarize one event cluster into clean Markdown prose."""
    has_full_text = any(
        bool(a.get("enriched_body") or a.get("fetched_body") or a.get("content_from_rss"))
        for a in cluster.articles
    )
    detail = _detail_instruction(cluster.importance, has_full_text, len(cluster.articles))
    sources_block = _format_sources_block(cluster.articles, tz)

    memory_block = ""
    if cluster.parent_event:
        pe = cluster.parent_event
        memory_block = (
            f"\n前情回顾（{pe['report_date']} 已报道：《{pe['title']}》）：\n"
            f"{pe['summary_md'][:500]}\n"
            "请在此基础上聚焦今日新进展，用“此前报道……”等自然衔接，避免整段重复旧内容。\n"
        )

    system = "你是一位面向双语读者的专业体育新闻编辑，以事实准确、行文克制流畅著称。"
    user = f"""请根据以下一手报道素材，撰写本事件的中文摘要。

事件标题：{cluster.title}
重要度：{cluster.importance}
篇幅指引：{detail}

{calendar_ref}
（文中如需提及具体日期或星期，必须严格对照上方日历和各来源的发布时间，将“昨天/周五”等相对表述转为准确日期，如“11月24日（周二）”。）
{memory_block}
报道素材：
{sources_block}

{_STYLE_GUIDE}
直接输出正文 Markdown，不要重复输出事件标题。"""

    return await chat_client.chat_text(user, system=system, temperature=0.3)


async def summarize_sport_clusters(
    chat_client: ChatClient,
    clusters: list[FinalEventCluster],
    calendar_ref: str,
    tz: ZoneInfo,
) -> list[str]:
    """Concurrently summarize all clusters for one sport."""
    if not clusters:
        return []
    return list(
        await asyncio.gather(
            *(summarize_event(chat_client, c, calendar_ref, tz) for c in clusters)
        )
    )


async def generate_overview(
    chat_client: ChatClient,
    sections: list[dict[str, Any]],
) -> list[str]:
    """Generate structured cross-sport headline bullets."""
    if not sections:
        return []

    parts: list[str] = []
    for sec in sections:
        parts.append(f"### {sec['sport_name']}")
        for ev in sec["events"]:
            tag = "[重大] " if ev["importance"] == "high" else ""
            parts.append(f"- {tag}{ev['title']}：{ev['summary_md'][:260]}")
        parts.append("")

    n_sports = len(sections)
    n_min = max(n_sports, 5)
    n_max = min(max(n_sports * 2, 6), 10)

    system = "你是体育日报总编，负责提炼今日最值得关注的跨运动头版要点，并输出严格 JSON。"
    user = f"""以下是今日各运动板块的新闻事件摘要：

{chr(10).join(parts)}

请提炼 {n_min}–{n_max} 条今日头版要点：
- 每条 1 句话，涵盖核心主体与关键结果/数据（仅对核心比分、金额、关键统计用 **加粗**，日期/年份不加粗）。
- 每个有新闻的运动板块至少覆盖 1 条，优先挑 [重大] 事件。
- 严格忠于上述内容，不新增未提及信息。

严格以如下 JSON 格式回复：
{{
  "bullets": [
    "第一条要点...",
    "第二条要点..."
  ]
}}"""

    out = await chat_client.chat_json(user, OverviewOutput, system=system, temperature=0.2)
    return [b.strip().lstrip("-• ").strip() for b in out.bullets if b.strip()]
