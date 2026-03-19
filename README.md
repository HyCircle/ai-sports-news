# spnews

轻量级体育资讯自动化工具：抓取 RSS 新闻，按事件聚类，调用本地 LLM 生成中文 Markdown 早报。

当前关注运动：
- 橄榄球（NFL）
- 棒球（MLB）
- F1 赛车

## 功能概览

- 多源 RSS 抓取（按运动拆分）
- 时间窗口过滤（默认过去 24 小时）
- 去重与基础清洗（标题、摘要、HTML 清理）
- LLM 聚类同一事件并排序重要性（`high / medium / low`）
- 分级生成中文总结：
	- `high`：3 段深入总结
	- `medium`：1 段简要总结
	- `low`：仅列出相关链接
- 自动附来源链接，保证可溯源
- 输出 Markdown 报告

## 技术栈

- Python 3.12+
- uv（项目与依赖管理）
- `feedparser`（RSS 解析）
- `httpx`（调用 LLM API）
- `python-dateutil`（时间解析）
- `tzdata`（Windows 时区数据库支持）

## 项目结构

```text
spnews/
├── pyproject.toml
├── README.md
├── output/
└── src/
    └── spnews/
        ├── __init__.py
        ├── main.py        # CLI 入口
        ├── config.py      # RSS/LLM/时区配置
        ├── fetcher.py     # RSS 抓取与时间过滤
        ├── llm.py         # LLM API 封装
        ├── cluster.py     # 事件聚类与重要性排序
        ├── summarizer.py  # 事件总结与全局摘要
        └── report.py      # Markdown 报告组装
```

## 快速开始

1. 安装 uv（如未安装）
2. 在项目目录安装依赖

```bash
uv sync
```

3. 运行

```bash
uv run spnews
```

执行后将生成报告到 `output/` 目录。

## 配置

配置文件：`src/spnews/config.py`

- LLM 服务地址：`LLM_BASE_URL`
- 模型名：`LLM_MODEL`
- RSS 源列表：`RSS_SOURCES`
- 时区：`DEFAULT_TIMEZONE`（当前为 `America/Chicago`）

当前默认配置示例：

```python
LLM_BASE_URL = "http://10.0.0.181:8070/v1"
LLM_MODEL = "Qwen3.5-35B-A3B-Q4_K_M:Thinking"
# LLM_MODEL = "GLM-4.7-Flash:UD-Q4_K_XL"
DEFAULT_TIMEZONE = "America/Chicago"
```

## CLI 用法

```bash
uv run spnews [options]
```

可选参数：

- `-s, --sports`：选择运动，可多选
	- 可选值：`baseball` `football` `formula1`
- `--hours`：回溯小时数（默认 `24`）
- `-o, --output`：自定义输出文件路径

示例：

```bash
# 默认：三项运动 + 过去 24 小时
uv run spnews

# 只跑 F1
uv run spnews -s formula1

# F1 + NFL，过去 12 小时
uv run spnews -s formula1 football --hours 12

# 输出到指定文件
uv run spnews -s formula1 -o output/f1_daily.md
```

## 输出说明

报告结构：

1. 顶部全局摘要（跨运动）
2. 各运动分节
3. 事件级摘要（按重要性排序）
4. 每个事件对应来源链接
5. 报告尾部生成时间与声明

时间相关说明：

- 报告中的生成时间使用芝加哥时区（`America/Chicago`，会自动显示 `CST/CDT`）
- RSS 文章筛选使用 UTC 时间进行窗口过滤（与大多数源发布时间格式一致）

## 工作流

按运动独立执行，最后拼接：

1. 抓取 RSS 文章
2. 过滤时间窗口并去重
3. LLM 聚类同一事件并标注重要性
4. LLM 生成事件摘要
5. 组装单运动 Markdown
6. 生成全局摘要并合并为最终报告

这种方式便于测试阶段只跑单项运动，降低耗时和算力消耗。

## 注意事项

- 输出依赖本地 LLM 服务稳定性与模型质量
- 聚类与摘要由模型生成，建议人工抽检重点事件
- 某些 RSS 源可能临时不可用，程序会跳过并继续
- 本项目定位个人轻量工具，优先可读性与可维护性

## 许可证

当前未声明开源许可证，如需公开发布请补充 `LICENSE` 文件。
