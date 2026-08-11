"""
SQLite persistence for contacts, rooms and messages.
Both peers store the conversation so history survives offline periods.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class Storage:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base = Path.home() / ".p2p_chat"
            base.mkdir(parents=True, exist_ok=True)
            db_path = str(base / "chat.db")
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        c = self._conn.cursor()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS contacts (
                peer_id    TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                last_ip    TEXT,
                last_port  INTEGER,
                last_seen  REAL,
                note       TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS rooms (
                room_id    TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                is_group   INTEGER DEFAULT 0,
                created_at REAL,
                last_active REAL
            );

            CREATE TABLE IF NOT EXISTS room_members (
                room_id  TEXT,
                peer_id  TEXT,
                username TEXT,
                PRIMARY KEY (room_id, peer_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                msg_id     TEXT PRIMARY KEY,
                room_id    TEXT NOT NULL,
                sender     TEXT NOT NULL,
                msg_type   TEXT NOT NULL,          -- text | voice
                content    TEXT,                   -- text body or path to voice file
                timestamp  REAL NOT NULL,
                delivered  INTEGER DEFAULT 0,
                FOREIGN KEY (room_id) REFERENCES rooms(room_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_room_ts
                ON messages(room_id, timestamp);
            """
        )
        self._conn.commit()

    # ── Settings ──────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)",
            (key, value),
        )
        self._conn.commit()

    # ── Contacts ──────────────────────────────────────────────

    def upsert_contact(
        self,
        peer_id: str,
        username: str,
        ip: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO contacts(peer_id, username, last_ip, last_port, last_seen)
            VALUES(?,?,?,?,?)
            ON CONFLICT(peer_id) DO UPDATE SET
                username=excluded.username,
                last_ip=COALESCE(excluded.last_ip, contacts.last_ip),
                last_port=COALESCE(excluded.last_port, contacts.last_port),
                last_seen=excluded.last_seen
            """,
            (peer_id, username, ip, port, now),
        )
        self._conn.commit()

    def list_contacts(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM contacts ORDER BY last_seen DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contact(self, peer_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE peer_id=?", (peer_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── Rooms ─────────────────────────────────────────────────

    def create_room(
        self, name: str, is_group: bool = False, room_id: Optional[str] = None
    ) -> str:
        rid = room_id or str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO rooms(room_id, name, is_group, created_at, last_active)
            VALUES(?,?,?,?,?)
            """,
            (rid, name, int(is_group), now, now),
        )
        self._conn.commit()
        return rid

    def list_rooms(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM rooms ORDER BY last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM rooms WHERE room_id=?", (room_id,)
        ).fetchone()
        return dict(row) if row else None

    def touch_room(self, room_id: str) -> None:
        self._conn.execute(
            "UPDATE rooms SET last_active=? WHERE room_id=?",
            (time.time(), room_id),
        )
        self._conn.commit()

    def add_member(self, room_id: str, peer_id: str, username: str) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO room_members(room_id, peer_id, username)
            VALUES(?,?,?)
            """,
            (room_id, peer_id, username),
        )
        self._conn.commit()

    def list_members(self, room_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM room_members WHERE room_id=?", (room_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Messages ──────────────────────────────────────────────

    def save_message(
        self,
        room_id: str,
        sender: str,
        msg_type: str,
        content: str,
        msg_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        delivered: bool = False,
    ) -> str:
        mid = msg_id or str(uuid.uuid4())
        ts = timestamp if timestamp is not None else time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO messages
                (msg_id, room_id, sender, msg_type, content, timestamp, delivered)
            VALUES(?,?,?,?,?,?,?)
            """,
            (mid, room_id, sender, msg_type, content, ts, int(delivered)),
        )
        self.touch_room(room_id)
        self._conn.commit()
        return mid

    def get_messages(
        self, room_id: str, limit: int = 200, before_ts: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        if before_ts:
            rows = self._conn.execute(
                """
                SELECT * FROM messages
                WHERE room_id=? AND timestamp < ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (room_id, before_ts, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM messages
                WHERE room_id=?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (room_id, limit),
            ).fetchall()
        result = [dict(r) for r in reversed(rows)]
        return result

    def mark_delivered(self, msg_id: str) -> None:
        self._conn.execute(
            "UPDATE messages SET delivered=1 WHERE msg_id=?", (msg_id,)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
