# Крео-бот

Telegram-бот на aiogram 3: робить вертикальні креативи 9:16 для TikTok/Reels/Shorts.

## Що вміє

- **Відео**: файл або посилання Pinterest → найдинамічніший шматок 7–10 с, кольорокор, текст, музика, чисті метадані.
- **Фото (нове)**: альбом 4–10 фото → одне відео **7–9 с** (випадково), 1080×1920 / 30 fps.
  Кожен кадр триває **0.3 с**, послідовність фото повторюється по колу з новою унікалізацією.
  Кожне фото унікалізується випадковим zoom/pan, дзеркалом, легкою зміною кольору та grain.
  EXIF-метадані видаляються ще на етапі JPEG, а ffmpeg додатково пише `-map_metadata -1`, `bitexact`, `+faststart`.
- Персональні налаштування: стиль, системний промт, CTA, перемикачі «Текст» і «Звук».
- Адмінка: бібліотека треків, статистика, логи, користувачі, розсилка, повідомлення одному юзеру.

## Запуск

1. Встанови [ffmpeg](https://ffmpeg.org/) + ffprobe і додай їх у `PATH`.
2. `python -m venv venv` → `.\venv\Scripts\pip install -r requirements.txt`
3. Скопіюй `.env.example` у `.env`, заповни `BOT_TOKEN`, `ADMIN_IDS` і хоча б один AI-ключ.
4. `python run.py` (або `python -m app.main`).

## Команди

`/start`, `/menu`, `/options`, `/admin`, `/broadcast`, `/cancel`

Тему можна задати текстом перед завантаженням або підписом до медіа.

## Структура

```
app/
  main.py            # точки входу, роутери
  handlers.py        # відео, Pinterest, альбом фото, спільний пайплайн
  photo_slideshow.py # НОВЕ: 4–10 фото → mp4 по 0.3 с/кадр
  video_processor.py # ffmpeg-рендер відео, пресети, текст, метадані
  ai_text.py         # Groq/Gemini → headline + CTA
  downloader.py      # Pinterest через yt-dlp
  menu.py            # інлайн-меню, стиль/промт/CTA/перемикачі
  user_settings.py   # персональні налаштування (SQLite)
  db.py              # треки + дефолти
  admin.py / stats_db.py / tracking.py / broadcast.py
  options.py / link.py  # сумісність зі старими викликами
data/                # створюється автоматично: audio, tmp, output, bot.db
```
