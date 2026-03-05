"""Persistent knowledge base for cross-issue references and research memory.

Stores every paper we've seen, topics we've identified, and free-form
knowledge entries.  Used to inject historical context into analysis prompts
and to generate cross-references in reports.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Memory:
    """SQLite-backed knowledge base."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    # ── schema ─────────────────────────────────────────────────

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                arxiv_id    TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                authors     TEXT NOT NULL DEFAULT '[]',
                report_date TEXT,
                tags        TEXT NOT NULL DEFAULT '[]',
                novelty     REAL,
                confidence  REAL,
                paper_type  TEXT,
                skip_reason TEXT,
                included    INTEGER DEFAULT 0,
                issue_no    INTEGER,
                summary     TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topics (
                name         TEXT PRIMARY KEY,
                description  TEXT,
                paper_count  INTEGER DEFAULT 0,
                first_seen   TEXT NOT NULL,
                last_updated TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_topics (
                arxiv_id TEXT NOT NULL REFERENCES papers(arxiv_id),
                topic    TEXT NOT NULL REFERENCES topics(name),
                PRIMARY KEY (arxiv_id, topic)
            );

            CREATE TABLE IF NOT EXISTS entries (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                category   TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_papers_date
                ON papers(report_date);
            CREATE INDEX IF NOT EXISTS idx_papers_included
                ON papers(included);
            CREATE INDEX IF NOT EXISTS idx_pt_topic
                ON paper_topics(topic);
            CREATE INDEX IF NOT EXISTS idx_entries_cat
                ON entries(category);
            """
        )
        self._conn.commit()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── papers ─────────────────────────────────────────────────

    def record_paper(
        self,
        arxiv_id: str,
        title: str,
        *,
        authors: list[str] | None = None,
        report_date: str = "",
        tags: list[str] | None = None,
        novelty: float | None = None,
        confidence: float | None = None,
        paper_type: str = "",
        skip_reason: str = "",
        included: bool = False,
        issue_no: int | None = None,
        summary: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT INTO papers
                   (arxiv_id, title, authors, report_date, tags,
                    novelty, confidence, paper_type, skip_reason,
                    included, issue_no, summary, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(arxiv_id) DO UPDATE SET
                   title      = excluded.title,
                   authors    = CASE WHEN excluded.authors != '[]'
                                     THEN excluded.authors ELSE authors END,
                   report_date= COALESCE(NULLIF(excluded.report_date,''), report_date),
                   tags       = CASE WHEN excluded.tags != '[]'
                                     THEN excluded.tags ELSE tags END,
                   novelty    = COALESCE(excluded.novelty, novelty),
                   confidence = COALESCE(excluded.confidence, confidence),
                   paper_type = COALESCE(NULLIF(excluded.paper_type,''), paper_type),
                   skip_reason= COALESCE(NULLIF(excluded.skip_reason,''), skip_reason),
                   included   = MAX(excluded.included, included),
                   issue_no   = COALESCE(excluded.issue_no, issue_no),
                   summary    = COALESCE(NULLIF(excluded.summary,''), summary)
            """,
            (
                arxiv_id,
                title,
                json.dumps(authors or []),
                report_date,
                json.dumps(tags or []),
                novelty,
                confidence,
                paper_type,
                skip_reason,
                int(included),
                issue_no,
                summary,
                self._now(),
            ),
        )
        self._conn.commit()

    def get_paper(self, arxiv_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)
        ).fetchone()
        return self._paper_dict(row) if row else None

    def search_papers(self, query: str, *, limit: int = 10) -> list[dict]:
        """Keyword search over included papers (title, tags, summary)."""
        words = self._keywords(query)
        if not words:
            return []
        where = " AND ".join(
            "(LOWER(title) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(summary) LIKE ?)"
            for _ in words
        )
        params: list[str] = []
        for w in words:
            p = f"%{w}%"
            params.extend([p, p, p])
        rows = self._conn.execute(
            f"SELECT * FROM papers WHERE included=1 AND ({where}) "
            "ORDER BY report_date DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._paper_dict(r) for r in rows]

    def get_recent_papers(self, n: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM papers WHERE included=1 "
            "ORDER BY report_date DESC, issue_no DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._paper_dict(r) for r in rows]

    def get_papers_by_date(self, date: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM papers WHERE report_date = ? AND included = 1 "
            "ORDER BY issue_no",
            (date,),
        ).fetchall()
        return [self._paper_dict(r) for r in rows]

    # ── topics ─────────────────────────────────────────────────

    def record_topic(self, name: str, description: str = "") -> None:
        now = self._now()
        self._conn.execute(
            """INSERT INTO topics (name, description, first_seen, last_updated)
               VALUES (?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                   description = CASE
                       WHEN LENGTH(excluded.description) > LENGTH(COALESCE(description,''))
                       THEN excluded.description ELSE description END,
                   last_updated = excluded.last_updated""",
            (name, description, now, now),
        )
        self._conn.commit()

    def link_paper_topic(self, arxiv_id: str, topic: str) -> None:
        self.record_topic(topic)
        self._conn.execute(
            "INSERT OR IGNORE INTO paper_topics VALUES (?,?)",
            (arxiv_id, topic),
        )
        self._conn.execute(
            "UPDATE topics SET paper_count = "
            "(SELECT COUNT(*) FROM paper_topics WHERE topic = ?), "
            "last_updated = ? WHERE name = ?",
            (topic, self._now(), topic),
        )
        self._conn.commit()

    def search_topics(self, query: str, *, limit: int = 10) -> list[dict]:
        words = self._keywords(query)
        if not words:
            return []
        where = " OR ".join(
            "(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)" for _ in words
        )
        params: list[str] = []
        for w in words:
            p = f"%{w}%"
            params.extend([p, p])
        rows = self._conn.execute(
            f"SELECT * FROM topics WHERE {where} "
            "ORDER BY paper_count DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_topic_papers(self, topic: str, *, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT p.* FROM papers p "
            "JOIN paper_topics pt ON p.arxiv_id = pt.arxiv_id "
            "WHERE pt.topic = ? AND p.included=1 "
            "ORDER BY p.report_date DESC LIMIT ?",
            (topic, limit),
        ).fetchall()
        return [self._paper_dict(r) for r in rows]

    def get_all_topics(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM topics ORDER BY paper_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── free-form entries ──────────────────────────────────────

    def record_entry(self, key: str, value: str, category: str) -> None:
        self._conn.execute(
            """INSERT INTO entries (key, value, category, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   category=excluded.category,
                   updated_at=excluded.updated_at""",
            (key, value, category, self._now()),
        )
        self._conn.commit()

    def search_entries(
        self, query: str, *, category: str = "", limit: int = 10
    ) -> list[dict]:
        words = self._keywords(query)
        if not words:
            return []
        where = " AND ".join(
            "(LOWER(key) LIKE ? OR LOWER(value) LIKE ?)" for _ in words
        )
        params: list[str] = []
        for w in words:
            p = f"%{w}%"
            params.extend([p, p])
        if category:
            where += " AND category = ?"
            params.append(category)
        rows = self._conn.execute(
            f"SELECT * FROM entries WHERE {where} "
            "ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── stats ──────────────────────────────────────────────────

    def stats(self) -> dict:
        def _count(sql: str) -> int:
            return self._conn.execute(sql).fetchone()[0]

        return {
            "total_papers": _count("SELECT COUNT(*) FROM papers"),
            "included_papers": _count(
                "SELECT COUNT(*) FROM papers WHERE included=1"
            ),
            "topics": _count("SELECT COUNT(*) FROM topics"),
            "entries": _count("SELECT COUNT(*) FROM entries"),
            "dates": _count(
                "SELECT COUNT(DISTINCT report_date) FROM papers WHERE included=1"
            ),
        }

    def close(self) -> None:
        self._conn.close()

    # ── helpers ────────────────────────────────────────────────

    @staticmethod
    def _keywords(query: str) -> list[str]:
        return [w.strip() for w in query.lower().split() if len(w.strip()) >= 2]

    @staticmethod
    def _paper_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for key in ("authors", "tags"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
