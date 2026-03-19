---
---

# spnews 🏈⚾🏎️

轻量级体育资讯自动化工具 · RSS 抓取 + LLM 聚类 + 中文早报

---

**支持运动**: NFL | MLB | F1  
**技术栈**: Python 3.12+ · uv · feedparser · LLM API

---

## 📰 每日报告

<!-- 
# 如何添加新报告
每次运行 `uv run spnews` 生成新报告后，只需提交到 GitHub，
该报告会自动出现在下方列表中。点击日期即可查看已渲染的 Markdown 页面。

1. 本地生成：`uv run spnews` → output/YYYY-MM-DD_sports_daily.md
2. 上传 GitHub: `git add output/ && git commit -m "update" && git push`
3. GitHub Pages 自动渲染为 HTML
-->

<!-- REPORT_LIST_START -->
| 📅 日期 | 🏆 涵盖运动 |
|---------|-------------|
| [2026-03-19](output/2026-03-19_sports_daily.html) | MLB · NFL · F1 |
| [2026-03-17](output/2026-03-17_sports_daily.html) | MLB · NFL · F1 |
| [2026-03-16](output/2026-03-16_sports_daily.html) | MLB · NFL · F1 |
| [2026-03-15](output/2026-03-15_sports_daily.html) | MLB · NFL · F1 |

> 共 4 份日报，查看完整历史列表: [Archived Reports](archives.html)
<!-- REPORT_LIST_END -->

> 💡 **提示**: 报告列表会在每次运行 `uv run spnews` 后自动更新，默认展示最近 10 条。

---

## 🛠️ 本地部署

```bash
# 安装依赖
uv sync

# 配置环境变量 (替换为你的 LLM 地址)
export LLM_BASE_URL="http://your-server:8070/v1"
export LLM_MODEL="your-model-name"

# 运行生成报告
uv run spnews
```

### 可选参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `-s, --sports` | 选择运动 | `uv run spnews -s formula1 football` |
| `--hours` | 回溯小时数 | `uv run spnews --hours 12` |
| `-o, --output` | 自定义输出路径 | `-o output/f1_daily.md` |

---

## 📦 项目结构

```text
spnews/
├── pyproject.toml    # 依赖配置
├── README.md         # 详细说明文档
├── src/spnews/
│   ├── main.py       # CLI 入口
│   ├── config.py     # 配置文件 (环境变量)
│   ├── fetcher.py    # RSS 抓取
│   ├── llm.py        # LLM API 调用
│   ├── cluster.py    # 事件聚类
│   └── summarizer.py # AI 总结生成
└── output/           # 每日报告生成目录 ✅
```

---

---

🎯 想深入了解项目？ → [访问项目介绍页](landing.html)

*Powered by 🐍 Python + ⚡ LLM API · Built with simplicity in mind*
