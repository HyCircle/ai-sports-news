# ai-sports-news

轻量级体育资讯自动化工具：抓取 RSS 新闻，通过 SQLite 数据库去重与状态管理，按事件聚类，调用本地 LLM 生成中文 Markdown 日报，并自动维护 GitHub Pages 首页与归档列表。

日报首页: [https://hycircle.github.io/ai-sports-news/](https://hycircle.github.io/ai-sports-news/)

## 当前支持

- 橄榄球 (NFL)
- 棒球 (MLB)
- F1 赛车
- 足球
- 篮球 (NBA)

## 功能概览

- 多源 RSS 抓取（按运动拆分）
- **RSS 增量抓取策略**：仅导入最近 N 天（默认 7 天）的新闻，避免数据库无限膨胀
- SQLite 数据库驱动的去重与状态管理（不再依赖时间窗口）
- 增量抓取：INSERT OR IGNORE 自动去重，即使多天运行也不会遗漏
- **待办筛选与状态追踪**：
  - 处理 `report_date IS NULL` 的所有文章。
  - **自动清理被忽略条目**：LLM 在聚类时未选中的文章也会被标记为已处理（used=0），防止陈旧新闻反复进入上下文。
- 记忆提取：自动读取近期事件摘要，避免重复报道、增强连续性
- 闭环更新：报告生成成功后才标记文章为已处理（崩溃安全），更新失败会保留待办状态
- 基础清洗（标题、摘要、HTML 清理）
- LLM 聚类同一事件并标注重要性（high / medium / low）
- LLM 生成中文事件总结与全局摘要
- 每个事件自动附来源链接（可折叠 details 区块）
- 生成 Markdown 日报到 output 目录
- 每次运行后自动更新:
  - 首页 [index.md](index.md) 最近 10 条报告列表
  - 归档页 [archives.md](archives.md) 全量历史报告列表

## 技术栈

- Python 3.12+
- uv（项目与依赖管理）
- SQLite（内置 `sqlite3`，零额外依赖）
- feedparser（RSS 解析）
- httpx（调用 LLM API）
- python-dateutil（时间解析）
- tzdata（Windows 时区数据库支持）

## 项目结构

```text
ai-sports-news/
├── pyproject.toml
├── README.md
├── index.md                     # GitHub Pages 首页（日报列表）
├── archives.md                  # GitHub Pages 归档页（全量列表）
├── spnews.db                    # SQLite 数据库（自动创建，已 gitignore）
├── output/                      # 每日报告输出目录
└── src/
    └── spnews/
        ├── __init__.py
        ├── main.py              # CLI 入口 + 闭环 DB 更新
        ├── config.py            # RSS/LLM/时区/DB 配置
        ├── db.py                # SQLite 数据库操作
        ├── fetcher.py           # RSS 增量抓取（DB 去重）
        ├── llm.py               # LLM API 封装
        ├── cluster.py           # 事件聚类（含历史记忆）
        ├── summarizer.py        # 事件总结（含前续报道衔接）
        ├── report.py            # 报告编排与 Markdown 组装
        └── indexer.py           # 首页/归档自动索引更新
```

## 快速开始

1. 安装依赖

```bash
uv sync
```

1. 设置环境变量并运行

macOS/Linux:

```bash
export LLM_BASE_URL="http://your-server:8070/v1"
export LLM_MODEL="your-model-name"
uv run spnews
```

Windows PowerShell:

```powershell
$env:LLM_BASE_URL="http://your-server:8070/v1"
$env:LLM_MODEL="your-model-name"
uv run spnews
```

Windows CMD:

```cmd
set LLM_BASE_URL=http://your-server:8070/v1
set LLM_MODEL=your-model-name
uv run spnews
```

运行完成后:

- 生成或更新 output/YYYY-MM-DD_sports_daily.md
- 自动刷新 [index.md](index.md) 与 [archives.md](archives.md) 的报告列表

## 配置项

环境变量:

- LLM_BASE_URL: LLM API 地址（默认 [http://localhost:8070/v1](http://localhost:8070/v1)）
- LLM_MODEL: 模型名称（默认 Qwen3.5-27B-Q4:Instruct）

代码内配置（[src/spnews/config.py](src/spnews/config.py)）:

- RSS_SOURCES: 各运动 RSS 源
- DEFAULT_TIMEZONE: 默认时区（当前为 America/Chicago）
- DB_PATH: 数据库文件路径（默认 `spnews.db`，可通过 `SPNEWS_DB` 环境变量覆盖）
- REASON_LIMIT: LLM 推理预算参数

## CLI 用法

```bash
uv run spnews [options]
```

可选参数:

- -s, --sports: 指定运动，可多选（可选值: baseball football formula1）
- -o, --output: 自定义输出路径
- --db: 指定数据库文件路径（默认: spnews.db）

示例:

```bash
# 默认：全部运动，处理所有未处理的文章
uv run spnews

# 只跑 F1
uv run spnews -s formula1

# F1 + NFL
uv run spnews -s formula1 football

# 输出到指定文件
uv run spnews -s formula1 -o output/f1_daily.md

# 使用自定义数据库
uv run spnews --db my_data.db
```

## 报告生成流程

1. **增量抓取**: fetcher.py 抓取 RSS，通过 INSERT OR IGNORE 写入 SQLite（自动去重）
2. **待办筛选**: 从数据库获取 `report_date IS NULL` 的未处理文章
3. **记忆提取**: 从 events 表读取最近 3 天的事件摘要作为上下文
4. **事件聚类**: cluster.py 调用 LLM 聚类并标注重要性，同时关联历史事件
5. **事件总结**: summarizer.py 逐事件生成正文（有前续报道时自动衔接），生成跨运动总览
6. **报告组装**: report.py 组装最终 Markdown（含来源 details）
7. **文件输出**: main.py 保存到 output 目录
8. **闭环更新**: 写入成功后，标记文章 `report_date` 并保存事件摘要到 DB
9. **索引更新**: indexer.py 更新首页与归档页列表

## 时间与日期规则

- 报告标题日期与默认输出文件名，都基于 DEFAULT_TIMEZONE（当前 America/Chicago）
- 报告末尾生成时间显示该时区缩写（CST/CDT）
- RSS 文章的发布时间以 UTC 格式存储在数据库中
- 不再依赖时间窗口过滤，改为数据库状态驱动（`report_date IS NULL` = 待处理）

## GitHub Pages 说明

当前站点采用:

- [index.md](index.md): 站点首页（而不是 index.html）
- [archives.md](archives.md): 历史报告归档页

为保证 GitHub Pages/Jekyll 正常渲染:

- 站点页面（如 index.md、archives.md、output/*.md）保留 front matter（文件开头的 --- 块）
- 报告列表使用 HTML table（避免部分场景下 Markdown 表格渲染异常）

## 已知限制

- 聚类与摘要质量依赖模型能力，建议人工抽检重点事件
- RSS 源偶发不可用时会跳过并继续，不阻塞整次生成
- 当前默认仅支持上述三类运动，新增运动需要补 RSS 源与映射

## 数据库说明

- 首次运行时自动创建 `spnews.db`（SQLite），已添加到 `.gitignore`
- `articles` 表：存储所有抓取过的 RSS 文章，`link` 字段唯一索引去重
- `events` 表：存储已生成的事件摘要，用于历史记忆和连续性
- 即使多天未运行，积压的新文章会在下次运行时一次性处理
- 如果运行中途崩溃，未标记的文章会在下次运行时自动重新处理
- 查看数据库：`sqlite3 spnews.db "SELECT sport, count(*), sum(report_date IS NOT NULL) FROM articles GROUP BY sport;"`

## 开发建议

- 本地快速验证可先只跑单项运动，减少耗时:

```bash
uv run spnews -s formula1
```

- 部署到 GitHub Pages 后，优先检查 3 个入口页面:
- 首页: [https://hycircle.github.io/ai-sports-news/](https://hycircle.github.io/ai-sports-news/)
- 归档: [https://hycircle.github.io/ai-sports-news/archives.html](https://hycircle.github.io/ai-sports-news/archives.html)
- GitHub 仓库: [https://github.com/HyCircle/ai-sports-news](https://github.com/HyCircle/ai-sports-news)

## 许可证

本项目采用 [MIT License](LICENSE)。
