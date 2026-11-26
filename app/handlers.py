import asyncio
import logging
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message

from . import config, db
from . import user_settings as us
from .ai_text import generate_texts
from .downloader import download_video, find_pinterest_url
from .menu import refresh_menu
from .photo_slideshow import (
    MAX_PHOTOS,
    MIN_PHOTOS,
    PHOTO_MAX_SEC,
    PHOTO_MIN_SEC,
    process_photos,
)
from .stats_db import inc_videos
from .video_processor import VideoError, process_video

log = logging.getLogger(__name__)

router = Router()
SEM = asyncio.Semaphore(1)  # одна обробка за раз — бережём слабый VPS
last_topic: dict[int, str] = {}
ALBUM_DEBOUNCE = getattr(config, "ALBUM_DEBOUNCE_SEC", 0.8)


@dataclass
class Album:
    """Буфер альбому фото, поки Telegram доставляє всі його повідомлення."""

    first: Message
    items: list[tuple[int, str]] = field(default_factory=list)  # (message_id, file_id)
    task: asyncio.Task | None = None
    started: bool = False


albums: dict[str, Album] = {}

HELP = (
    "Я монтирую вертикальные видео 7–10 сек.\n\n"
    "<b>Как пользоваться</b>\n"
    "• Пришли видеофайл (тема — в подписи) или ссылку Pinterest + тему текстом\n"
    "• Пришли 4–10 фото одним альбомом — сделаю слайдшоу 7–9 с (кадр 0.3 с)\n"
    "• Просто текст без ссылки — запомню как тему для следующего видео\n\n"
    "<b>Команды</b>\n"
    "/style — цветокор (cinematic, default, warm, cold, contrast, bw)\n"
    "/prompt &lt;текст&gt; — системный промт для AI (/showprompt, /prompt_reset)\n"
    "/cta &lt;смысл&gt; — какой призыв должен генерировать AI\n"
    "/tracks — список треков, /deltrack &lt;id&gt; — удалить\n\n"
    "Аудио: просто отправь mp3/m4a файл в чат — он попадёт в библиотеку."
)


async def _get_texts(uid: int, topic: str) -> dict[str, str]:
    """Загальний генератор текстів для обох пайплайнів."""
    settings = await us.get_settings(uid)
    if not settings["text_on"]:
        return {"headline": "", "cta": ""}  # не витрачаємо квоту AI
    return await generate_texts(
        topic,
        await us.get_setting(uid, "system_prompt"),
        await us.get_setting(uid, "cta_hint"),
    )


