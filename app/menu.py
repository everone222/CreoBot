"""Кнопкове меню: одне повідомлення, яке редагується, а повідомлення користувача видаляються.
Стиль, промт і CTA — персональні для кожного користувача. Треки та адмін-панель — тільки адмінам.
Перемикачі «Текст» і «Звук» — персональні, доступні всім."""
from contextlib import suppress
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import config, db
from . import user_settings as us
from .video_processor import COLOR_PRESETS

IS_ADMIN = F.from_user.id.in_(config.ADMIN_IDS)

router = Router()        # доступний усім
user_router = Router()   # лише відмова не-адмінам для адмінських кнопок

menu_msg: dict[int, int] = {}  # id користувача -> id повідомлення-меню

PAGES = {"menu", "style", "prompt", "cta", "help"}  # "tracks" — окремо, лише адмінам
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac"}

class Edit(StatesGroup):
    prompt = State()
    cta = State()


def kb(rows: list[list[tuple[str, str]]]):
    b = InlineKeyboardBuilder()
    for row in rows:
        b.row(*[InlineKeyboardButton(text=t, callback_data=d) for t, d in row])
    return b.as_markup()


BACK = [("⬅️ Меню", "menu")]


async def render(page: str, uid: int):
    """Повертає (текст, клавіатура) для сторінки меню конкретного користувача."""
    is_admin = uid in config.ADMIN_IDS

    if page == "style":
        cur = await us.get_setting(uid, "style")
        row = [(("✅ " if s == cur else "") + s, f"style:{s}") for s in COLOR_PRESETS]
        return "🎨 <b>Стиль кольорокорекції</b>", kb([row, BACK])

    if page == "tracks" and is_admin:
        tracks = await db.list_tracks()
        lines = "\n".join(f"{i}. {escape(name)}" for i, name, _ in tracks) or "Бібліотека порожня."
        rows = [[(f"🗑 {i}", f"deltrack:{i}") for i, _, _ in tracks[k:k + 4]] for k in range(0, len(tracks), 4)]
        text = (
            "🎵 <b>Треки</b>\nНадішліть аудіофайл у чат або покладіть файли в папку "
            "<code>data/audio</code> і натисніть «Імпорт».\n\n" + lines
        )
        return text, kb(rows + [[("📂 Імпорт з папки", "import")], BACK])

    if page == "prompt":
        cur = escape((await us.get_setting(uid, "system_prompt"))[:3000])
        rows = [[("✏️ Змінити", "edit:prompt"), ("♻️ Скинути", "reset:prompt")], BACK]
        return f"✍️ <b>Системний промт</b>\n\n{cur}", kb(rows)

    if page == "cta":
        cur = escape(await us.get_setting(uid, "cta_hint"))
        rows = [[("✏️ Змінити", "edit:cta")], BACK]
        return f"📣 <b>Зміст заклику (CTA)</b>\n\n{cur}", kb(rows)

    if page == "help":
        text = (
            "❓ <b>Як користуватись</b>\n\n"
            "• Надішліть відео (тема — у підписі) або посилання Pinterest + тему текстом.\n"
            "• 4–10 фото одним альбомом → слайдшоу 7–9 с (кадр 0.3 с).\n"
            "• Текст без посилання — запам'ятаю як тему для наступного відео.\n"
            "• Стиль, промт і CTA налаштовуються окремо для вас.\n"
            "• Кнопки «Текст» і «Звук» вмикають або вимикають текст на відео та звук."
        )
        if is_admin:
            text += "\n• Аудіофайл у чат — потрапляє в бібліотеку треків."
        return text, kb([BACK])

    style = await us.get_setting(uid, "style")
    s = await us.get_settings(uid)
    toggles = [
        (f"📝 Текст: {'✅ ВКЛ' if s['text_on'] else '❌ ВИКЛ'}", "tgl:text_on"),
        (f"🔊 Звук: {'✅ ВКЛ' if s['audio_on'] else '❌ ВИКЛ'}", "tgl:audio_on"),
    ]
    if not is_admin:
        text = (
            f"🎬 <b>Відео-бот</b>\nСтиль: {style}\n\n"
            "Надішліть відео або посилання Pinterest."
        )
        return text, kb([
            [("🎨 Стиль", "style")],
            toggles,
            [("✍️ Промт", "prompt"), ("📣 CTA", "cta")],
            [("❓ Допомога", "help")],
        ])

    n = len(await db.list_tracks())
    text = f"🎬 <b>Відео-бот</b>\nСтиль: {style} · Треків: {n}\n\nНадішліть відео або посилання Pinterest."
    return text, kb([
        [("🎨 Стиль", "style"), ("🎵 Треки", "tracks")],
        toggles,
        [("✍️ Промт", "prompt"), ("📣 CTA", "cta")],
        [("❓ Допомога", "help")],
        [("🛠 Адмін-панель", "adm:home")],
    ])


async def show(msg: Message, page: str, uid: int) -> None:
    text, markup = await render(page, uid)
    try:
        await msg.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


