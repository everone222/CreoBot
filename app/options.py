"""Сумісність: /options відкриває звичайне меню з перемикачами.

Раніше тут був окремий роутер з власними callback_data `toggle:*`, через що
перемикачі дублювалися і не працювали після перезапуску. Тепер єдиний
джерело правди — `menu.py` (`tgl:*`), а цей модуль лише сумісність.
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from . import user_settings as us
from .menu import send_menu

router = Router(name="options-compat")


@router.message(Command("options"))
async def show_options(m: Message):
    await send_menu(m)


@router.callback_query(F.data.startswith("toggle:"))
async def legacy_toggle(cb: CallbackQuery):
    """ Старі клавіатури `/options` ще можуть бути в чаті. """
    field = cb.data.split(":", 1)[1]
    try:
        await us.toggle_setting(cb.from_user.id, field)
    except ValueError:
        await cb.answer("Невідомий перемикач", show_alert=True)
        return
    await cb.answer("Збережено. Відкрий /menu, щоб побачити стан.")
