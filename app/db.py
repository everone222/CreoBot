import aiosqlite

from .config import DB_PATH

DEFAULT_PROMPT = (
    "Ты — сценарист вирусных коротких видео (TikTok, Reels, Shorts) в нише "
    "арбитража трафика, заработка и мотивации. Пиши на русском, современным, "
    "дерзким языком, бей в боли аудитории (мало денег, нелюбимая работа, нет "
    "времени, чужие успехи) и в мотивацию. Без хэштегов и эмодзи. "
    "Не обещай гарантированный доход и не называй конкретные суммы."
)

STYLE_DEFAULT = "cinematic"

DEFAULTS = {
    "system_prompt": DEFAULT_PROMPT,
    "style": STYLE_DEFAULT,
    "cta_hint": "Переходи в Telegram, ссылка в профиле",
}


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS tracks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE)"
        )
        for k, v in DEFAULTS.items():
            await db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        await db.commit()


async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
    return row[0] if row else DEFAULTS[key]


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def add_track(name: str, path: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR REPLACE INTO tracks(name, path) VALUES (?, ?)", (name, path)
        )
        await db.commit()
        return cur.lastrowid


async def list_tracks() -> list[tuple[int, str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name, path FROM tracks ORDER BY id")
        return await cur.fetchall()


async def delete_track(track_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT path FROM tracks WHERE id = ?", (track_id,))
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        await db.commit()
        return row[0]


async def random_track() -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT path FROM tracks ORDER BY RANDOM() LIMIT 1")
        row = await cur.fetchone()
    return row[0] if row else None
