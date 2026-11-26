"""Застарілий shim. Робоча логіка тепер у handlers.py + downloader.py.

Раніше цей файл реєстрував зламаний роутер: імпортував неіснуючий
`generate_text` і викликав `process_video()` зі старим сигналом. Його не
підключали в main.py, але імпорт усе одно падав. Залишились лише сумісні
ре-експорти, ніяких роутерів.
"""
from .ai_text import generate_texts
from .downloader import PIN_RE, download_pinterest, download_video, find_pinterest_url
from .video_processor import process_video

__all__ = [
    "PIN_RE",
    "download_pinterest",
    "download_video",
    "find_pinterest_url",
    "generate_text",
    "generate_texts",
    "process_video",
]


async def generate_text(topic: str = "") -> str:
    """Старий API: одна рядок-результат замість двох полів JSON."""
    from . import config

    from .db import DEFAULT_PROMPT, DEFAULTS

    texts = await generate_texts(
        topic or config.DEFAULT_TOPIC,
        await _setting("system_prompt", DEFAULT_PROMPT),
        await _setting("cta_hint", DEFAULTS["cta_hint"]),
    )
    return f"{texts['headline']}\n{texts['cta']}".strip()


async def _setting(key: str, default: str) -> str:
    from .user_settings import get_setting

    try:
        return await get_setting(key, default)
    except Exception:  # noqa: BLE001
        return default
