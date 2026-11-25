"""Async structured event summarization, deterministic validation, and cross-sport overview."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .cluster import FinalEventCluster
from .enrich import clean_extracted_body
from .llm import ChatClient

logger = logging.getLogger("spnews.summarize")

_WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

_ZH_DATE_SPACE_RE = re.compile(r"(\d{1,2})\s+月\s+(\d{1,2})\s+日")
_HYBRID_DOLLAR_ZH_RE = re.compile(r"\$(\d+(?:\.\d+)?)\s*([亿万])(?!美元)")
_STRAIGHT_QUOTE_RE = re.compile(r'"([^"\n]{1,60})"')
_REVERSED_SPLIT_RE = re.compile(r"(\d+)\s*(投|传|罚)\s*(\d+)\s*中")
_META_LEAK_RE = re.compile(r"(素材显示|报道素材|根据素材|上述素材)")

_STYLE_GUIDE = """\
写作规范（标题与正文必须严格统一）：
1. **人名一致性**：高知名球星与中文体育媒体通用译名用中文（如 詹姆斯、哈登、维斯塔潘、汉密尔顿、凯恩、罗杰斯、波切蒂诺）；其余球员/教练/新秀统一用英文原名（如 Tarik Skubal、Alec Bohm、Trinity Rodman），绝不对英文名做字面意译。**标题与正文必须使用完全一致的人名写法**（严禁标题写中文而正文只写英文）；标题为纯文本，不要在 `title` 中使用 `**` 加粗。
2. **队名与赛事**：队名用中文常用名，正文首次出现可按需括注英文（如 纽约大都会 (New York Mets)），不反向写“English (中文)”；赛事缩写（NBA、NFL、MLB、F1、EPL 等）保持英文。
3. **金额统一中文自然读法**：如 **4.5亿美元**、**8000万美元**、**100亿欧元**、**62.7万英镑**；严禁混用 $450 million、$1.2亿 或 €10B。
4. **准确体育术语与数据语序**：
   - lockout→停摆；bench→贬为替补；release/waive→裁掉；practice squad→训练队；first-team reps→主力组合练；Pro Ref→英格兰裁判公司 (PGMOL)。
   - 投篮/传球/罚球命中率必须严格用中文语序“出手数在前、命中数在后”（如 15-of-26 必须写作 **26投15中**，严禁写成 15投26中）。
