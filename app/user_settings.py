"""
Налаштування (SQLite через aiosqlite).

  * get_setting / set_setting — персональні налаштування (style, system_prompt, cta_hint ...).
    Якщо в існуючій таблиці user_settings є колонка з такою назвою — користуємось нею
    (так зберігаються старі значення); інакше — таблиця kv_settings.
  * get_settings / toggle_setting — перемикачі «текст на відео» і «звук»
    (окрема таблиця user_toggles, щоб не конфліктувати зі старою user_settings).

Усі функції async.
"""
import os

import aiosqlite

from . import config


def _resolve_db_path() -> str:
    for name in ("DB_PATH", "DB_FILE", "DATABASE_PATH", "DB_NAME"):
        v = getattr(config, name, None)
        if v:
            return str(v)
    return os.getenv("DB_PATH", "data/bot.db")


DB_PATH = _resolve_db_path()

_LEGACY = "user_settings"      # стара таблиця проєкту (не змінюємо її структуру)
_TOGGLES = "user_toggles"      # наша таблиця для перемикачів
_FIELDS = ("text_on", "audio_on")

DEFAULT_PROMPT = (
    "Ты — сценарист коротких вирусных вертикальных видео в нише "
    "арбитража трафика, заработка в интернете и мотивации. "
    "Пиши коротко, цепляюще, на русском языке, без воды и без эмодзи. "
    "Каждая фраза — не больше 8 слов."
)
DEFAULT_CTA = "Подписывайся, чтобы не пропустить"


async def init_user_settings() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TOGGLES} (
                user_id  INTEGER PRIMARY KEY,
                text_on  INTEGER NOT NULL DEFAULT 1,
                audio_on INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_settings (
                user_id INTEGER NOT NULL DEFAULT 0,
                key     TEXT    NOT NULL,
                value   TEXT,
                PRIMARY KEY (user_id, key)
            )
            """
        )
        await db.commit()


# ---------- перемикачі текст / звук ----------

async def get_settings(user_id: int) -> dict:
    await init_user_settings()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"INSERT OR IGNORE INTO {_TOGGLES} (user_id) VALUES (?)", (user_id,))
        await db.commit()
        cur = await db.execute(
            f"SELECT text_on, audio_on FROM {_TOGGLES} WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
    return {"text_on": bool(row[0]), "audio_on": bool(row[1])}


async def toggle_setting(user_id: int, field: str) -> dict:
    if field not in _FIELDS:
        raise ValueError(f"unknown setting: {field}")
    await init_user_settings()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"INSERT OR IGNORE INTO {_TOGGLES} (user_id) VALUES (?)", (user_id,))
        await db.execute(
            f"UPDATE {_TOGGLES} SET {field} = 1 - {field} WHERE user_id = ?", (user_id,)
        )
        await db.commit()
    return await get_settings(user_id)


# ---------- персональні налаштування ключ-значення ----------
#   await get_setting(user_id, "style")
#   await get_setting(user_id, "style", "default")
#   await get_setting("style")            -> глобальне (user_id = 0)

def _split_args(a, b, c):
    if isinstance(a, int):
        return a, b, c
    return 0, a, b


def _from_db_module(name: str, fallback: str) -> str:
    """Беремо значення з вашого db.py (напр. db.DEFAULT_PROMPT), якщо воно там є."""
    try:
        from . import db as _db
        return getattr(_db, name, fallback)
    except Exception:
        return fallback


def _builtin_default(key: str):
    k = str(key).lower()
    if k == "style":
        return _from_db_module("STYLE_DEFAULT", "cinematic")
    if "prompt" in k:
        return _from_db_module("DEFAULT_PROMPT", DEFAULT_PROMPT)
    if "cta" in k:
        return _from_db_module("DEFAULT_CTA", DEFAULT_CTA)
    return None


async def _legacy_columns(db) -> set[str]:
    try:
        cur = await db.execute(f"PRAGMA table_info({_LEGACY})")
        return {r[1] for r in await cur.fetchall()}
    except Exception:
        return set()


def _use_legacy(cols: set[str], user_id: int, key: str) -> bool:
    return bool(user_id) and "user_id" in cols and key in cols


async def get_setting(a, b=None, c=None):
    user_id, key, default = _split_args(a, b, c)
    key = str(key)
    await init_user_settings()
    async with aiosqlite.connect(DB_PATH) as db:
        value = None
        cols = await _legacy_columns(db)
        if _use_legacy(cols, user_id, key):
            cur = await db.execute(
                f'SELECT "{key}" FROM {_LEGACY} WHERE user_id = ?', (user_id,)
            )
            row = await cur.fetchone()
            value = row[0] if row else None
        if value in (None, ""):
            cur = await db.execute(
                "SELECT value FROM kv_settings WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
            row = await cur.fetchone()
            value = row[0] if row else None
    if value not in (None, ""):
        return value
    if default is not None:
        return default
    return _builtin_default(key)


async def set_setting(a, b, c=None):
    """set_setting(key, value) або set_setting(user_id, key, value)"""
    if isinstance(a, int) and c is not None:
        user_id, key, value = a, str(b), c
    else:
        user_id, key, value = 0, str(a), b
    value = None if value is None else str(value)
    await init_user_settings()
    async with aiosqlite.connect(DB_PATH) as db:
        cols = await _legacy_columns(db)
        if _use_legacy(cols, user_id, key):
            try:
                cur = await db.execute(
                    f'UPDATE {_LEGACY} SET "{key}" = ? WHERE user_id = ?', (value, user_id)
                )
                if cur.rowcount == 0:
                    await db.execute(
                        f'INSERT INTO {_LEGACY} (user_id, "{key}") VALUES (?, ?)',
                        (user_id, value),
                    )
                await db.commit()
                return
            except Exception:
                await db.rollback()  # не вийшло у старій таблиці — пишемо в kv
        await db.execute(
            "INSERT INTO kv_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, value),
        )
        await db.commit()
