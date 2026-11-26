from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from . import config
from .stats_db import track


class TrackingMiddleware(BaseMiddleware):
    """Реєструє юзера і пише в логи кожну кнопку та команду (вміст текстів не зберігається)."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and not user.is_bot:
            action = None
            if isinstance(event, CallbackQuery) and event.data:
                action = f"btn:{event.data}"
            elif isinstance(event, Message):
                if event.text and event.text.startswith("/"):
                    action = f"cmd:{event.text.split()[0]}"
                elif event.video:
                    action = "msg:відео"
                elif event.audio or event.voice or event.document:
                    action = "msg:файл/аудіо"
                elif event.text:
                    action = "msg:текст"
            try:
                await track(user.id, user.username, user.full_name, action,
                            user.id in config.ADMIN_IDS)
            except Exception:
                pass  # збій статистики не має ламати бота
        return await handler(event, data)
