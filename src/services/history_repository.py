import json
import sqlite3
from pathlib import Path
from typing import Dict, List


class DownloadHistoryRepository:
    def __init__(self, db_path: Path, legacy_json_path: Path | None = None, max_rows: int = 1000) -> None:
        self.db_path = db_path
        self.legacy_json_path = legacy_json_path
        self.max_rows = max(1, int(max_rows))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_if_needed()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS download_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    message_id TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _migrate_legacy_if_needed(self) -> None:
        if not self.legacy_json_path or not self.legacy_json_path.exists():
            return

        if self.list_entries(limit=1):
            return

        try:
            data = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
        except Exception:
            return

        rows = []
        for item in data[: self.max_rows]:
            if not isinstance(item, dict):
                continue
            rows.append(
                (
                    str(item.get("timestamp", "")),
                    str(item.get("name", "")),
                    str(item.get("path", "")),
                    str(item.get("message_id", "")),
                )
            )

        if not rows:
            return

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO download_history(timestamp, name, path, message_id)
                VALUES(?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def add_entry(self, timestamp: str, name: str, path: str, message_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO download_history(timestamp, name, path, message_id)
                VALUES(?, ?, ?, ?)
                """,
                (timestamp, name, path, message_id),
            )
            # Keep only the most recent max_rows records.
            conn.execute(
                """
                DELETE FROM download_history
                WHERE id NOT IN (
                    SELECT id FROM download_history ORDER BY id DESC LIMIT ?
                )
                """,
                (self.max_rows,),
            )
            conn.commit()

    def list_entries(self, limit: int | None = None) -> List[Dict[str, str]]:
        query = "SELECT timestamp, name, path, message_id FROM download_history ORDER BY id DESC"
        params: tuple[int, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (max(1, int(limit)),)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "timestamp": str(row[0]),
                "name": str(row[1]),
                "path": str(row[2]),
                "message_id": str(row[3]),
            }
            for row in rows
        ]

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM download_history")
            conn.commit()
