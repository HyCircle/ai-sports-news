"""Deterministic tests for calendar table, Markdown rendering, static site, and RSS 2.0 output."""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from spnews.site import build_site_from_reports, render_summary_html
from spnews.summarize import (
    EventSummaryOutput,
    build_calendar_reference,
    find_factual_glitches,
    normalize_summary_text,
)


def test_calendar_reference_exact_weekdays():
    now = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    cal = build_calendar_reference(now, days=3)
    assert "2026-11-25（周三，今天）" in cal
    assert "2026-11-24（周二，昨天）" in cal
    assert "2026-11-23（周一，2天前）" in cal


def test_summary_normalization_and_glitch_detection():
    assert normalize_summary_text('在 11 月 22 日签下 $1.2亿合同，称 "完全无意义"。') == (
        "在 11月22日签下 1.2亿美元合同，称 “完全无意义”。"
    )
    glitches = find_factual_glitches("哈登全场 15投26中，素材显示他状态火热。")
    assert len(glitches) == 2
    assert any("26投15中" in g for g in glitches)
    assert any("素材显示" in g for g in glitches)
    assert find_factual_glitches("哈登全场 26投15中、14罚14中。") == []


def test_event_summary_output_to_markdown():
    out = EventSummaryOutput(
        title="小熊连续补强外野与轮换",
        lead="芝加哥小熊在24小时内签下两名核心球员。",
        body_blocks=[
            "- 与 Teruaki Sato 达成 **6年1.2亿美元** 合同。",
            "- 与 Trevor Rogers 达成 **5年1.2亿美元** 合同。",
            "两笔引援旨在填补休赛期离队空缺。",
        ],
    )
    md = out.to_markdown()
    assert md.startswith("芝加哥小熊在24小时内签下两名核心球员。\n\n- 与 Teruaki Sato")
    assert "\n- 与 Trevor Rogers" in md
    assert "\n\n两笔引援旨在填补休赛期离队空缺。" in md


def test_render_summary_html_escapes_html_and_formats_markdown():
    md = (
        "签约总额 **$45.75 million**，含 <script>alert(1)</script>。\n\n"
        "- 第一项 **3-0**\n"
        "- 第二项 *重点*"
    )
    rendered = render_summary_html(md)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<strong>$45.75 million</strong>" in rendered
    assert "<ul><li>第一项 <strong>3-0</strong></li><li>第二项 <em>重点</em></li></ul>" in rendered


def test_build_site_and_rss_xml(tmp_path: Path):
    reports = [
        {
            "report_date": "2026-11-25",
            "generated_at": "2026-11-25T14:00:00-06:00",
            "timezone": "CST",
            "llm_model": "deepseek-flash",
            "overview_bullets": ["湖人以 **112-104** 击败掘金。"],
            "counts": {
                "sports": 1,
                "events": 1,
                "high_events": 1,
                "articles_used": 2,
                "articles_ignored": 1,
            },
            "sections": [
                {
                    "sport": "basketball",
                    "sport_name": "篮球 (NBA)",
                    "badge": "NBA",
                    "events": [
                        {
                            "id": 42,
                            "title": "湖人击败掘金",
                            "importance": "high",
                            "summary_md": "洛杉矶湖人 (Los Angeles Lakers) 以 **112-104** 战胜掘金。",
                            "parent_event": {
                                "id": 10,
                                "report_date": "2026-11-24",
                                "title": "湖人伤病更新",
                            },
                            "sources": [
                                {
                                    "title": "Lakers top Nuggets",
                                    "source_name": "ESPN",
                                    "url": "https://www.espn.com/nba/story/_/id/1",
                                    "published_at": "2026-11-25T05:00:00+00:00",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        {
            "report_date": "2026-11-24",
            "generated_at": "2026-11-24T14:00:00-06:00",
            "timezone": "CST",
            "llm_model": "deepseek-flash",
            "overview_bullets": ["昨日回顾。"],
            "counts": {
                "sports": 1,
                "events": 1,
                "high_events": 0,
                "articles_used": 1,
                "articles_ignored": 0,
            },
            "sections": [
                {
                    "sport": "basketball",
                    "sport_name": "篮球 (NBA)",
                    "badge": "NBA",
                    "events": [
                        {
                            "id": 10,
                            "title": "湖人伤病更新",
                            "importance": "medium",
                            "summary_md": "赛前伤病名单更新。",
                            "parent_event": None,
                            "sources": [],
                        }
                    ],
                }
            ],
        },
    ]

    out = tmp_path / "dist"
    res = build_site_from_reports(reports, output_dir=out, site_url="https://sports.yhao.dev")
    assert res["reports_rendered"] == 2
    assert res["latest_date"] == "2026-11-25"

    index_html = (out / "index.html").read_text(encoding="utf-8")
    assert "体育日报" in index_html
    assert '<link rel="canonical" href="https://sports.yhao.dev/">' in index_html
    assert 'href="#event-42"' in index_html  # overview bullet & TOC linked to matching event
    assert 'id="toc-nav"' in index_html
    assert "/reports/2026-11-24/#event-10" in index_html

    day_html = (out / "reports" / "2026-11-25" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://sports.yhao.dev/reports/2026-11-25/">' in day_html
    assert (out / "reports" / "2026-11-24" / "index.html").exists()

    archives_html = (out / "archives" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://sports.yhao.dev/archives/">' in archives_html
    assert (out / "assets" / "style.css").exists()
    assert (out / "assets" / "app.js").exists()

    latest_json = json.loads((out / "data" / "latest.json").read_text(encoding="utf-8"))
    assert latest_json["report_date"] == "2026-11-25"

    # RSS must be well-formed XML with both items
    rss_root = ET.fromstring((out / "rss.xml").read_text(encoding="utf-8"))
    items = rss_root.findall("./channel/item")
    assert len(items) == 2
    assert items[0].findtext("link") == "https://sports.yhao.dev/reports/2026-11-25/"
