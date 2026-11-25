# ai-sports-news (`spnews`)

公开体育新闻日报自动化系统：多源异步 RSS 抓取与规则降噪、OpenRouter `qwen/qwen3-embedding-8b` 向量化、PostgreSQL 18 + pgvector 混合聚类与 14 天跨天记忆、按需正文提取（`trafilatura` + ESPN JSON）、在线 LLM 并发撰写中文日报，并生成静态站点、JSON 接口与 RSS 2.0 订阅源托管至 `https://sports.yhao.dev`。

## 覆盖运动

- 棒球 (MLB)
- 橄榄球 (NFL)
- F1 赛车
- 足球
- 篮球 (NBA)

## 架构概览

1. **Ingest (`ingest.py`)**：`httpx` 并发抓 RSS、URL 规范化去追踪参数、直读 RSS 内嵌正文、确定性规则拦截投注/视频/播客/直播流噪音（审计记录 `filter_reason`）。
2. **Embed (`embed.py`)**：OpenRouter `qwen/qwen3-embedding-8b`（MRL 1024 维 + L2 归一化）写入 PostgreSQL `vector(1024)`。
3. **Hybrid Cluster (`cluster.py`)**：平均连接余弦微聚类 + pgvector 14 天历史事件语义召回 + 在线 LLM Structured Outputs 精排（强 Schema 校验，无静默降级）。
4. **Enrich & Summarize (`enrich.py`, `summarize.py`)**：仅对入选事件代表文章按需提取正文（RSS `content` → ESPN 公开 JSON → `trafilatura` 并落库缓存），注入精确 14 天日历表，并发撰写中文事件与跨运动头版要点。
5. **Static Site & RSS (`site.py`)**：Jinja2 + 原生 CSS/JS 渲染 `dist/`（首页、单日固定链接、归档与搜索、`rss.xml`、`data/*.json`），经 Cloudflare Pages 发布。

## 快速开始

```bash
uv sync
cp .env.example .env   # 填入 SPNEWS_DATABASE_URL / DEEPSEEK_API_KEY / OPENROUTER_API_KEY
uv run spnews init-db
uv run spnews run
```

## 常用命令

```bash
# 仅抓取并向量化（不生成日报）
uv run spnews ingest

# 干跑生成，方便同一批数据对比不同模型（不修改 articles/events/reports 状态）
uv run spnews generate --dry-run -o preview_ds.json --preview-dir preview_ds
uv run spnews generate --dry-run \
  --llm-base-url https://openrouter.ai/api/v1 \
  --llm-model <openrouter-model-id> \
  -o preview_or.json --preview-dir preview_or

# 从数据库重建静态站与 rss.xml
uv run spnews build -o dist

# 全流程并部署到 Cloudflare Pages
uv run spnews run --deploy --cf-project spnews

# 查看数据库统计与近期运行记录
uv run spnews status

# 运行单元测试与代码检查
uv run pytest
uv run ruff check src tests
```

## 许可证

[MIT License](LICENSE)
