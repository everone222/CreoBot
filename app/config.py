import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
AUDIO_DIR = DATA_DIR / "audio"
TMP_DIR = DATA_DIR / "tmp"
OUTPUT_DIR = DATA_DIR / "output"
DB_PATH = DATA_DIR / "bot.db"

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

def _default_font() -> str:
    """Шрифт з кирилицею: Windows → Linux → рідна папка проєкту."""
    candidates = (
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    )
    for path in candidates:
        if Path(path).exists():
            return path
    local = BASE_DIR / "fonts"
    if local.exists():
        for font in sorted(local.glob("*.ttf")):
            return str(font)
    return candidates[2]


FONT_PATH = os.getenv("FONT_PATH", _default_font())

# Використовуються і для відео, і для слайдшоу з фото.
MIN_CLIP = 7.0
MAX_CLIP = 10.0
PHOTO_FRAME_SEC = float(os.getenv("PHOTO_FRAME_SEC", "0.3"))
# Загальна тривалість слайдшоу з фото — випадкова в цих межах.
PHOTO_MIN_SEC = float(os.getenv("PHOTO_MIN_SEC", "7.0"))
PHOTO_MAX_SEC = float(os.getenv("PHOTO_MAX_SEC", "9.0"))
MIN_PHOTOS = 4
MAX_PHOTOS = 10
ALBUM_DEBOUNCE_SEC = 0.8

DEFAULT_TOPIC = "заработок, арбитраж трафика, мотивация"


def validate() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан в .env")
    if not ADMIN_IDS:
        raise SystemExit("ADMIN_IDS не задан в .env (бот закрыт для посторонних)")
    if not (GROQ_API_KEY or GEMINI_API_KEY):
        raise SystemExit("Нужен GROQ_API_KEY или GEMINI_API_KEY")
    if not Path(FONT_PATH).exists():
        raise SystemExit(f"Шрифт не найден: {FONT_PATH}")
    for d in (DATA_DIR, AUDIO_DIR, TMP_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)