"""PostgreSQL 18 + pgvector storage layer."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import Settings

_SCHEMA_TEMPLATE = """\
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS articles (
    id               BIGSERIAL PRIMARY KEY,
    canonical_url    TEXT NOT NULL UNIQUE,
    sport            TEXT NOT NULL,
    source_name      TEXT NOT NULL DEFAULT '',
    title            TEXT NOT NULL,
    summary          TEXT NOT NULL DEFAULT '',
    content_from_rss TEXT NOT NULL DEFAULT '',
    fetched_body     TEXT,
    published_at     TIMESTAMPTZ,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding        vector({dim}),
    status           TEXT NOT NULL DEFAULT 'pending',
    filter_reason    TEXT,
    report_date      DATE
);

CREATE INDEX IF NOT EXISTS idx_articles_sport_status
    ON articles (sport, status, published_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id              BIGSERIAL PRIMARY KEY,
    report_date     DATE NOT NULL,
    sport           TEXT NOT NULL,
    title           TEXT NOT NULL,
    importance      TEXT NOT NULL DEFAULT 'medium',
    summary_md      TEXT NOT NULL,
    article_ids     BIGINT[] NOT NULL DEFAULT '{{}}',
    parent_event_id BIGINT REFERENCES events(id),
    embedding       vector({dim}),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_sport_date
    ON events (sport, report_date DESC);

CREATE TABLE IF NOT EXISTS reports (
    report_date      DATE PRIMARY KEY,
    overview_bullets JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_json      JSONB NOT NULL,
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id          BIGSERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'running',
    stats       JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    error       TEXT
);
"""


@contextmanager
def connect(dsn: str) -> Iterator[psycopg.Connection]:
    """Open a psycopg connection with pgvector registered and dict_row factory."""
    conn = psycopg.connect(dsn, row_factory=dict_row)
    register_vector(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(settings: Settings) -> None:
    """Create tables and indexes idempotently."""
    ddl = _SCHEMA_TEMPLATE.format(dim=settings.embed_dim)
    with psycopg.connect(settings.spnews_database_url) as conn:
        conn.execute(ddl)
        conn.commit()


def save_articles(dsn: str, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert articles via ON CONFLICT DO NOTHING.

    Returns (inserted_pending, inserted_filtered).
    """
    if not rows:
        return 0, 0
    inserted_pending = 0
    inserted_filtered = 0
    with connect(dsn) as conn:
        for r in rows:
            cur = conn.execute(
                """
                INSERT INTO articles (
                    canonical_url, sport, source_name, title, summary,
                    content_from_rss, published_at, status, filter_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (canonical_url) DO NOTHING
                RETURNING status
                """,
                (
                    r["canonical_url"],
                    r["sport"],
                    r["source_name"],
                    r["title"],
                    r["summary"],
                    r["content_from_rss"],
                    r["published_at"],
                    r["status"],
                    r["filter_reason"],
                ),
            )
            row = cur.fetchone()
            if row:
                if row["status"] == "pending":
                    inserted_pending += 1
                else:
                    inserted_filtered += 1
    return inserted_pending, inserted_filtered


def get_articles_needing_embed(dsn: str, sports: list[str] | None = None) -> list[dict[str, Any]]:
    """Return pending articles that do not yet have an embedding vector."""
    with connect(dsn) as conn:
        if sports:
            return conn.execute(
                """
                SELECT id, sport, title, summary, content_from_rss
                FROM articles
                WHERE status = 'pending' AND embedding IS NULL AND sport = ANY(%s)
                ORDER BY published_at DESC NULLS LAST, id DESC
                """,
                (sports,),
            ).fetchall()
        return conn.execute(
            """
            SELECT id, sport, title, summary, content_from_rss
            FROM articles
            WHERE status = 'pending' AND embedding IS NULL
            ORDER BY published_at DESC NULLS LAST, id DESC
            """
        ).fetchall()


def save_article_embeddings(dsn: str, items: list[tuple[int, np.ndarray]]) -> None:
    """Persist L2-normalized float32 embeddings for articles."""
    if not items:
        return
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE articles SET embedding = %s WHERE id = %s",
            [(vec, aid) for aid, vec in items],
        )


