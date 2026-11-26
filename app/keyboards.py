from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="👥 Користувачі", callback_data="adm:users:0")],
        [InlineKeyboardButton(text="📜 Логи", callback_data="adm:logs:0")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu")],
        [InlineKeyboardButton(text="📣 Розсилка всім", callback_data="adm:bc")],
        [InlineKeyboardButton(text="✉️ Написати користувачу", callback_data="adm:dm")]
    ])


def pager(prefix: str, page: int, total: int, per_page: int = 10) -> InlineKeyboardMarkup:
    pages = max(1, -(-total // per_page))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="adm:noop"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}:{page + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"{prefix}:{page}")],
        [InlineKeyboardButton(text="⬅️ Адмін-панель", callback_data="adm:home")],
    ])


def back_to_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="adm:stats")],
        [InlineKeyboardButton(text="⬅️ Адмін-панель", callback_data="adm:home")],
    ])