5. **加粗克制**：仅对核心数据（比分、金额、合同年限、排名、关键统计、伤缺时长）用 **加粗**；日期、年份、序数词不加粗。
6. **严守主题边界与事实纪律**：
   - 若某篇报道是多队综合汇总稿（如全联盟伤病报告），**只提取与本事件主题直接相关的内容**，绝不顺带写入其他球队动态。
   - 严禁写入电视台直播预告、博彩盘口/赔率，严禁出现“素材显示/报道素材”等措辞。
   - 严禁编造原文未提及的犯规性质（严格区分点球与任意球）、比赛分钟数或身份；仅含标题/短摘时如实写简短事实，不脑补背景。"""


class EventSummaryOutput(BaseModel):
    title: str = Field(min_length=4, max_length=42)
    lead: str = Field(min_length=12, max_length=220)
    body_blocks: list[str] = Field(min_length=1, max_length=6)

    def to_markdown(self) -> str:
        """Assemble lead + body_blocks into clean Markdown paragraphs & bullet lists."""
        lead_clean = normalize_summary_text(self.lead.strip())
        parts: list[str] = [lead_clean] if lead_clean else []

        bullet_buf: list[str] = []
        for raw in self.body_blocks:
            block = normalize_summary_text(raw.strip())
            if not block:
                continue
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if all(ln.startswith(("- ", "* ", "• ")) for ln in lines):
                for ln in lines:
                    bullet_buf.append("- " + ln[2:].strip())
            else:
                if bullet_buf:
                    parts.append("\n".join(bullet_buf))
                    bullet_buf.clear()
                parts.append(block)
        if bullet_buf:
            parts.append("\n".join(bullet_buf))
        return "\n\n".join(parts)


class OverviewOutput(BaseModel):
    bullets: list[str] = Field(min_length=1, max_length=12)


def normalize_summary_text(text: str) -> str:
    """Deterministically normalize punctuation, date spacing, and hybrid currency glitches."""
    if not text:
        return ""
    out = _ZH_DATE_SPACE_RE.sub(r"\1月\2日", text)
    out = _HYBRID_DOLLAR_ZH_RE.sub(r"\1\2美元", out)
    # Replace ASCII straight quotes around short quoted phrases with Chinese curly quotes
    # (skipping Markdown link syntax or URLs)
    def _quote_sub(m: re.Match[str]) -> str:
        inner = m.group(1)
        if "http://" in inner or "https://" in inner or "=" in inner:
            return m.group(0)
        return f"“{inner}”"

    out = _STRAIGHT_QUOTE_RE.sub(_quote_sub, out)
    return out


def find_factual_glitches(text: str) -> list[str]:
    """Deterministically detect obvious numerical/meta-text errors before publishing."""
    issues: list[str] = []
    for m in _REVERSED_SPLIT_RE.finditer(text):
        attempts, verb, makes = int(m.group(1)), m.group(2), int(m.group(3))
        if attempts < makes:
            issues.append(
                f"检测到倒置数据“{m.group(0)}”（{makes}大于{attempts}），应为“{makes}{verb}{attempts}中”"
            )
    for m in _META_LEAK_RE.finditer(text):
        issues.append(f"正文包含内部词“{m.group(0)}”，请改为自然新闻表述")
    return issues


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


def _pub_ts(art: dict[str, Any]) -> float:
    dt = art.get("published_at")
    return dt.timestamp() if dt is not None else 0.0


def _format_sources_block(articles: list[dict[str, Any]], tz: ZoneInfo) -> str:
    """Format up to 3 full-text articles (newest first) PLUS all remaining headlines/summaries.

    Guarantees breaking short wires are never silently truncated out of multi-article clusters.
    """
    with_body: list[dict[str, Any]] = []
    brief_only: list[dict[str, Any]] = []
    for art in sorted(articles, key=_pub_ts, reverse=True):
        body = clean_extracted_body(
            (
                art.get("enriched_body")
                or art.get("fetched_body")
                or art.get("content_from_rss")
                or ""
            ).strip()
        )
        if body and len(with_body) < 3:
            with_body.append({**art, "_clean_body": body})
        else:
            brief_only.append(art)

    blocks: list[str] = []
    idx = 1
    for art in with_body:
        pub_str = _format_pub_date(art.get("published_at"), tz)
        blocks.append(
            f"[{idx}] 标题: {art['title']}\n"
            f"    来源: {art['source_name']} | 发布时间: {pub_str}\n"
            f"    正文摘录:\n{art['_clean_body'][:2000]}"
        )
        idx += 1

    if brief_only:
        brief_lines = ["其余相关快讯/报道（按时间倒序，注意覆盖最新进展）："]
        for art in brief_only:
            pub_str = _format_pub_date(art.get("published_at"), tz)
            summary = clean_extracted_body((art.get("summary") or "").strip())
            line = f"[{idx}] ({pub_str} | {art['source_name']}) {art['title']}"
            if summary:
                line += f"\n    摘要: {summary[:240]}"
            brief_lines.append(line)
            idx += 1
        blocks.append("\n".join(brief_lines))

    return "\n\n".join(blocks)


def _detail_instruction(importance: str, has_full_text: bool) -> str:
    if not has_full_text:
        return (
            "来源仅含标题或简短摘要：lead 写 1 句核心事实，body_blocks 写 1 个短段（2–3 句），"
            "总计 80–150 字，切勿脑补背景。"
        )
    if importance == "high":
        return (
            "重大事件：lead 写 1 句精炼导语（25–55 字）；body_blocks 写 2–3 个清晰短块"
            "（每块 2–3 句，或使用 `- ` 列表呈现多方进展/关键数据），总计约 240–360 字。"
        )
    if importance == "medium":
        return (
            "常规重要事件：lead 写 1 句核心事实（25–55 字）；body_blocks 写 1–2 个短块"
            "（总计约 140–240 字）；若涉及 3 个及以上球员、伤病、交易或奖项，body_blocks 必须用 `- ` 无序列表。"
        )
    return "次要简讯：lead 写 1 句核心事实，body_blocks 写 1 个短块（2–3 句），总计约 80–140 字。"


async def summarize_event(
    chat_client: ChatClient,
    cluster: FinalEventCluster,
    calendar_ref: str,
    tz: ZoneInfo,
) -> tuple[str, str]:
    """Summarize one event cluster into finalized (title, summary_md) with glitch guard."""
    has_full_text = any(
        bool(a.get("enriched_body") or a.get("fetched_body") or a.get("content_from_rss"))
        for a in cluster.articles
    )
    detail = _detail_instruction(cluster.importance, has_full_text)
    sources_block = _format_sources_block(cluster.articles, tz)

    memory_block = ""
    if cluster.parent_event:
        pe = cluster.parent_event
        memory_block = (
            f"\n前情回顾（{pe['report_date']} 已报道：《{pe['title']}》）：\n"
            f"{pe['summary_md'][:400]}\n"
            "请聚焦今日新进展，用“此前报道……”自然衔接，避免重复旧内容。\n"
        )

    system = (
        "你是面向中文体育读者的资深新闻编辑，以事实严谨、译名地道、结构清晰克制著称。"
        "你必须严格输出合法 JSON。"
    )
    user = f"""请阅读以下一手报道并输出本事件的定稿标题与结构化中文摘要。

