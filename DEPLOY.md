# Деплой Крео-бота

> ⚠️ Я не зміг виконати деплой звідси: у цьому середовищі немає Git-авторизації,
> Render/Railway CLI та токенів до акаунтів. Усі файли нижче вже підготовлені —
> залишилось залити репозиторій і виставити 3 секрети.

## Що вже готово

| Файл | Для чого |
|---|---|
| `Procfile` | `web: python run.py` (Heroku/Railway-сумісний запуск) |
| `render.yaml` | Render Blueprint: ffmpeg + pip, `/health`, змінні |
| `Dockerfile` | python:3.12-slim + ffmpeg, універсальний контейнер |
| `.dockerignore` | не тягнути `venv/`, `.env`, `data/` у образ |
| `run.py` | polling-бот + HTTP `/health` на `$PORT` |

## Варіант A — Render (найпростіший)

1. Створи GitHub-репозиторій і залий сюди папку `D:\Крео бот` (корінь — там, де лежить `render.yaml`).
2. Render Dashboard → **New → Blueprint** → вибери той репозиторій.
3. При створенні заповни Secret Env Vars:
   - `BOT_TOKEN` — токен від @BotFather
   - `ADMIN_IDS` — твої Telegram ID через кому
   - `GROQ_API_KEY` **або** `GEMINI_API_KEY` (бажано обидва — є fallback)
4. Deploy → дочекайся логів `[bot] Авторизовано як @...`.
5. Перевір `https://<service>.onrender.com/health` → має бути `ok`.

`render.yaml` сам ставить `ffmpeg` через apt, тож конвертація фото запрацює одразу.

## Варіант B — Railway

1. New Project → Deploy from GitHub repo.
2. Railway побачить `Dockerfile` і використає його.
3. У Settings → Variables додай ті самі `BOT_TOKEN`, `ADMIN_IDS`, `GROQ_API_KEY` / `GEMINI_API_KEY`.
4. `PORT` Railway виставить сам; `/health` уже є.

## Варіант C — VPS / Docker самостійно

```bash
cd /path/to/creo-bot
cp .env.example .env      # заповнити токени
docker build -t creo-bot .
docker run -d --restart unless-stopped --env-file .env -p 10000:10000 creo-bot
```

Без Docker:

```bash
python -m venv venv
source venv/bin/activate      # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Змінні оточення

| Змінна | Обов'язкова | Нотатка |
|---|---|---|
| `BOT_TOKEN` | так | інакше `config.validate()` зупинить бота |
| `ADMIN_IDS` | так | бот закритий для сторонніх |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | хоча б одна | генерація headline + CTA |
| `PHOTO_FRAME_SEC` | ні | за замовчуванням `0.3` |
| `PHOTO_MIN_SEC` / `PHOTO_MAX_SEC` | ні | за замовчуванням `7` / `9` |
| `FONT_PATH` | ні | авто-визначення; поклади `.ttf` у `fonts/`, якщо потрібно |
| `PORT` | ні | за замовчуванням `10000`, хостинг виставить сам |

## Після деплою перевірити

- `/start` у боті → меню.
- Надіслати 5 фото одним альбомом → ролик **7–9 с** у підписом `🖼 5 фото · 0.3 с/кадр · 7–9 с`.
- Надіслати відео / Pinterest-посилання → старий сценарій працює.
- `/admin` → статистика й розсилка.
- `/health` → `ok`.

## Відомі обмеження

- Bot API приймає файли до **20 МБ**; це стосується і окремого фото, і вихідного відео.
- Обробка серіалізується через `Semaphore(1)` — на слабкому VPS це навмисно.
- Free-план Render засинає; перший запит після простою може бути повільним.
