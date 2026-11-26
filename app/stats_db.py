import aiosqlite
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config

DB_PATH = getattr(config, "DB_PATH", "data/bot.db")
UTC = timezone.utc

# На Windows для ZoneInfo потрібен пакет tzdata (pip install tzdata); є запасний варіант
try:
    LOCAL_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    try:
        LOCAL_TZ = ZoneInfo("Europe/Kiev")
    except Exception:
        LOCAL_TZ = timezone(timedelta(hours=2))


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _now() -> str:
    return _fmt(datetime.now(UTC))


def to_local(ts: str) -> str:
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")


async def init_stats_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                full_name     TEXT,
                first_seen    TEXT NOT NULL,
                last_seen     TEXT NOT NULL,
                actions_count INTEGER NOT NULL DEFAULT 0,
                videos_count  INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS action_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                username   TEXT,
                full_name  TEXT,
                is_admin   INTEGER NOT NULL DEFAULT 0,
                action     TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_logs_created ON action_logs(created_at DESC);
            """
        )
        await db.commit()


async def track(user_id: int, username: str | None, full_name: str,
                action: str | None, is_admin: bool) -> None:
    now = _now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO bot_users (user_id, username, full_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                last_seen = excluded.last_seen
            """,
            (user_id, username, full_name, now, now),
        )
        if action:
            await db.execute(
                "INSERT INTO action_logs (user_id, username, full_name, is_admin, action, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, full_name, int(is_admin), action, now),
            )
            await db.execute(
                "UPDATE bot_users SET actions_count = actions_count + 1 WHERE user_id = ?",
                (user_id,),
            )
        await db.commit()


async def inc_videos(user_id: int) -> None:
    """Виклич після успішно зробленого відео."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE bot_users SET videos_count = videos_count + 1 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def get_stats() -> dict:
    now = datetime.now(UTC)
    midnight = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today = _fmt(midnight.astimezone(UTC))
    day_ago = _fmt(now - timedelta(days=1))
    week_ago = _fmt(now - timedelta(days=7))

    async with aiosqlite.connect(DB_PATH) as db:
        async def one(sql: str, *args) -> int:
            cur = await db.execute(sql, args)
            return (await cur.fetchone())[0] or 0

        stats = {
            "total_users": await one("SELECT COUNT(*) FROM bot_users"),
            "new_today": await one("SELECT COUNT(*) FROM bot_users WHERE first_seen >= ?", today),
            "active_24h": await one("SELECT COUNT(*) FROM bot_users WHERE last_seen >= ?", day_ago),
            "active_7d": await one("SELECT COUNT(*) FROM bot_users WHERE last_seen >= ?", week_ago),
            "total_actions": await one("SELECT COUNT(*) FROM action_logs"),
            "total_videos": await one("SELECT SUM(videos_count) FROM bot_users"),
        }
        cur = await db.execute(
            "SELECT action, COUNT(*) FROM action_logs "
            "WHERE action LIKE 'btn:%' AND action NOT LIKE 'btn:adm:%' GROUP BY action"
        )
        stats["buttons"] = await cur.fetchall()
    return stats


async def get_users_page(page: int, per_page: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM bot_users")
        total = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT user_id, username, full_name, last_seen, actions_count, videos_count "
            "FROM bot_users ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        )
        return await cur.fetchall(), total


async def get_logs_page(page: int, per_page: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM action_logs")
        total = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT user_id, username, full_name, is_admin, action, created_at "
            "FROM action_logs ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        )
        return await cur.fetchall(), total
