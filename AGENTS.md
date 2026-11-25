# AGENTS.md — ai-sports-news

> 每次工作前先读 `.workflow/kit/discipline.md`（六条常驻纪律 + 脊椎）。

## 项目定位与技术栈

公开体育新闻日报自动化系统（托管于 `https://sports.yhao.dev`）：
- **Python 3.12 + uv**（单一工具链，无 Node 构建依赖）
- **PostgreSQL 18 + pgvector**（独立库 `spnews`，Mac Mini 常驻）
- **采集与正文**：`httpx` (async) + `feedparser` + `trafilatura`（按需抽取入选文章正文）
- **向量化与记忆**：OpenRouter `qwen/qwen3-embedding-8b`（MRL 1024 维 + L2 归一化）
- **聚类与撰写**：OpenAI-compatible 在线模型（默认 DeepSeek `deepseek-flash`，可切换 OpenRouter 模型做对比）
- **站点与发布**：Jinja2 + 原生 CSS/JS 静态构建至 `dist/`（含 `rss.xml` 与 `data/*.json`），经 Cloudflare Pages 发布

## 常用命令

```bash
uv sync                          # 同步依赖
uv run pytest                    # 运行确定性单元测试
uv run ruff check src tests      # 代码检查
uv run spnews init-db            # 初始化 PG 表与扩展
uv run spnews run                # 全流程：抓取 → 向量化 → 聚类撰写 → 构建站点
uv run spnews generate --dry-run # 仅跑生成不改 DB 状态（支持 A/B 对比模型）
uv run spnews build              # 从 DB 重建 dist/ 静态站与 rss.xml
uv run spnews status             # 查看数据库与近期运行指标
```

## 协作与安全约定

- 秘钥与连接串仅存 `.env`，绝不写入代码或提交。
- 确定性逻辑（URL 规范化、噪音过滤、凝聚微聚类、Schema 校验、静态站与 RSS 生成）必须配不依赖外部 API 的单元测试。
- 架构与模块边界见 `.workflow/architecture.md`。
