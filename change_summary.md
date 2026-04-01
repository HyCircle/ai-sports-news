# Change Summary: SQLite Database Integration

## Phase 0: Pre-setup

- `.gitignore`: 添加 `*.db` 规则，防止 SQLite 数据库文件被提交
- `change_summary.md`: 创建本文件，用于跟踪各阶段改动

## Phase 1: Database Infrastructure

- **新建 `src/spnews/db.py`**: SQLite 数据库模块，包含：
  - `articles` 表：存储 RSS 文章，`link` 唯一索引去重，`report_date IS NULL` 标识待处理
  - `events` 表：存储已生成事件摘要，用于历史记忆/连续性
  - `init_db()`: 建表（IF NOT EXISTS）
  - `save_articles()`: INSERT OR IGNORE 批量写入
  - `get_pending_articles()`: 获取未处理文章
  - `mark_articles_used()`: 标记文章已用于指定日期报告
  - `save_events()`: 保存事件摘要
  - `get_recent_events()`: 获取最近 N 天事件（记忆提取）
- **修改 `src/spnews/config.py`**: 新增 `DB_PATH` 配置项（默认 `spnews.db`，可通过 `SPNEWS_DB` 环境变量覆盖）

## Phase 2: Refactor fetcher.py

- **重构 `src/spnews/fetcher.py`**:
  - 删除 `hours` 参数和 24 小时时间窗口过滤逻辑（`cutoff`/`timedelta`）
  - 删除按时间排序逻辑（聚类由 LLM 处理）
  - 新增 `db_path` 参数，调用 `db.save_articles()` 进行 INSERT OR IGNORE 去重
  - 函数返回类型从 `list[dict]` 改为 `int`（新插入的文章数）
  - `_extract_entry()` 直接接收 `source_name` 参数，不再后续赋值
  - 仍保留 `seen_links` 做同一批次内的快速去重（避免同一次 RSS 抓取中的重复条目浪费 DB 操作）

## Phase 3: Enhance cluster.py + summarizer.py

- **修改 `src/spnews/cluster.py`**:
  - `cluster_articles()` 新增可选参数 `recent_events: list[dict] | None`
  - 当 `recent_events` 非空时，在 clustering prompt 中追加"近期已报道事件"上下文
  - 提示 LLM 在 JSON 输出中新增 `related_previous_event` 字段，标注与历史事件的关联
- **修改 `src/spnews/summarizer.py`**:
  - `summarize_event()` 新增可选参数 `previous_coverage: str | None`
  - 当有前续报道时，在 prompt 中注入记忆提示，引导 LLM 用"此前报道..."衔接，避免重复内容

## Phase 4: Refactor main.py + report.py (State-Driven Workflow)

- **重构 `src/spnews/report.py`**:
  - `build_sport_section()` 改为内部函数 `_build_sport_section()`，接收已获取的 `articles` 和 `recent_events`
  - 不再自行调用 `fetch_sport()`，而是由 `build_full_report()` 统一编排
  - 返回 `(md_section, generated_events, used_links)` 三元组，支持闭环更新
  - `build_full_report()` 签名改为 `(sports, db_path)`，删除 `hours` 参数
  - 新流程：init_db → fetch_sport → get_pending_articles → get_recent_events → _build_sport_section → overview
  - 返回 `(report_str, events_by_sport, all_used_links)`，由调用方执行闭环 DB 更新
  - 利用 `related_previous_event` 字段匹配前续报道，传入 `previous_coverage` 给 summarizer

- **重构 `src/spnews/main.py`**:
  - 删除 `--hours` CLI 参数
  - 新增 `--db` CLI 参数（覆盖 DB 路径）
  - 闭环更新：仅在 Markdown 文件写入成功后，才调用 `mark_articles_used()` 和 `save_events()`
  - 打印 DB 更新统计信息

## Phase 5: CLI Parameter Adjustment

- 已在 Phase 4 中完成：删除 `--hours`，新增 `--db`
- CLI 验证通过：`uv run spnews --help` 输出正确

## Phase 6: README Update

- **更新 `README.md`**:
  - 项目描述增加 SQLite 数据库说明
  - 功能概览：替换"时间窗口过滤"为数据库驱动的完整功能列表（增量抓取/待办筛选/记忆提取/闭环更新）
  - 技术栈：新增 SQLite（内置 sqlite3）
  - 项目结构：新增 db.py，更新各模块注释
  - 配置项：新增 DB_PATH / SPNEWS_DB 说明
  - CLI 用法：删除 --hours，新增 --db，更新示例
  - 报告生成流程：从 6 步扩展为 9 步（含 DB 操作）
  - 时间/日期规则：删除时间窗口过滤描述
  - 新增"数据库说明"章节
  - 开发建议：移除 --hours 示例

