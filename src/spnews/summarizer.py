"""LLM-based article summarization per event cluster."""

from __future__ import annotations

from .llm import chat

_STYLE_GUIDE = """\
写作风格要求：
- 以中文为主体撰写，保持客观新闻风格
- 人名直接使用英文（如 Russell、Hamilton），仅对知名度极高的人物首次出现时加中文注释（如"Ohtani（大谷翔平）"）
- 队名首次出现用"中文 (English)"，后续直接用英文简称或中文简称
- 联赛/赛事缩写（NFL、MLB、WBC、F1）无需翻译
- 仅对核心数据（比分、金额、合同年限、排名、伤病时间等）用 **加粗**；年份(2026等)、序数词(第一/首次等)、日期不加粗
- 如涉及多笔签约/交易，用列表而非长段落
- 严禁编造报道中没有的信息，不得推测报道未提及的后续影响或假设性场景
- 禁止为凑篇幅而重复已述内容——但须确保至少覆盖事件的核心事实，不要仅因来源数量少就省略关键信息"""


def summarize_event(event_name: str, articles: list[dict],
                    importance: str, report_date: str = "",
                    previous_coverage: str | None = None) -> str:
    """Summarize a cluster of articles about one event. Returns markdown text."""
    sources_block = ""
    for art in articles:
        sources_block += (
            f"- 标题: {art['title']}\n"
            f"  来源: {art['source_name']}\n"
            f"  摘要: {art['summary'][:500]}\n"
            f"  链接: {art['link']}\n\n"
        )

    n_sources = len(articles)
    if importance == "high":
        if n_sources >= 5:
            detail = "请根据信息量写 2-3 段深入总结（背景、细节、影响），信息不足时不必凑段数。"
        elif n_sources >= 2:
            detail = "请写 1-2 段总结核心事实与背景，不要凑段数。"
        else:
            detail = "信息来源有限，请用 1 段（至少 3-4 句）准确总结核心内容，不要推测。"
    elif importance == "medium":
        if n_sources >= 3:
            detail = "请写 1 段（3-5 句）总结核心事实与背景，可体现不同来源的角度。"
        else:
            detail = "请写 1 段（2-4 句）概述核心事实与背景，不要推测。"
    else:
        detail = "请用 2-3 句话概述核心内容。"

    date_hint = ""
    if report_date:
        date_hint = (
            f"\n今天日期: {report_date}。"
            '请将"周五""昨天"等相对时间转换为具体日期, 如"3月12日(周五)"。'
        )

    memory_hint = ""
    if previous_coverage:
        memory_hint = (
            f"\n\n此事件此前已有报道，以下是之前的摘要（请基于此写后续进展，"
            f"避免重复已有内容，可用\"此前报道...\"等自然衔接语言）：\n{previous_coverage}"
        )

    prompt = f"""你是一个面向双语读者的体育新闻编辑。请根据以下报道总结此事件。

事件：{event_name}
{detail}{date_hint}{memory_hint}

相关报道：
{sources_block}

{_STYLE_GUIDE}
不要输出标题，直接输出正文。"""

    return chat(prompt)


def generate_overview(sport_summaries: dict[str, str]) -> str:
    """Generate a brief bullet-point overview across all sports."""
    combined = ""
    for sport_name, content in sport_summaries.items():
        combined += f"### {sport_name}\n{content}\n\n"

    n = len(sport_summaries)
    n_min = max(n, 5)
    n_max = n * 2

    prompt = f"""你是体育新闻编辑。以下是今日各运动的新闻汇总。
请输出 {n_min}-{n_max} 条 bullet point 摘要，每条一句话，每种运动至少覆盖 1 条，概括最值得关注的事件。

{combined}

{_STYLE_GUIDE}
格式：直接输出 markdown 无序列表（- 开头），不要加标题或前缀。"""

    return chat(prompt)



