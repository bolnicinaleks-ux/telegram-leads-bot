import asyncio
import json
from datetime import datetime

import aiosqlite

from bot.utils import dt_to_str

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    username       TEXT,
    full_name      TEXT    NOT NULL,
    answers        TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'new',
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    synced_version INTEGER NOT NULL DEFAULT 0,
    sheet_row      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_leads_user ON leads(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);

-- Все карточки заявки в чатах админов: чтобы обновлять их при смене статуса
CREATE TABLE IF NOT EXISTS lead_messages (
    lead_id    INTEGER NOT NULL REFERENCES leads(id),
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (lead_id, chat_id, message_id)
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() не вызван")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def _write(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        async with self._lock:
            return await self.conn.execute(sql, params)

    async def create_lead(
        self, *, user_id: int, username: str | None, full_name: str, answers: dict, now: datetime
    ) -> int:
        ts = dt_to_str(now)
        cur = await self._write(
            """INSERT INTO leads (user_id, username, full_name, answers, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, full_name, json.dumps(answers, ensure_ascii=False), ts, ts),
        )
        return cur.lastrowid

    async def get_lead(self, lead_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM leads WHERE id = ?", (lead_id,))

    async def count_since(self, user_id: int, since: datetime) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) FROM leads WHERE user_id = ? AND created_at >= ?", (user_id, dt_to_str(since))
        )
        return row[0]

    async def user_leads(self, user_id: int, limit: int = 5) -> list[aiosqlite.Row]:
        return await self._fetchall(
            "SELECT * FROM leads WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        )

    async def recent_leads(self, limit: int = 10, status: str | None = None) -> list[aiosqlite.Row]:
        if status:
            return await self._fetchall(
                "SELECT * FROM leads WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)
            )
        return await self._fetchall("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,))

    async def all_leads(self) -> list[aiosqlite.Row]:
        return await self._fetchall("SELECT * FROM leads ORDER BY id")

    async def set_status(self, lead_id: int, status: str, now: datetime) -> bool:
        cur = await self._write(
            """UPDATE leads SET status = ?, updated_at = ?, version = version + 1
               WHERE id = ? AND status != ?""",
            (status, dt_to_str(now), lead_id, status),
        )
        return cur.rowcount > 0

    async def add_message(self, lead_id: int, chat_id: int, message_id: int) -> None:
        await self._write(
            "INSERT OR IGNORE INTO lead_messages (lead_id, chat_id, message_id) VALUES (?, ?, ?)",
            (lead_id, chat_id, message_id),
        )

    async def lead_messages(self, lead_id: int) -> list[aiosqlite.Row]:
        return await self._fetchall("SELECT chat_id, message_id FROM lead_messages WHERE lead_id = ?", (lead_id,))

    # --- Синхронизация с Google Sheets ---

    async def unsynced(self, limit: int = 50) -> list[aiosqlite.Row]:
        return await self._fetchall(
            "SELECT * FROM leads WHERE synced_version < version ORDER BY id LIMIT ?", (limit,)
        )

    async def mark_synced(self, lead_id: int, version: int, sheet_row: int) -> None:
        # Ставим именно ту версию, что выгрузили: если статус успели сменить, запись останется в очереди.
        await self._write(
            "UPDATE leads SET synced_version = MAX(synced_version, ?), sheet_row = ? WHERE id = ?",
            (version, sheet_row, lead_id),
        )
