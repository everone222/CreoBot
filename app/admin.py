from collections import Counter
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from . import config
from . import keyboards as kb
from .labels import describe_action
from .stats_db import get_logs_page, get_stats, get_users_page, to_local

PER_PAGE = 10

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

# спрацьовує лише для не-адмінів (admin router підключається першим)
deny_router = Router()


def _who(username, full_name, user_id: int) -> str:
    name = f"@{username}" if username else (full_name or "без імені")
    return f"{escape(name)} (<code>{user_id}</code>)"


async def _show(cb: CallbackQuery, text: str, markup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise
    await cb.answer()


@router.message(Command("admin"))
async def admin_cmd(message: Message):
    await message.answer("🛠 <b>Адмін-панель</b>", reply_markup=kb.admin_home(), parse_mode="HTML")


@router.callback_query(F.data == "adm:home")
async def admin_home(cb: CallbackQuery):
    await _show(cb, "🛠 <b>Адмін-панель</b>", kb.admin_home())


@router.callback_query(F.data == "adm:noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data == "adm:stats")
async def stats(cb: CallbackQuery):
    s = await get_stats()
    top: Counter = Counter()
    for action, count in s["buttons"]:
        top[describe_action(action)] += count
    top_text = "\n".join(
        f"  {i}. {escape(name)} — {c}" for i, (name, c) in enumerate(top.most_common(5), 1)
    ) or "  —"
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всього користувачів: <b>{s['total_users']}</b>\n"
        f"🆕 Нових сьогодні: <b>{s['new_today']}</b>\n"
        f"🔥 Активні за 24 год: <b>{s['active_24h']}</b>\n"
        f"📅 Активні за 7 днів: <b>{s['active_7d']}</b>\n"
        f"🖱 Всього дій: <b>{s['total_actions']}</b>\n"
        f"🎬 Створено відео: <b>{s['total_videos']}</b>\n\n"
        f"🏆 <b>Топ кнопок:</b>\n{top_text}"
    )
    await _show(cb, text, kb.back_to_admin())


@router.callback_query(F.data.startswith("adm:users:"))
async def users(cb: CallbackQuery):
    page = int(cb.data.split(":")[2])
    rows, total = await get_users_page(page, PER_PAGE)
    lines = [
        f"{_who(u, n, uid)}{' 👑' if uid in config.ADMIN_IDS else ''}\n"
        f"   ⏱ {to_local(last)} · дій: {acts} · відео: {vids}"
        for uid, u, n, last, acts, vids in rows
    ]
    text = f"👥 <b>Користувачі</b> (всього {total})\n\n" + ("\n\n".join(lines) or "Поки порожньо")
    await _show(cb, text, kb.pager("adm:users", page, total, PER_PAGE))


@router.callback_query(F.data.startswith("adm:logs:"))
async def logs(cb: CallbackQuery):
    page = int(cb.data.split(":")[2])
    rows, total = await get_logs_page(page, PER_PAGE)
    lines = [
        f"<code>{to_local(ts)}</code> {'👑' if adm else '👤'} {_who(u, n, uid)}\n"
        f"   → {escape(describe_action(a))}"
        for uid, u, n, adm, a, ts in rows
    ]
    text = f"📜 <b>Логи дій</b> (всього {total})\n\n" + ("\n\n".join(lines) or "Поки порожньо")
    await _show(cb, text, kb.pager("adm:logs", page, total, PER_PAGE))


@deny_router.callback_query(F.data.startswith("adm:"))
async def deny(cb: CallbackQuery):
    await cb.answer("⛔ Немає доступу", show_alert=True)