def get_pending_articles(dsn: str, sport: str) -> list[dict[str, Any]]:
    """Return all pending articles for one sport, newest first."""
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT id, canonical_url, sport, source_name, title, summary,
                   content_from_rss, fetched_body, published_at, embedding
            FROM articles
            WHERE sport = %s AND status = 'pending'
            ORDER BY published_at DESC NULLS LAST, id DESC
            """,
            (sport,),
        ).fetchall()
    for r in rows:
        emb = r.get("embedding")
        if emb is not None and hasattr(emb, "to_numpy"):
            r["embedding"] = emb.to_numpy()
    return rows


def save_fetched_bodies(dsn: str, bodies: dict[int, str]) -> None:
    """Cache extracted full-text bodies on articles so retries/re-runs skip re-fetching."""
    if not bodies:
        return
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE articles SET fetched_body = %s WHERE id = %s",
            [(body, aid) for aid, body in bodies.items()],
        )


def search_similar_events(
    dsn: str,
    sport: str,
    query_vec: np.ndarray,
    days: int = 14,
    limit: int = 3,
    min_similarity: float = 0.55,
) -> list[dict[str, Any]]:
    """Find top-K recent events for the same sport by cosine similarity."""
    max_dist = 1.0 - min_similarity
    with connect(dsn) as conn:
        return conn.execute(
            """
            SELECT id, report_date, title, importance, summary_md,
                   1.0 - (embedding <=> %s) AS similarity
            FROM events
            WHERE sport = %s
              AND embedding IS NOT NULL
              AND report_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
              AND (embedding <=> %s) <= %s
            ORDER BY embedding <=> %s ASC
            LIMIT %s
            """,
            (query_vec, sport, days, query_vec, max_dist, query_vec, limit),
        ).fetchall()


def commit_report_run(
    dsn: str,
    report_date: str,
    overview_bullets: list[str],
    report_json: dict[str, Any],
    events_to_save: list[dict[str, Any]],
    used_article_ids: list[int],
    ignored_article_ids: list[int],
) -> list[int]:
    """Atomically save events, upsert the daily report, and mark articles processed."""
    event_ids: list[int] = []
    with connect(dsn) as conn:
        sports_in_run = sorted({ev["sport"] for ev in events_to_save})
        if sports_in_run:
            conn.execute(
                "DELETE FROM events WHERE report_date = %s AND sport = ANY(%s)",
                (report_date, sports_in_run),
            )
        for ev in events_to_save:
            row = conn.execute(
                """
                INSERT INTO events (
                    report_date, sport, title, importance, summary_md,
                    article_ids, parent_event_id, embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    report_date,
                    ev["sport"],
                    ev["title"],
                    ev["importance"],
                    ev["summary_md"],
                    ev["article_ids"],
                    ev.get("parent_event_id"),
                    ev.get("embedding"),
                ),
            ).fetchone()
            event_ids.append(row["id"])
            ev["id"] = row["id"]

        id_by_key = {(ev["sport"], ev["title"]): ev["id"] for ev in events_to_save}
        for section in report_json.get("sections", []):
            sport_key = section["sport"]
            for item in section.get("events", []):
                eid = id_by_key.get((sport_key, item["title"]))
                if eid is not None:
                    item["id"] = eid

        conn.execute(
            """
            INSERT INTO reports (report_date, overview_bullets, report_json, generated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (report_date) DO UPDATE
            SET overview_bullets = EXCLUDED.overview_bullets,
                report_json = EXCLUDED.report_json,
                generated_at = now()
            """,
            (report_date, Jsonb(overview_bullets), Jsonb(report_json)),
        )

        if used_article_ids:
            conn.execute(
                """
                UPDATE articles
                SET status = 'used', report_date = %s
                WHERE id = ANY(%s)
                """,
                (report_date, used_article_ids),
            )
        if ignored_article_ids:
            conn.execute(
                """
                UPDATE articles
                SET status = 'ignored', report_date = %s
                WHERE id = ANY(%s)
                """,
                (report_date, ignored_article_ids),
            )
    return event_ids


def list_reports(dsn: str) -> list[dict[str, Any]]:
    """Return all stored daily reports ordered newest first."""
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT report_date, overview_bullets, report_json, generated_at
            FROM reports
            ORDER BY report_date DESC
            """
        ).fetchall()
    return rows


def start_run(dsn: str) -> int:
    with connect(dsn) as conn:
        row = conn.execute(
            "INSERT INTO runs (status) VALUES ('running') RETURNING id"
        ).fetchone()
        return int(row["id"])


def finish_run(
    dsn: str,
    run_id: int,
    status: str,
    stats: dict[str, Any],
    error: str | None = None,
) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            UPDATE runs
            SET finished_at = %s, status = %s, stats = %s, error = %s
            WHERE id = %s
            """,
            (datetime.now(UTC), status, Jsonb(stats), error, run_id),
        )


def get_status_summary(dsn: str) -> dict[str, Any]:
    """Return database health metrics for `spnews status`."""
    with connect(dsn) as conn:
        articles = conn.execute(
            """
            SELECT sport,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                   COUNT(*) FILTER (WHERE status = 'used') AS used,
                   COUNT(*) FILTER (WHERE status = 'ignored') AS ignored,
                   COUNT(*) FILTER (WHERE status = 'filtered') AS filtered,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
            FROM articles
            GROUP BY sport
            ORDER BY sport
            """
        ).fetchall()
        reports_cnt = conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"]
        events_cnt = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        recent_runs = conn.execute(
            """
            SELECT id, started_at, finished_at, status, stats, error
            FROM runs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
    return {
        "articles_by_sport": articles,
        "reports_count": reports_cnt,
        "events_count": events_cnt,
        "recent_runs": recent_runs,
    }


def dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
