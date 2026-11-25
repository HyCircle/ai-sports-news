# Architecture — ai-sports-news (v2)

## 数据流与模块边界

```text
sources.py (源清单 / URL 规范化 / 噪音规则)
    ↓
ingest.py (async RSS 并发抓取 + 清洗入库)
    ↓
embed.py (OpenRouter qwen3-embedding-8b 批量向量化 → 1024d MRL L2)
    ↓
cluster.py (余弦平均连接微聚类 + pgvector 14 天记忆召回 + LLM Structured Outputs 精排)
    ↓
enrich.py (仅对入选事件代表文章补齐正文：RSS content / ESPN JSON / trafilatura)
    ↓
summarize.py (注入 14 天精确日期表 + 前情摘要，async 并发撰写事件与总览)
    ↓
pipeline.py (单事务闭环更新 articles/events/reports/runs)
    ↓
site.py (Jinja2 渲染 dist/: 首页 / 单日页 / 归档 / rss.xml / data/*.json)
```

## 核心数据模型（PostgreSQL 18 + pgvector）

- `articles`: RSS 文章去重（`canonical_url UNIQUE`）、状态机（`pending` → `used` / `ignored`；规则拦截直接写 `filtered` + `filter_reason`）、1024 维 `vector(1024)`、正文缓存 `fetched_body`。
- `events`: 日报结构化事件、`importance`、`article_ids INT[]`、跨天关联 `parent_event_id REFERENCES events(id)`、事件向量 `vector(1024)`。
- `reports`: 按 `report_date` 存储完整结构化 `report_json`（静态站与 RSS 的唯一真源）。
- `runs`: 每次流水线运行的起止时间、状态、分阶段统计指标（抓取/过滤/正文成功率/LLM token 与耗时）和错误信息。

## 关键不变量

1. **零静默最坏兜底**：聚类 JSON 或 Schema 校验在自动重试 1 次后仍失败时直接抛错中止，文章保持 `pending`，绝不将全量文章打包成“综合新闻”落库。
2. **向量空间一致性**：所有入库向量均为 `qwen/qwen3-embedding-8b` 前 1024 维切片并 L2 归一化（`float32`），跨模型不可混存同一列。
3. **正文按需抓取与缓存**：仅对最终入选事件的代表文章（每簇最多 3 篇）抓正文，并缓存到 `articles.fetched_body`，干跑/A/B 对比不重复抓网。
4. **单事务闭环**：报告生成完整成功后，才在一个 PG 事务中标记 `articles` 状态并写入 `events` / `reports`。
