# ai-sports-news

轻量级体育资讯自动化工具：抓取 RSS 新闻，按事件聚类，调用本地 LLM 生成中文 Markdown 日报，并自动维护 GitHub Pages 首页与归档列表。

日报首页: [https://hycircle.github.io/ai-sports-news/](https://hycircle.github.io/ai-sports-news/)

## 当前支持

- 橄榄球 (NFL)
- 棒球 (MLB)
- F1 赛车

## 功能概览

- 多源 RSS 抓取（按运动拆分）
- 时间窗口过滤（默认过去 24 小时）
- 去重与基础清洗（标题、摘要、HTML 清理）
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
├── output/                      # 每日报告输出目录
└── src/
    └── spnews/
        ├── __init__.py
        ├── main.py              # CLI 入口
        ├── config.py            # RSS/LLM/时区配置
        ├── fetcher.py           # RSS 抓取与时间过滤
        ├── llm.py               # LLM API 封装
        ├── cluster.py           # 事件聚类与重要性排序
        ├── summarizer.py        # 事件总结与全局摘要
        ├── report.py            # Markdown 报告组装
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
- REASON_LIMIT: LLM 推理预算参数

## CLI 用法

```bash
uv run spnews [options]
```

可选参数:

- -s, --sports: 指定运动，可多选
- 可选值: baseball football formula1
- --hours: 回溯小时数（默认 24）
- -o, --output: 自定义输出路径

示例:

```bash
# 默认：全部运动 + 过去 24 小时
uv run spnews

# 只跑 F1
uv run spnews -s formula1

# F1 + NFL，过去 12 小时
uv run spnews -s formula1 football --hours 12

# 输出到指定文件
uv run spnews -s formula1 -o output/f1_daily.md
```

## 报告生成流程

1. fetcher.py 抓取并过滤 RSS 文章
2. cluster.py 调用 LLM 进行事件聚类与重要性排序
3. summarizer.py 逐事件生成正文，并生成跨运动总览
4. report.py 组装最终 Markdown（含来源 details）
5. main.py 保存到 output 目录
6. indexer.py 更新首页与归档页列表

## 时间与日期规则

- 报告标题日期与默认输出文件名，都基于 DEFAULT_TIMEZONE（当前 America/Chicago）
- 报告末尾生成时间显示该时区缩写（CST/CDT）
- RSS 时间过滤在 UTC 语义下进行窗口比较（更适配源站时间格式）

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

## 开发建议

- 本地快速验证可先只跑单项运动，减少耗时:

```bash
uv run spnews -s formula1 --hours 12
```

- 部署到 GitHub Pages 后，优先检查 3 个入口页面:
- 首页: [https://hycircle.github.io/ai-sports-news/](https://hycircle.github.io/ai-sports-news/)
- 归档: [https://hycircle.github.io/ai-sports-news/archives.html](https://hycircle.github.io/ai-sports-news/archives.html)
- GitHub 仓库: [https://github.com/HyCircle/ai-sports-news](https://github.com/HyCircle/ai-sports-news)

## 许可证

本项目采用 [MIT License](LICENSE)。
