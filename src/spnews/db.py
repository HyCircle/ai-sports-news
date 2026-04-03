"""SQLite storage for articles and generated event summaries."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    link        TEXT    UNIQUE NOT NULL,
    title       TEXT    NOT NULL,
    summary     TEXT    NOT NULL DEFAULT '',
    sport       TEXT    NOT NULL,
    source_name TEXT    NOT NULL DEFAULT '',
    published_at TEXT,
    fetched_at  TEXT    NOT NULL,
    report_date TEXT,
    used        INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date  TEXT    NOT NULL,
    sport        TEXT    NOT NULL,
    event_name   TEXT    NOT NULL,
    importance   TEXT    NOT NULL DEFAULT 'medium',
    summary_text TEXT    NOT NULL,
    article_links TEXT   NOT NULL DEFAULT '[]',
    created_at   TEXT    NOT NULL
);
"""


@contextmanager
def _connect(db_path: str | Path):
    """Yield a sqlite3 connection with auto commit/rollback."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> Path:
    """Create tables if they don't exist. Returns the resolved path."""
    db_path = Path(db_path)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
    return db_path


def save_articles(db_path: str | Path, articles: list[dict], sport: str) -> int:
    """Bulk-insert articles via INSERT OR IGNORE. Returns count of newly inserted rows."""
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with _connect(db_path) as conn:
        for art in articles:
            pub = art.get("published")
            pub_str = pub.isoformat() if pub else None
            cur = conn.execute(
                "INSERT OR IGNORE INTO articles "
                "(link, title, summary, sport, source_name, published_at, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (art["link"], art["title"], art["summary"],
                 sport, art.get("source_name", ""), pub_str, now),
            )
            inserted += cur.rowcount
    return inserted


def get_pending_articles(db_path: str | Path, sport: str) -> list[dict]:
    """Return articles with report_date IS NULL for the given sport."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT link, title, summary, source_name, published_at "
            "FROM articles WHERE sport = ? AND report_date IS NULL "
            "ORDER BY published_at DESC",
            (sport,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_articles_done(
    db_path: str | Path,
    report_date: str,
    used_links: list[str],
    ignored_links: list[str],
) -> None:
    """Mark all considered articles for this run.

    used_links:    articles that appeared in the final report (used=1).
    ignored_links: articles that were considered but filtered out by the LLM (used=0).
    Both sets receive report_date so they are never re-queued as pending.
    """
    with _connect(db_path) as conn:
        if used_links:
            conn.executemany(
                "UPDATE articles SET report_date = ?, used = 1 WHERE link = ?",
                [(report_date, link) for link in used_links],
            )
        if ignored_links:
            conn.executemany(
                "UPDATE articles SET report_date = ?, used = 0 WHERE link = ?",
                [(report_date, link) for link in ignored_links],
            )


def save_events(db_path: str | Path, report_date: str, sport: str,
                events: list[dict]) -> None:
    """Persist generated event summaries."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        for ev in events:
            conn.execute(
                "INSERT INTO events "
                "(report_date, sport, event_name, importance, summary_text, "
                "article_links, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (report_date, sport, ev["event_name"], ev.get("importance", "medium"),
                 ev["summary_text"], json.dumps(ev.get("article_links", [])), now),
            )


def get_recent_events(db_path: str | Path, sport: str,
                      days: int = 3) -> list[dict]:
    """Return events from the last N days for context/memory."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT report_date, event_name, importance, summary_text "
            "FROM events WHERE sport = ? "
            "AND report_date >= date('now', ?)"
            "ORDER BY report_date DESC, id DESC",
            (sport, f"-{days} days"),
        ).fetchall()
    return [dict(r) for r in rows]