临时主题标签：{cluster.title}
重要度：{cluster.importance}
篇幅与结构：{detail}

{calendar_ref}
（文中提及日期或星期必须严格对照上方日历与各来源发布时间，并以美国中部时间 {tz.key} 为基准统一表述，避免同一场比赛因跨时区出现两个日期。）
{memory_block}
报道来源：
{sources_block}

{_STYLE_GUIDE}

严格输出如下 JSON（不要输出多余解释）：
{{
  "title": "6–26字简明中文定稿标题（与正文事实和人名严格一致）",
  "lead": "1句核心导语，交代最重要结果/进展与关键数据",
  "body_blocks": [
    "第一段补充关键细节或数据（2–3句）",
    "- 若涉及多笔交易/伤病/多人获奖，用连字符列表项"
  ]
}}"""

    out = await chat_client.chat_json(user, EventSummaryOutput, system=system, temperature=0.25)
    final_title = normalize_summary_text(out.title.replace("**", "").replace("*", "").strip())
    summary_md = out.to_markdown()

    glitches = find_factual_glitches(f"{final_title}\n{summary_md}")
    if glitches:
        logger.warning(
            "Factual/style glitch detected in '%s': %s; retrying once",
            final_title,
            "; ".join(glitches),
        )
        fix_prompt = (
            f"{user}\n\n"
            f"你上一次输出存在以下明确错误，请修正后重新输出完整 JSON：\n"
            + "\n".join(f"- {g}" for g in glitches)
        )
        out = await chat_client.chat_json(
            fix_prompt, EventSummaryOutput, system=system, temperature=0.15
        )
        final_title = normalize_summary_text(out.title.replace("**", "").replace("*", "").strip())
        summary_md = out.to_markdown()

    return final_title, summary_md


async def summarize_sport_clusters(
    chat_client: ChatClient,
    clusters: list[FinalEventCluster],
    calendar_ref: str,
    tz: ZoneInfo,
) -> list[tuple[str, str]]:
    """Concurrently summarize all clusters for one sport into (final_title, summary_md)."""
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
    """Generate structured cross-sport headline bullets aligned with finalized titles & style."""
    if not sections:
        return []

    parts: list[str] = []
    for sec in sections:
        parts.append(f"### {sec['sport_name']}")
        for ev in sec["events"]:
            tag = "[重大] " if ev["importance"] == "high" else ""
            lead = (ev["summary_md"].split("\n\n")[0] if ev.get("summary_md") else "")[:200]
            parts.append(f"- {tag}{ev['title']}：{lead}")
        parts.append("")

    n_sports = len(sections)
    n_min = max(n_sports, 5)
    n_max = min(max(n_sports * 2, 6), 8)

    system = "你是体育日报总编，负责提炼今日跨运动头版要点并输出严格 JSON。"
    user = f"""以下是今日各运动板块已定稿的事件标题与导语：

{chr(10).join(parts)}

请提炼 {n_min}–{n_max} 条今日头版要点：
- 每条 1 句话，涵盖核心主体与关键结果/数据（仅对核心比分、金额、关键统计用 **加粗**，日期/年份不加粗）。
- 每个有新闻的运动板块至少覆盖 1 条，优先挑选 [重大] 事件。
- 人名、队名、金额与术语严格与上方定稿内容保持一致（金额用中文自然读法，如 **4.5亿美元**），不新增未提及信息。

严格以如下 JSON 格式回复：
{{
  "bullets": [
    "第一条要点...",
    "第二条要点..."
  ]
}}"""

    out = await chat_client.chat_json(user, OverviewOutput, system=system, temperature=0.2)
    return [
        normalize_summary_text(b.strip().lstrip("-• ").strip())
        for b in out.bullets
        if b.strip()
    ]
