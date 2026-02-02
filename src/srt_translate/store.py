from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class TaskRecord:
    video_id: str
    video_path: str
    status: str
    payload: dict[str, Any]
    updated_at: int


import threading

class StateStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def __enter__(self) -> "StateStore":
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore not opened")
        return self._conn

    def _ensure_schema(self) -> None:
        with self._lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  video_id TEXT PRIMARY KEY,
                  video_path TEXT NOT NULL,
                  status TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  updated_at INTEGER NOT NULL
                );
                """
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
            self.conn.commit()

    def upsert_task(self, rec: TaskRecord) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO tasks(video_id, video_path, status, payload_json, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                  video_path=excluded.video_path,
                  status=excluded.status,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    rec.video_id,
                    rec.video_path,
                    rec.status,
                    json.dumps(rec.payload, ensure_ascii=False, separators=(",", ":")),
                    rec.updated_at,
                ),
            )
            self.conn.commit()

    def get_task(self, video_id: str) -> TaskRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT video_id, video_path, status, payload_json, updated_at FROM tasks WHERE video_id=?",
                (video_id,),
            ).fetchone()
            if row is None:
                return None
            return TaskRecord(
                video_id=row[0],
                video_path=row[1],
                status=row[2],
                payload=json.loads(row[3]),
                updated_at=int(row[4]),
            )

    def list_tasks_by_status(self, status: str, limit: int = 1000) -> list[TaskRecord]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT video_id, video_path, status, payload_json, updated_at FROM tasks WHERE status=? ORDER BY updated_at ASC LIMIT ?",
                (status, limit),
            ).fetchall()
            out: list[TaskRecord] = []
            for row in rows:
                out.append(
                    TaskRecord(
                        video_id=row[0],
                        video_path=row[1],
                        status=row[2],
                        payload=json.loads(row[3]),
                        updated_at=int(row[4]),
                    )
                )
            return out