async def _deliver(m: Message, render, source, work_dir: Path,
                   topic: str, extra_caption: str = "") -> None:
    """Спільний пайплайн: текст → рендер → документ → статистика → clean-up."""
    uid = m.from_user.id
    settings = await us.get_settings(uid)
    status = await m.answer(
        "⏳ Генерирую текст…" if settings["text_on"] else "🎬 Монтирую…"
    )
    out: Path | None = None
    try:
        texts = await _get_texts(uid, topic)
        if texts["headline"] or texts["cta"]:
            await status.edit_text(
                f"🎬 Монтирую…\n«{texts['headline']}» / «{texts['cta']}»"
            )

        # Налаштування могли змінитися під час генерації тексту — перечитаємо.
        settings = await us.get_settings(uid)
        track = await db.random_track() if settings["audio_on"] else None
        async with SEM:
            out = await render(
                source,
                texts["headline"],
                texts["cta"],
                await us.get_setting(uid, "style"),
                track,
                text_on=settings["text_on"],
                audio_on=settings["audio_on"],
            )

        caption = f"{texts['headline']}\n{texts['cta']}".strip()
        if extra_caption:
            caption = (caption + "\n\n" + extra_caption).strip()
        if settings["audio_on"] and not track:
            caption += "\n\n⚠️ Библиотека треков пуста — видео без звука."

        # документом — чтобы Telegram не пережимал файл
        await m.answer_document(
            FSInputFile(out, filename="video.mp4"), caption=caption or None
        )
        await inc_videos(uid)
        await status.delete()
    except VideoError as e:
        await status.edit_text(f"❌ {e}")
    except Exception:  # noqa: BLE001
        log.exception("pipeline failed")
        await status.edit_text("❌ Что-то пошло не так, смотри логи.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if out:
            out.unlink(missing_ok=True)


async def run_pipeline(m: Message, src: Path, topic: str, work_dir: Path) -> None:
    """Старий сценарій: одне відео."""
    await _deliver(m, process_video, src, work_dir, topic)


async def run_photo_pipeline(m: Message, paths: list[Path], topic: str,
                             work_dir: Path, count: int) -> None:
    """Новий сценарій: альбом фото → слайдшоу по 0.3 с."""
    sec = getattr(config, "PHOTO_FRAME_SEC", 0.3)
    label = f"🖼 {count} фото · {sec:g} с/кадр · {PHOTO_MIN_SEC:g}–{PHOTO_MAX_SEC:g} с"
    await _deliver(m, process_photos, paths, work_dir, topic, label)


@router.message(
    F.from_user.id.in_(config.ADMIN_IDS),
    F.audio | (F.document & F.document.mime_type.startswith("audio/")),
)
async def on_audio(m: Message, bot: Bot):
    f = m.audio or m.document
    name = getattr(f, "file_name", None) or f"{f.file_unique_id}.mp3"
    safe = re.sub(r"[^\w.\-]+", "_", name)
    dest = config.AUDIO_DIR / f"{f.file_unique_id}_{safe}"
    try:
        await bot.download(f, destination=dest)
    except TelegramBadRequest:
        await m.answer("Файл слишком большой (лимит Bot API — 20 МБ).")
        return
    await db.add_track(name, str(dest))
    await refresh_menu(m, "tracks")


async def _finish_album(key: str, last: Message) -> None:
    """Дочекатись кінця альбому, скачати фото і віддати в слайдшоу."""
    await asyncio.sleep(ALBUM_DEBOUNCE)
    album = albums.get(key)
    if album is None or album.started:
        return
    album.started = True
    albums.pop(key, None)

    try:
        items = sorted(album.items)  # message_id альбому йдуть по порядку
        count = len(items)
        if count < MIN_PHOTOS or count > MAX_PHOTOS:
            await last.answer(
                f"Для слайдшоу треба {MIN_PHOTOS}–{MAX_PHOTOS} фото, отримав {count}."
            )
            return

        first = album.first
        topic = (
            (first.caption or "").strip()
            or last_topic.get(first.from_user.id)
            or config.DEFAULT_TOPIC
        )

        work_dir = config.TMP_DIR / uuid.uuid4().hex
        work_dir.mkdir(parents=True)
        paths: list[Path] = []
        try:
            for i, (_, file_id) in enumerate(items):
                file = await last.bot.get_file(file_id)
                dest = work_dir / f"photo_{i:02d}.jpg"
                await last.bot.download(file.file_id, destination=dest)
                paths.append(dest)
        except TelegramBadRequest:
            shutil.rmtree(work_dir, ignore_errors=True)
            await last.answer("Файл слишком большой (лимит Bot API — 20 МБ).")
            return
        except Exception:  # noqa: BLE001
            log.exception("photo download failed")
            shutil.rmtree(work_dir, ignore_errors=True)
            await last.answer("❌ Не вдалось завантажити фото.")
            return

        await run_photo_pipeline(last, paths, topic, work_dir, count)
    except Exception:  # noqa: BLE001
        log.exception("album finish failed")


@router.message(F.photo)
async def on_photos(m: Message):
    """Альбом 4–10 фото → одне відео. Один foto без альбому → підказка."""
    if not m.media_group_id:
        if m.caption:
            last_topic[m.from_user.id] = m.caption.strip()
        await m.answer(
            f"Надішли {MIN_PHOTOS}–{MAX_PHOTOS} фото одним альбомом "
            "(вибери всі та надішли разом)."
        )
        return

    key = f"{m.from_user.id}:{m.media_group_id}"
    album = albums.get(key)
    if album is not None and album.started:
        return  # запізніле повідомлення вже обробленого альбому

    if album is None:
        album = Album(first=m)
        albums[key] = album
    album.items.append((m.message_id, m.photo[-1].file_id))

    if album.task is not None and not album.task.done():
        album.task.cancel()  # debounce: таймер починається з останнього фото
    album.task = asyncio.create_task(_finish_album(key, m))


@router.message(F.video | (F.document & F.document.mime_type.startswith("video/")))
async def on_video(m: Message, bot: Bot):
    topic = (m.caption or "").strip() or last_topic.get(m.from_user.id) or config.DEFAULT_TOPIC
    f = m.video or m.document
    work_dir = config.TMP_DIR / uuid.uuid4().hex
    work_dir.mkdir(parents=True)
    src = work_dir / "input.mp4"
    try:
        await bot.download(f, destination=src)
    except TelegramBadRequest:
        shutil.rmtree(work_dir, ignore_errors=True)
        await m.answer(
            "Файл слишком большой (лимит Bot API — 20 МБ). "
            "Пришли ссылку или файл поменьше."
        )
        return
    await run_pipeline(m, src, topic, work_dir)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    url = find_pinterest_url(m.text)
    topic = m.text.replace(url, "").strip() if url else m.text.strip()
    if not url:
        last_topic[m.from_user.id] = topic
        await m.answer("Тему запомнил. Теперь пришли видео или ссылку Pinterest.")
        return
    topic = topic or last_topic.get(m.from_user.id) or config.DEFAULT_TOPIC
    work_dir = config.TMP_DIR / uuid.uuid4().hex
    work_dir.mkdir(parents=True)
    wait = await m.answer("⬇️ Скачиваю видео…")
    try:
        src = await download_video(url, work_dir)
    except Exception:  # noqa: BLE001
        log.exception("download failed")
        shutil.rmtree(work_dir, ignore_errors=True)
        await wait.edit_text("❌ Не удалось скачать (в пине может быть картинка, а не видео).")
        return
    await wait.delete()
    await run_pipeline(m, src, topic, work_dir)
