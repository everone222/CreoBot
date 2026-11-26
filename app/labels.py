"""Людські назви кнопок для логів (під твоє меню)."""
import re

BUTTON_LABELS = {
    # твоє меню
    "menu": "⬅️ Меню",
    "style": "🎨 Стиль",
    "tracks": "🎵 Треки",
    "prompt": "✍️ Промт",
    "cta": "📣 CTA",
    "help": "❓ Допомога",
    "import": "📂 Імпорт треків",
    "reset:prompt": "♻️ Скинути промт",
    "edit:prompt": "✏️ Змінити промт",
    "edit:cta": "✏️ Змінити CTA",
    # адмін-панель
    "adm:home": "🛠 Адмін-панель",
    "adm:stats": "📊 Статистика",
    "adm:users": "👥 Користувачі",
    "adm:logs": "📜 Логи",
}

# кнопки з параметром: "style:<назва>", "deltrack:<id>"
PREFIX_LABELS = {
    "style:": "🎨 Обрав стиль:",
    "deltrack:": "🗑 Видалив трек №",
}


def describe_action(action: str) -> str:
    kind, _, value = action.partition(":")
    if kind == "btn":
        if value in BUTTON_LABELS:
            return BUTTON_LABELS[value]
        m = re.fullmatch(r"(adm:(?:users|logs)):\d+", value)  # сторінки пагінації
        if m:
            return BUTTON_LABELS[m.group(1)]
        for prefix, label in PREFIX_LABELS.items():
            if value.startswith(prefix):
                return f"{label} {value[len(prefix):]}"
        return f"кнопка {value}"
    if kind == "cmd":
        return f"команда {value}"
    if kind == "msg":
        return f"надіслав {value}"
    return action
