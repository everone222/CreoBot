"""Розсилка всім користувачам + повідомлення одному користувачу (тільки для адмінів).

Нічого не змінює в існуючому коді: свій роутер, свій фільтр адміна.
Користувачів бере з твоєї SQLite (таблиці зі стовпцями user_id / tg_id / telegram_id).
"""
import asyncio
import logging
import os
import sqlite3
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from . import config

log = logging.getLogger(__name__)

ID_COLUMNS = ("user_id", "tg_id", "telegram_id")
SKIP_DIRS = {"venv", ".venv", "site-packages", "node_modules", ".git"}


# ---------- адміни ----------

def is_admin(user_id: int) -> bool:
    ids = getattr(config, "ADMIN_IDS", None)
    if ids is None:
        raw = os.getenv("ADMIN_IDS", "").replace(";", ",")
        ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    try:
        return user_id in {int(i) for i in ids}
    except (TypeError, ValueError):
        return False


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return bool(event.from_user and is_admin(event.from_user.id))


# ---------- пошук користувачів у базі ----------

def _db_paths() -> list[str]:
    paths: list[str] = []
    for name in ("DB_PATH", "DB_FILE", "DATABASE", "DB_NAME", "STATS_DB_PATH"):
        value = getattr(config, name, None)
        if isinstance(value, (str, os.PathLike)) and os.path.exists(value):
            paths.append(str(value))
    if not paths:  # конфіг не підказав — шукаємо *.db у проєкті
        for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
            for p in Path.cwd().rglob(pattern):
                if not SKIP_DIRS.intersection(p.parts):
                    paths.append(str(p))
    return list(dict.fromkeys(paths))


def _collect_ids() -> tuple[set[int], list[str]]:
    ids: set[int] = set()
    sources: list[str] = []
    for path in _db_paths():
        try:
            con = sqlite3.connect(path)
        except sqlite3.Error:
            continue
        try:
            tables = [
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in tables:
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
                col = next((c for c in ID_COLUMNS if c in cols), None)
                if col is None and table.lower() in ("users", "user") and "id" in cols:
                    col = "id"
                if col is None:
                    continue
                found = 0
                for (value,) in con.execute(f'SELECT DISTINCT "{col}" FROM "{table}"'):
                    if isinstance(value, int) and value > 0:
                        ids.add(value)
                        found += 1
                if found:
                    sources.append(f"{Path(path).name}:{table}.{col}")
        except sqlite3.Error:
            log.exception("read %s failed", path)
        finally:
            con.close()
    return ids, sources


async def get_user_ids() -> tuple[set[int], list[str]]:
    return await asyncio.to_thread(_collect_ids)


# ---------- відправка ----------

async def _copy_to(bot: Bot, uid: int, from_chat: int, msg_id: int) -> str:
    """ok | blocked | fail. copy_message зберігає текст/фото/відео з підписом."""
    try:
        await bot.copy_message(uid, from_chat, msg_id)
        return "ok"
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await _copy_to(bot, uid, from_chat, msg_id)
    except TelegramForbiddenError:
        return "blocked"
    except Exception:
        log.exception("send to %s failed", uid)
        return "fail"


_bg_tasks: set[asyncio.Task] = set()


async def _run_broadcast(bot: Bot, admin_chat: int, ids: list[int], data: dict) -> None:
    sem = asyncio.Semaphore(20)
    counts = {"ok": 0, "blocked": 0, "fail": 0}

    async def worker(uid: int) -> None:
        async with sem:
            res = await _copy_to(bot, uid, data["chat_id"], data["msg_id"])
            counts[res] += 1
            await asyncio.sleep(0.8)  # 20 паралельно / 0.8 с ≈ 25 повідомлень/с

    await asyncio.gather(*(worker(uid) for uid in ids))
    await bot.send_message(
        admin_chat,
        f"✅ Розсилку завершено\n"
        f"Доставлено: {counts['ok']}\n"
        f"Заблокували бота: {counts['blocked']}\n"
        f"Помилки: {counts['fail']}",
    )


# ---------- роутер ----------

router = Router(name="broadcast")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class Broadcast(StatesGroup):
    content = State()
    confirm = State()


class DirectMsg(StatesGroup):
    user_id = State()
    content = State()


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Розсилка всім", callback_data="adm:bc")],
            [InlineKeyboardButton(text="✉️ Написати користувачу", callback_data="adm:dm")],
        ]
    )


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="adm:cancel")]]
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📣 Розсилка та повідомлення", reply_markup=_menu_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Скасовано.")


@router.callback_query(F.data == "adm:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("Скасовано.")
    await cb.answer()


# --- розсилка всім ---

@router.callback_query(F.data == "adm:bc")
async def cb_bc(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.content)
    await cb.message.answer(
        "📣 Надішли повідомлення для розсилки (текст, фото чи відео з підписом).",
        reply_markup=_cancel_kb(),
    )
    await cb.answer()


@router.message(Broadcast.content)
async def bc_preview(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id, msg_id=message.message_id)
    await state.set_state(Broadcast.confirm)
    ids, sources = await get_user_ids()
    await message.answer("Так виглядатиме повідомлення:")
    await message.bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    src = ", ".join(sources) if sources else "нічого не знайдено"
    await message.answer(
        f"Відправити {len(ids)} користувачам?\nДжерела: {src}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Відправити", callback_data="adm:bc_go"),
                    InlineKeyboardButton(text="❌ Скасувати", callback_data="adm:cancel"),
                ]
            ]
        ),
    )


@router.callback_query(Broadcast.confirm, F.data == "adm:bc_go")
async def bc_go(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    ids, _ = await get_user_ids()
    await cb.message.edit_text(
        f"⏳ Розсилка пішла ({len(ids)} користувачів). Звіт прийде, коли завершиться."
    )
    await cb.answer()
    task = asyncio.create_task(_run_broadcast(cb.bot, cb.message.chat.id, list(ids), data))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


# --- повідомлення одному користувачу ---

@router.callback_query(F.data == "adm:dm")
async def cb_dm(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DirectMsg.user_id)
    await cb.message.answer("✉️ Надішли ID користувача.", reply_markup=_cancel_kb())
    await cb.answer()


@router.message(DirectMsg.user_id)
async def dm_get_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("ID — це число. Спробуй ще раз або /cancel.")
        return
    await state.update_data(target=int(text))
    await state.set_state(DirectMsg.content)
    await message.answer("Тепер надішли повідомлення для цього користувача.", reply_markup=_cancel_kb())


@router.message(DirectMsg.content)
async def dm_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    res = await _copy_to(message.bot, data["target"], message.chat.id, message.message_id)
    await message.answer(
        {
            "ok": "✅ Надіслано.",
            "blocked": "⚠️ Користувач заблокував бота або ніколи його не запускав.",
            "fail": "❌ Не вдалося надіслати, деталі в консолі.",
        }[res]
    )
