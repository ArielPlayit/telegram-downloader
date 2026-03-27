import json
import sqlite3
from pathlib import Path
from typing import Iterable, Set


class WatcherStateRepository:
    def __init__(self, db_path: Path, legacy_state_path: Path | None = None) -> None:
        self.db_path = db_path
        self.legacy_state_path = legacy_state_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_state_if_needed()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watcher_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_messages (
                    message_id INTEGER PRIMARY KEY
                )
                """
            )
            conn.commit()

    def _migrate_legacy_state_if_needed(self) -> None:
        if not self.legacy_state_path or not self.legacy_state_path.exists():
            return

        if self.load_last_seen_id() != 0 or self.load_pending_ids():
            return

        try:
            legacy = json.loads(self.legacy_state_path.read_text(encoding="utf-8"))
            last_seen = int(legacy.get("last_seen_id", legacy.get("last_id", 0)) or 0)
            pending = [int(x) for x in legacy.get("pending_ids", [])]
            self.save_last_seen_id(last_seen)
            self.add_pending_ids(pending)
        except Exception:
            # Ignore malformed legacy state and keep DB defaults.
            pass

    def load_last_seen_id(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM watcher_state WHERE key = 'last_seen_id'"
            ).fetchone()
        if not row:
            return 0
        return int(row[0])

    def save_last_seen_id(self, last_seen_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watcher_state(key, value)
                VALUES('last_seen_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(int(last_seen_id)),),
            )
            conn.commit()

    def load_pending_ids(self) -> Set[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT message_id FROM pending_messages").fetchall()
        return {int(row[0]) for row in rows}

    def add_pending_id(self, message_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO pending_messages(message_id) VALUES(?)",
                (int(message_id),),
            )
            conn.commit()

    def add_pending_ids(self, message_ids: Iterable[int]) -> None:
        values = [(int(mid),) for mid in message_ids]
        if not values:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO pending_messages(message_id) VALUES(?)",
                values,
            )
            conn.commit()

    def remove_pending_id(self, message_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_messages WHERE message_id = ?", (int(message_id),))
            conn.commit()

    def set_pending_ids(self, message_ids: Set[int]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_messages")
            conn.executemany(
                "INSERT OR IGNORE INTO pending_messages(message_id) VALUES(?)",
                [(int(mid),) for mid in sorted(message_ids)],
            )
            conn.commit()
