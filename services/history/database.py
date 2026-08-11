from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional


class HistoryDatabase:
    def __init__(self, db_path: str = "talksync.db"):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                created_at TEXT,
                duration_seconds REAL,
                blocks TEXT,
                starred INTEGER DEFAULT 0,
                folder TEXT DEFAULT ''
            )
        """)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN starred INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN folder TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def save_session(self, title: str, blocks: list[dict]) -> int:
        if self._conn is None:
            self.connect()
        cursor = self._conn.execute(
            "INSERT INTO sessions (title, created_at, blocks) VALUES (?, ?, ?)",
            (title, datetime.now().isoformat(), json.dumps(blocks)),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_sessions(self, limit: int = 50, folder: str = "") -> list[dict]:
        if self._conn is None:
            self.connect()
        if folder:
            cursor = self._conn.execute(
                "SELECT id, title, created_at, starred, folder FROM sessions WHERE folder = ? ORDER BY created_at DESC LIMIT ?",
                (folder, limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT id, title, created_at, starred, folder FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [
            {"id": r[0], "title": r[1], "created_at": r[2], "starred": bool(r[3]), "folder": r[4] or ""}
            for r in cursor.fetchall()
        ]

    def load_session(self, session_id: int) -> Optional[dict]:
        if self._conn is None:
            self.connect()
        cursor = self._conn.execute(
            "SELECT title, created_at, duration_seconds, blocks, starred, folder FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "title": row[0],
            "created_at": row[1],
            "duration_seconds": row[2],
            "blocks": json.loads(row[3]) if row[3] else [],
            "starred": bool(row[4]),
            "folder": row[5] or "",
        }

    def delete_session(self, session_id: int) -> None:
        if self._conn is None:
            self.connect()
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    def star_session(self, session_id: int) -> None:
        if self._conn is None:
            self.connect()
        self._conn.execute("UPDATE sessions SET starred = 1 WHERE id = ?", (session_id,))
        self._conn.commit()

    def unstar_session(self, session_id: int) -> None:
        if self._conn is None:
            self.connect()
        self._conn.execute("UPDATE sessions SET starred = 0 WHERE id = ?", (session_id,))
        self._conn.commit()

    def list_starred_sessions(self, limit: int = 50) -> list[dict]:
        if self._conn is None:
            self.connect()
        cursor = self._conn.execute(
            "SELECT id, title, created_at, starred, folder FROM sessions WHERE starred = 1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": r[0], "title": r[1], "created_at": r[2], "starred": True, "folder": r[4] or ""}
            for r in cursor.fetchall()
        ]

    def set_session_folder(self, session_id: int, folder: str) -> None:
        if self._conn is None:
            self.connect()
        self._conn.execute("UPDATE sessions SET folder = ? WHERE id = ?", (folder, session_id))
        self._conn.commit()

    def list_folders(self) -> list[str]:
        if self._conn is None:
            self.connect()
        cursor = self._conn.execute("SELECT DISTINCT folder FROM sessions WHERE folder != ''")
        return [r[0] for r in cursor.fetchall()]

    def get_session_segments(self, session_id: int) -> list[dict]:
        session = self.load_session(session_id)
        if session and "blocks" in session:
            return session["blocks"]
        return []

    def get_all_sessions(self) -> list[dict]:
        return self.list_sessions(limit=1000)


def get_database(db_path: str = "talksync.db") -> HistoryDatabase:
    db = HistoryDatabase(db_path)
    db.connect()
    return db
