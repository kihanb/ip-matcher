"""Persistent SQLite storage for system snapshots, saved profiles, and audit logs."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH


class ProfileStore:
    """Thread-safe store for Windows configuration snapshots, custom profiles, and logs."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('baseline', 'auto', 'custom')),
                    is_pinned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    ip_address TEXT DEFAULT '',
                    country_code TEXT DEFAULT '',
                    country_name TEXT DEFAULT '',
                    state_json TEXT NOT NULL,
                    notes TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details_json TEXT DEFAULT '{}'
                );
                """
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "is_pinned": bool(row["is_pinned"]),
            "created_at": row["created_at"],
            "ip_address": row["ip_address"],
            "country_code": row["country_code"],
            "country_name": row["country_name"],
            "state": json.loads(row["state_json"]),
            "notes": row["notes"],
        }

    def has_baseline(self) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE kind = 'baseline' LIMIT 1"
            ).fetchone()
            return row is not None

    def get_baseline(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE kind = 'baseline' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            return self._row_to_snapshot(row) if row else None

    def ensure_baseline(
        self,
        state: dict[str, Any],
        ip_address: str = "",
        country_code: str = "",
        country_name: str = "",
    ) -> dict[str, Any]:
        """Capture the original system configuration on first run if not yet stored."""
        existing = self.get_baseline()
        if existing:
            return existing
        return self.save_snapshot(
            name="تنظیمات اولیه سیستم (پیش‌فرض اصلی)",
            kind="baseline",
            state=state,
            is_pinned=True,
            ip_address=ip_address,
            country_code=country_code,
            country_name=country_name,
            notes="ذخیره‌شده به‌صورت خودکار پیش از هرگونه تغییر در سیستم",
        )

    def save_snapshot(
        self,
        name: str,
        kind: str,
        state: dict[str, Any],
        is_pinned: bool = False,
        ip_address: str = "",
        country_code: str = "",
        country_name: str = "",
        notes: str = "",
        max_auto_keep: int = 30,
    ) -> dict[str, Any]:
        """Save a system configuration snapshot or custom profile."""
        snap_id = str(uuid.uuid4())[:12]
        created_at = self._now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    id, name, kind, is_pinned, created_at,
                    ip_address, country_code, country_name, state_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap_id,
                    name,
                    kind,
                    1 if is_pinned else 0,
                    created_at,
                    ip_address,
                    country_code,
                    country_name,
                    json.dumps(state, ensure_ascii=False),
                    notes,
                ),
            )
            if kind == "auto" and max_auto_keep > 0:
                conn.execute(
                    """
                    DELETE FROM snapshots
                    WHERE kind = 'auto' AND is_pinned = 0 AND id NOT IN (
                        SELECT id FROM snapshots
                        WHERE kind = 'auto' AND is_pinned = 0
                        ORDER BY created_at DESC, rowid DESC
                        LIMIT ?
                    )
                    """,
                    (max_auto_keep,),
                )
        return self.get_snapshot(snap_id)  # type: ignore[return-value]

    def get_snapshot(self, snap_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snap_id,)
            ).fetchone()
            return self._row_to_snapshot(row) if row else None

    def get_latest_auto_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent auto-saved pre-change snapshot for 1-click Undo."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE kind = 'auto' ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            return self._row_to_snapshot(row) if row else None

    def list_snapshots(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM snapshots WHERE kind = ? ORDER BY is_pinned DESC, created_at DESC, rowid DESC",
                    (kind,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM snapshots ORDER BY CASE kind WHEN 'baseline' THEN 0 WHEN 'custom' THEN 1 ELSE 2 END, is_pinned DESC, created_at DESC, rowid DESC"
                ).fetchall()
            return [self._row_to_snapshot(r) for r in rows]

    def delete_snapshot(self, snap_id: str) -> bool:
        """Delete a non-baseline snapshot/profile."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT kind FROM snapshots WHERE id = ?", (snap_id,)
            ).fetchone()
            if not row or row["kind"] == "baseline":
                return False
            cur = conn.execute("DELETE FROM snapshots WHERE id = ?", (snap_id,))
            return cur.rowcount > 0

    def rename_snapshot(self, snap_id: str, new_name: str, notes: str | None = None) -> bool:
        with self._lock, self._connect() as conn:
            if notes is None:
                cur = conn.execute(
                    "UPDATE snapshots SET name = ? WHERE id = ?", (new_name, snap_id)
                )
            else:
                cur = conn.execute(
                    "UPDATE snapshots SET name = ?, notes = ? WHERE id = ?",
                    (new_name, notes, snap_id),
                )
            return cur.rowcount > 0

    def export_profiles_json(self) -> str:
        items = self.list_snapshots()
        return json.dumps(items, indent=2, ensure_ascii=False)

    def import_profiles_json(self, raw_json: str) -> int:
        data = json.loads(raw_json)
        if not isinstance(data, list):
            raise ValueError("Invalid profiles JSON: expected a list")
        imported = 0
        for item in data:
            if not isinstance(item, dict) or "state" not in item or "name" not in item:
                continue
            kind = item.get("kind", "custom")
            if kind == "baseline":
                kind = "custom"
            self.save_snapshot(
                name=str(item["name"]),
                kind=kind if kind in ("auto", "custom") else "custom",
                state=dict(item["state"]),
                is_pinned=bool(item.get("is_pinned", False)),
                ip_address=str(item.get("ip_address", "")),
                country_code=str(item.get("country_code", "")),
                country_name=str(item.get("country_name", "")),
                notes=str(item.get("notes", "")),
            )
            imported += 1
        return imported

    def add_log(
        self,
        action: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (timestamp, action, status, summary, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self._now_iso(),
                    action,
                    status,
                    summary,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            # Keep last 200 log entries
            conn.execute(
                """
                DELETE FROM audit_log
                WHERE id NOT IN (
                    SELECT id FROM audit_log ORDER BY id DESC LIMIT 200
                )
                """
            )

    def list_logs(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "action": r["action"],
                    "status": r["status"],
                    "summary": r["summary"],
                    "details": json.loads(r["details_json"] or "{}"),
                }
                for r in rows
            ]
