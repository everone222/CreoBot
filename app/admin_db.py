import os
from datetime import datetime, timedelta

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "bot.db")
FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> str:
    return datetime.now().strftime(FMT)


async def init_admin_tables() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS adm_users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                full_name  TEXT,
                first_seen TEXT NOT NULL,
                last_seen  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS adm_logs (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL,
                username TEXT,
                action   TEXT NOT NULL,
                ts       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_adm_logs_user ON adm_logs(user_id);
            """
        )
        await db.commit()


async def touch_user(user_id: int, username: str | None, full_name: str | None) -> None:
    now = _now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO adm_users (user_id, username, full_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                last_seen = excluded.last_seen
            """,
            (user_id, username, full_name, now, now),
        )
        await db.commit()


async def log_action(user_id: int, username: str | None, action: str) -> None:
    """Викликай і зі свого коду, напр. log_action(uid, uname, 'video_done')."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO adm_logs (user_id, username, action, ts) VALUES (?, ?, ?, ?)",
            (user_id, username, action, _now()),
        )
        await db.commit()


async def get_stats() -> dict:
    now = datetime.now()
    day = now.strftime("%Y-%m-%d 00:00:00")
    week = (now - timedelta(days=7)).strftime(FMT)

    async with aiosqlite.connect(DB_PATH) as db:

        async def one(query: str, *args) -> int:
            cur = await db.execute(query, args)
            row = await cur.fetchone()
            return row[0] if row else 0

        stats = {
            "users": await one("SELECT COUNT(*) FROM adm_users"),
            "new_today": await one(
                "SELECT COUNT(*) FROM adm_users WHERE first_seen >= ?", day
            ),
            "new_week": await one(
                "SELECT COUNT(*) FROM adm_users WHERE first_seen >= ?", week
            ),
            "active_today": await one(
                "SELECT COUNT(*) FROM adm_users WHERE last_seen >= ?", day
            ),
            "active_week": await one(
                "SELECT COUNT(*) FROM adm_users WHERE last_seen >= ?", week
            ),
            "actions": await one("SELECT COUNT(*) FROM adm_logs"),
            "videos": await one(
                "SELECT COUNT(*) FROM adm_logs WHERE action = 'video_done'"
            ),
            "videos_today": await one(
                "SELECT COUNT(*) FROM adm_logs WHERE action = 'video_done' AND ts >= ?",
                day,
            ),
        }
        cur = await db.execute(
            """
            SELECT action, COUNT(*) AS c FROM adm_logs
            WHERE action LIKE 'btn:%'
            GROUP BY action ORDER BY c DESC LIMIT 5
            """
        )
        stats["top"] = await cur.fetchall()
    return stats


async def get_logs(page: int, per_page: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM adm_logs")
        total = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT ts, user_id, username, action FROM adm_logs "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        )
        rows = await cur.fetchall()
    return rows, total


async def get_users(page: int, per_page: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM adm_users")
        total = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT user_id, username, full_name, first_seen, last_seen "
            "FROM adm_users ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        )
        rows = await cur.fetchall()
    return rows, total


async def get_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM adm_users")
        return [r[0] for r in await cur.fetchall()]
