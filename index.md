---
---

# spnews 🏈⚾🏎️

轻量级体育资讯自动化工具 · RSS 抓取 + LLM 聚类 + 中文日报

---

**支持运动**: NFL | MLB | F1 | 足球 | NBA  
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
<table>
  <thead>
    <tr><th>📅 日期</th><th>🏆 涵盖运动</th></tr>
  </thead>
  <tbody>
<tr><td><a href="output/2026-04-07_sports_daily.html">2026-04-07</a></td><td>MLB · NFL · F1 · 足球 · NBA</td></tr>
<tr><td><a href="output/2026-04-06_sports_daily.html">2026-04-06</a></td><td>MLB · NFL · F1 · 足球 · NBA</td></tr>
<tr><td><a href="output/2026-04-05_sports_daily.html">2026-04-05</a></td><td>MLB · NFL · F1 · 足球 · NBA</td></tr>
<tr><td><a href="output/2026-04-04_sports_daily.html">2026-04-04</a></td><td>MLB · NFL · F1 · 足球 · NBA</td></tr>
<tr><td><a href="output/2026-04-03_sports_daily.html">2026-04-03</a></td><td>MLB · NFL · F1</td></tr>
<tr><td><a href="output/2026-03-31_sports_daily.html">2026-03-31</a></td><td>MLB · NFL · F1</td></tr>
<tr><td><a href="output/2026-03-29_sports_daily.html">2026-03-29</a></td><td>MLB · NFL · F1</td></tr>
<tr><td><a href="output/2026-03-27_sports_daily.html">2026-03-27</a></td><td>MLB · NFL · F1</td></tr>
<tr><td><a href="output/2026-03-26_sports_daily.html">2026-03-26</a></td><td>MLB · NFL · F1</td></tr>
<tr><td><a href="output/2026-03-25_sports_daily.html">2026-03-25</a></td><td>MLB · NFL · F1</td></tr>
  </tbody>
</table>

> 共 20 份日报，查看完整历史列表: [Archived Reports](archives.html)
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

🎯 想深入了解项目？ → [访问 GitHub Repo](https://github.com/HyCircle/ai-sports-news)

*Powered by 🐍 Python + ⚡ LLM API · Built with simplicity in mind*
