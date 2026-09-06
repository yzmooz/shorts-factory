from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import AppConfig


class QueueStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                uploaded_at TEXT,
                youtube_id TEXT
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def fingerprint(topic: str) -> str:
        normalized = " ".join(topic.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def add(self, topic: str, output_dir: Path) -> int:
        cursor = self.connection.execute(
            "INSERT INTO videos(fingerprint, topic, output_dir, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (self.fingerprint(topic), topic, str(output_dir), "draft", _now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def exists(self, topic: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM videos WHERE fingerprint = ?", (self.fingerprint(topic),)
        ).fetchone()
        return row is not None

    def get(self, item_id: int) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM videos WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"В очереди нет ID {item_id}")
        return row

    def mark_uploaded(self, item_id: int, youtube_id: str) -> None:
        self.connection.execute(
            "UPDATE videos SET status = 'uploaded', uploaded_at = ?, youtube_id = ? WHERE id = ?",
            (_now(), youtube_id, item_id),
        )
        self.connection.commit()

    def can_upload(self, config: AppConfig) -> tuple[bool, str]:
        automation = config.section("automation")
        today = datetime.now(UTC).date().isoformat()
        count = self.connection.execute(
            "SELECT COUNT(*) AS n FROM videos WHERE uploaded_at LIKE ?", (today + "%",)
        ).fetchone()["n"]
        if count >= int(automation["max_uploads_per_day"]):
            return False, "достигнут дневной лимит публикаций"
        latest = self.connection.execute(
            "SELECT uploaded_at FROM videos WHERE uploaded_at IS NOT NULL ORDER BY uploaded_at DESC LIMIT 1"
        ).fetchone()
        if latest:
            last = datetime.fromisoformat(latest["uploaded_at"])
            earliest = last + timedelta(hours=float(automation["min_hours_between_uploads"]))
            if datetime.now(UTC) < earliest:
                return False, f"следующая загрузка разрешена после {earliest.isoformat()}"
        return True, "ok"

    def rows(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM videos ORDER BY id DESC"))


def _now() -> str:
    return datetime.now(UTC).isoformat()
