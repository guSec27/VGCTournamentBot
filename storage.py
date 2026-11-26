"""Small SQLite persistence layer for subscriptions and delivery deduplication."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    region TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS seen_events (
                    chat_id INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    PRIMARY KEY (chat_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS monthly_recaps (
                    chat_id INTEGER NOT NULL,
                    month TEXT NOT NULL,
                    PRIMARY KEY (chat_id, month)
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def set_region(self, chat_id: int, region: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO subscribers(chat_id, region) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET region=excluded.region",
                (chat_id, region),
            )

    def get_region(self, chat_id: int) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT region FROM subscribers WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] if row else None

    def subscribers(self) -> list[tuple[int, str]]:
        with self._connect() as db:
            return list(db.execute("SELECT chat_id, region FROM subscribers"))

    def was_seen(self, chat_id: int, event_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM seen_events WHERE chat_id=? AND event_id=?", (chat_id, event_id)
            ).fetchone()
        return row is not None

    def mark_seen(self, chat_id: int, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with self._connect() as db:
            db.executemany(
                "INSERT OR IGNORE INTO seen_events(chat_id, event_id) VALUES (?, ?)",
                [(chat_id, event_id) for event_id in event_ids],
            )

    def recap_sent(self, chat_id: int, month: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM monthly_recaps WHERE chat_id=? AND month=?", (chat_id, month)
            ).fetchone()
        return row is not None

    def mark_recap_sent(self, chat_id: int, month: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO monthly_recaps(chat_id, month) VALUES (?, ?)",
                (chat_id, month),
            )
