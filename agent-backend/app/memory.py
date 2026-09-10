"""SQLite-backed conversation memory with a small, dependency-free API."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MemoryMessage:
    role: str
    content: str
    created_at: int


@dataclass(frozen=True)
class MemoryContext:
    summary: str
    messages: list[MemoryMessage]


class SQLiteMemoryStore:
    """Persistent conversation storage suitable for a single local agent process."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id);
                """
            )

    def create_or_get(self, conversation_id: str, user_id: str = "") -> str:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations(conversation_id, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id = CASE WHEN conversations.user_id = '' THEN excluded.user_id
                                   ELSE conversations.user_id END,
                    updated_at = excluded.updated_at
                """,
                (conversation_id, user_id, now, now),
            )
        return conversation_id

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conversations(conversation_id, created_at, updated_at) VALUES (?, ?, ?)",
                (conversation_id, now, now),
            )
            conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )

    def load_context(self, conversation_id: str, limit: int | None = 12) -> MemoryContext:
        with self._connect() as conn:
            conversation = conn.execute(
                "SELECT summary FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if limit is None:
                rows = conn.execute(
                    "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                    (conversation_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT role, content, created_at
                    FROM (
                        SELECT role, content, created_at, id
                        FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
                    ) ORDER BY id ASC
                    """,
                    (conversation_id, max(0, limit)),
                ).fetchall()
        return MemoryContext(
            summary=(conversation["summary"] if conversation else "") or "",
            messages=[MemoryMessage(row["role"], row["content"], row["created_at"]) for row in rows],
        )

    def save_summary(self, conversation_id: str, summary: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET summary = ?, updated_at = ? WHERE conversation_id = ?",
                (summary, now, conversation_id),
            )

    def trim_messages(self, conversation_id: str, keep: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ?
                  AND id NOT IN (
                    SELECT id FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
                  )
                """,
                (conversation_id, conversation_id, max(0, keep)),
            )

    def list_conversations(self, user_id: str = "", limit: int = 50) -> list[dict]:
        where = "WHERE c.user_id = ?" if user_id else ""
        params: tuple = (user_id, max(1, limit)) if user_id else (max(1, limit),)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.conversation_id, c.user_id, c.summary, c.created_at, c.updated_at,
                       COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.conversation_id
                {where}
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]


class MySQLMemoryStore:
    """MySQL-backed conversation storage for shared/local deployments."""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        import pymysql

        self._pymysql = pymysql
        self._config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "charset": "utf8mb4",
            "autocommit": True,
            "cursorclass": pymysql.cursors.DictCursor,
        }
        self._initialize()

    def _connect(self):
        return self._pymysql.connect(**self._config)

    def _initialize(self) -> None:
        bootstrap = self._pymysql.connect(
            host=self._config["host"], port=self._config["port"], user=self._config["user"],
            password=self._config["password"], charset="utf8mb4", autocommit=True,
            cursorclass=self._pymysql.cursors.DictCursor,
        )
        try:
            with bootstrap.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self._config['database']}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            bootstrap.close()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        conversation_id VARCHAR(191) PRIMARY KEY,
                        user_id VARCHAR(191) NOT NULL DEFAULT '',
                        summary TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        updated_at BIGINT NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        conversation_id VARCHAR(191) NOT NULL,
                        role VARCHAR(32) NOT NULL,
                        content MEDIUMTEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        INDEX idx_messages_conversation(conversation_id, id),
                        CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id)
                            REFERENCES conversations(conversation_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )

    def create_or_get(self, conversation_id: str, user_id: str = "") -> str:
        now = int(time.time())
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations(conversation_id,user_id,summary,created_at,updated_at)
                    VALUES (%s,%s,'',%s,%s)
                    ON DUPLICATE KEY UPDATE
                      user_id=IF(conversations.user_id='',VALUES(user_id),conversations.user_id),
                      updated_at=VALUES(updated_at)
                    """,
                    (conversation_id, user_id, now, now),
                )
        return conversation_id

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT IGNORE INTO conversations(conversation_id,summary,created_at,updated_at) VALUES (%s,'',%s,%s)",
                    (conversation_id, now, now),
                )
                cursor.execute(
                    "INSERT INTO messages(conversation_id,role,content,created_at) VALUES (%s,%s,%s,%s)",
                    (conversation_id, role, content, now),
                )
                cursor.execute("UPDATE conversations SET updated_at=%s WHERE conversation_id=%s", (now, conversation_id))

    def load_context(self, conversation_id: str, limit: int | None = 12) -> MemoryContext:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT summary FROM conversations WHERE conversation_id=%s", (conversation_id,))
                conversation = cursor.fetchone()
                if limit is None:
                    cursor.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=%s ORDER BY id", (conversation_id,))
                else:
                    cursor.execute(
                        "SELECT role,content,created_at FROM (SELECT role,content,created_at,id FROM messages WHERE conversation_id=%s ORDER BY id DESC LIMIT %s) x ORDER BY id",
                        (conversation_id, max(0, limit)),
                    )
                rows = cursor.fetchall()
        return MemoryContext(
            summary=(conversation or {}).get("summary", "") or "",
            messages=[MemoryMessage(row["role"], row["content"], row["created_at"]) for row in rows],
        )

    def save_summary(self, conversation_id: str, summary: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE conversations SET summary=%s,updated_at=%s WHERE conversation_id=%s", (summary, int(time.time()), conversation_id))

    def trim_messages(self, conversation_id: str, keep: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM messages WHERE conversation_id=%s AND id NOT IN (SELECT id FROM (SELECT id FROM messages WHERE conversation_id=%s ORDER BY id DESC LIMIT %s) x)",
                    (conversation_id, conversation_id, max(0, keep)),
                )

    def list_conversations(self, user_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                if user_id:
                    cursor.execute(
                        "SELECT c.conversation_id,c.user_id,c.summary,c.created_at,c.updated_at,COUNT(m.id) message_count FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.conversation_id WHERE c.user_id=%s GROUP BY c.conversation_id ORDER BY c.updated_at DESC LIMIT %s",
                        (user_id, max(1, limit)),
                    )
                else:
                    cursor.execute(
                        "SELECT c.conversation_id,c.user_id,c.summary,c.created_at,c.updated_at,COUNT(m.id) message_count FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.conversation_id GROUP BY c.conversation_id ORDER BY c.updated_at DESC LIMIT %s",
                        (max(1, limit),),
                    )
                return list(cursor.fetchall())
