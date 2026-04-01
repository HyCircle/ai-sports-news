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