async def send_menu(m: Message) -> None:
    """Видалити старе меню і надіслати нове (викликайте, наприклад, після готового відео)."""
    old = menu_msg.pop(m.from_user.id, None)
    if old:
        with suppress(TelegramBadRequest):
            await m.bot.delete_message(m.chat.id, old)
    text, markup = await render("menu", m.from_user.id)
    sent = await m.answer(text, reply_markup=markup, parse_mode="HTML")
    menu_msg[m.from_user.id] = sent.message_id


async def refresh_menu(m: Message, page: str = "menu") -> None:
    """Видалити повідомлення користувача і оновити меню на місці (або створити нове)."""
    with suppress(TelegramBadRequest):
        await m.delete()
    text, markup = await render(page, m.from_user.id)
    mid = menu_msg.get(m.from_user.id)
    if mid:
        with suppress(TelegramBadRequest):
            await m.bot.edit_message_text(
                text, chat_id=m.chat.id, message_id=mid, reply_markup=markup, parse_mode="HTML"
            )
            return
    sent = await m.answer(text, reply_markup=markup, parse_mode="HTML")
    menu_msg[m.from_user.id] = sent.message_id


# ---------- команди ----------
@router.message(Command("start", "menu", "help"))
async def cmd_menu(m: Message, state: FSMContext):
    await state.clear()
    with suppress(TelegramBadRequest):
        await m.delete()
    await send_menu(m)


# ---------- кнопки (для всіх) ----------
@router.callback_query(F.data.in_(PAGES))
async def on_page(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    menu_msg[cb.from_user.id] = cb.message.message_id
    await show(cb.message, cb.data, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.in_({"tgl:text_on", "tgl:audio_on"}))
async def on_toggle(cb: CallbackQuery):
    await us.toggle_setting(cb.from_user.id, cb.data.split(":", 1)[1])
    menu_msg[cb.from_user.id] = cb.message.message_id
    await show(cb.message, "menu", cb.from_user.id)
    await cb.answer("Збережено")


@router.callback_query(F.data.startswith("style:"))
async def on_style(cb: CallbackQuery):
    style = cb.data.split(":", 1)[1]
    if style in COLOR_PRESETS:
        await us.set_setting(cb.from_user.id, "style", style)
    await show(cb.message, "style", cb.from_user.id)
    await cb.answer("Збережено")


@router.callback_query(F.data == "reset:prompt")
async def on_reset_prompt(cb: CallbackQuery):
    await us.set_setting(cb.from_user.id, "system_prompt", db.DEFAULT_PROMPT)
    await show(cb.message, "prompt", cb.from_user.id)
    await cb.answer("Скинуто")


@router.callback_query(F.data.in_({"edit:prompt", "edit:cta"}))
async def on_edit(cb: CallbackQuery, state: FSMContext):
    which = cb.data.split(":", 1)[1]
    await state.set_state(Edit.prompt if which == "prompt" else Edit.cta)
    await state.update_data(menu_id=cb.message.message_id)
    await cb.message.edit_text(
        "Надішліть новий текст одним повідомленням.",
        reply_markup=kb([[("✖️ Скасувати", which)]]),
    )
    await cb.answer()


@router.message(StateFilter(Edit.prompt, Edit.cta), F.text, ~F.text.startswith("/"))
async def on_new_value(m: Message, state: FSMContext):
    st = await state.get_state()
    data = await state.get_data()
    await state.clear()
    key, page = ("system_prompt", "prompt") if st == Edit.prompt.state else ("cta_hint", "cta")
    await us.set_setting(m.from_user.id, key, m.text.strip())
    menu_msg[m.from_user.id] = data["menu_id"]
    await refresh_menu(m, page)


# ---------- кнопки лише для адмінів: треки ----------
@router.callback_query(IS_ADMIN, F.data == "tracks")
async def on_tracks(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    menu_msg[cb.from_user.id] = cb.message.message_id
    await show(cb.message, "tracks", cb.from_user.id)
    await cb.answer()


@router.callback_query(IS_ADMIN, F.data.startswith("deltrack:"))
async def on_deltrack(cb: CallbackQuery):
    path = await db.delete_track(int(cb.data.split(":", 1)[1]))
    if path:
        Path(path).unlink(missing_ok=True)
    await show(cb.message, "tracks", cb.from_user.id)
    await cb.answer("Видалено")


@router.callback_query(IS_ADMIN, F.data == "import")
async def on_import(cb: CallbackQuery):
    known = {p for _, _, p in await db.list_tracks()}
    added = 0
    for f in sorted(config.AUDIO_DIR.rglob("*")):
        if f.is_file() and f.suffix.lower() in AUDIO_EXT and str(f) not in known:
            await db.add_track(f.name, str(f))
            added += 1
    await show(cb.message, "tracks", cb.from_user.id)
    await cb.answer(f"Додано: {added}")


# ---------- відмова не-адмінам для адмінських кнопок ----------
@user_router.callback_query(~IS_ADMIN)
async def user_denied(cb: CallbackQuery):
    await cb.answer("⛔ Недоступно", show_alert=True)
