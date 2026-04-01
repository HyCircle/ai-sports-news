"""LLM-based news clustering and importance ranking."""

from __future__ import annotations

import json

from .llm import chat


def cluster_articles(articles: list[dict], sport_name: str,
                     recent_events: list[dict] | None = None) -> list[dict]:
    """Cluster articles into events using LLM, return ranked event groups.

    Returns list of:
        {"event": str, "importance": "high"|"medium"|"low",
         "article_indices": [int], "related_previous_event": str|None}
    """
    if not articles:
        return []

    # Build article list for the prompt
    article_list = ""
    for i, art in enumerate(articles):
        article_list += f"[{i}] {art['title']}\n    {art['summary'][:200]}\n"

    # Build recent events context
    memory_block = ""
    if recent_events:
        memory_block = "\n\n--- 近期已报道事件（供参考，避免重复） ---\n"
        for ev in recent_events:
            memory_block += (
                f"- [{ev['report_date']}] {ev['event_name']} ({ev['importance']})\n"
                f"  {ev['summary_text'][:150]}\n"
            )
        memory_block += (
            "\n如果新文章是某个近期已报道事件的后续进展，请在该事件的 "
            "related_previous_event 字段填写对应的事件名称（精确匹配上方列表）。"
            "如果是全新事件，该字段留 null。\n"
        )

    prompt = f"""你是一个体育新闻编辑。下面是最近的{sport_name}新闻文章列表。

请完成以下任务：
1. 将这些文章按照它们报道的事件进行聚类（多篇文章可能报道同一事件）
    - 可忽略明显无效或信息价值很低的条目（如视频/播客预告、纯导流链接、信息重复且无新增）
2. 为每个事件写一个简短的中文事件名称
3. 按重要性排序，标记重要性级别：
   - high: 重大事件（如重要比赛结果、重大交易、伤病等），需要详细报道
   - medium: 一般事件，简要报道即可
   - low: 次要事件，仅需提及
4. 控制事件数量：总事件数绝对少于15个，尽量不超过10个，优先合并同主题的零散报道

文章列表：
{article_list}
{memory_block}
请严格以如下JSON格式回复，不要输出其他内容：
[
  {{"event": "事件名称", "importance": "high/medium/low", "article_indices": [0, 3, 5], "related_previous_event": null}},
  ...
]

注意：
- 不需要覆盖每一篇文章，被忽略的条目不要出现在 article_indices 中
- article_indices 是上面文章的编号
- 按重要性从高到低排序
- 输出事件总数不超过15个
- related_previous_event: 如果该事件与近期报道直接相关，填写对应事件名称；否则填 null"""

    resp = chat(prompt)

    # Parse JSON from response (handle markdown code blocks)
    text = resp.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    try:
        clusters = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: put all articles in one cluster
        print("  [WARN] Failed to parse clustering response, using fallback")
        clusters = [{"event": f"{sport_name}综合新闻", "importance": "medium",
                      "article_indices": list(range(len(articles)))}]

    return clusters
