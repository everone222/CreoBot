"""
Слайдшоу з альбому фото: 4–10 унікальних фото, кадр по 0.3 с,
загальна тривалість випадкова 7–9 с (послідовність повторюється по колу), vertical 9:16.

Кожне фото перед рендером «унікалізується»: випадковий zoom/pan, дзеркало,
невеликі зміни контрасту/колору та легкий grain. EXIF з фото не потрапляє у
результат (PIL перекомпресує кадр у JPEG без метаданих), а ffmpeg додатково
чистить контейнер: -map_metadata -1, bitexact, faststart.

Сумісний зі звичайним відеопайплайном: ті самі пресети стилю, текст, аудіо
та виклик через asyncio.to_thread.
"""
import asyncio
import math
import os
import random
import shutil
import tempfile
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from . import config
from .video_processor import (
    COLOR_PRESETS,
    FPS,
    W,
    H,
    VideoError,
    render_overlay,
    resolve_output_dir,
    resolve_track,
    run_ffmpeg,
)

MIN_PHOTOS = getattr(config, "MIN_PHOTOS", 4)
MAX_PHOTOS = getattr(config, "MAX_PHOTOS", 10)
FRAME_SEC = getattr(config, "PHOTO_FRAME_SEC", 0.3)
PHOTO_MIN_SEC = getattr(config, "PHOTO_MIN_SEC", 7.0)
PHOTO_MAX_SEC = getattr(config, "PHOTO_MAX_SEC", 9.0)
_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


class PhotoError(VideoError):
    """Помилка саме фото-пайплайна (текст показується користувачу)."""


def _cover(img: Image.Image, *, zoom: float, dx: float, dy: float,
           mirror: bool) -> Image.Image:
    """Привести foto до 1080x1920 з невеликим випадковим зсувом."""
    # EXIF-orientation застосовуємо до ресайзу, далі EXIF уже не існує.
    img = ImageOps.exif_transpose(img).convert("RGB")
    if mirror:
        img = ImageOps.mirror(img)

    iw, ih = img.size
    scale = max(W / iw, H / ih) * zoom
    nw, nh = max(W, math.ceil(iw * scale)), max(H, math.ceil(ih * scale))
    img = img.resize((nw, nh), _RESAMPLE)

    slack_x, slack_y = nw - W, nh - H
    left = slack_x // 2 + int(dx * slack_x / 2)
    top = slack_y // 2 + int(dy * slack_y / 2)
    left = min(max(0, left), slack_x)
    top = min(max(0, top), slack_y)
    return img.crop((left, top, left + W, top + H))


def _unique_frame(src: str, dst: str, seed: str) -> None:
    """Один кадр: унікальна комбінація transform + кольору + grain."""
    rng = random.Random(seed)
    rng_np = np.random.default_rng(int.from_bytes(seed.encode("utf-8"), "big") % (2**32))
    with Image.open(src) as raw:
        frame = _cover(
            raw,
            zoom=rng.uniform(1.04, 1.12),
            dx=rng.uniform(-0.85, 0.85),
            dy=rng.uniform(-0.85, 0.85),
            mirror=rng.random() < 0.35,
        )

    frame = ImageEnhance.Contrast(frame).enhance(rng.uniform(0.94, 1.10))
    frame = ImageEnhance.Color(frame).enhance(rng.uniform(0.88, 1.16))
    frame = ImageEnhance.Brightness(frame).enhance(rng.uniform(0.96, 1.05))

    arr = np.asarray(frame).astype(np.int16)
    grain = np.round(
        rng_np.normal(0.0, rng.uniform(1.0, 2.8), arr.shape)
    ).astype(np.int16)
    arr = np.clip(arr + grain, 0, 255).astype(np.uint8)

    # JPEG без exif/icc — метадані вихідного фото тут уже відрізані.
    Image.fromarray(arr, "RGB").save(dst, "JPEG", quality=92, subsampling=0)


def _concat_path(path: str) -> str:
    """concat-демuxer сприймає '\\' як escape — нормалізуємо шляхи."""
    return path.replace("\\", "/")


def _render(paths: list[str], out: str, headline: str | None, cta: str | None,
            style: str, track: str | None, seed: str, frame_count: int) -> None:
    work = tempfile.mkdtemp(prefix="ps_")
    try:
        frames: list[str] = []
        for i in range(frame_count):
            src = paths[i % len(paths)]
            if not Path(src).is_file():
                raise PhotoError(f"Фото не знайдено: {Path(src).name}")
            dst = os.path.join(work, f"frame_{i:03d}.jpg")
            # Новий seed на кожен прохід — повтори не ідентичні.
            _unique_frame(src, dst, f"{seed}-{i}")
            frames.append(dst)

        total = FRAME_SEC * len(frames)
        list_file = os.path.join(work, "frames.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for frame in frames:
                f.write(f"file '{_concat_path(frame)}'\n")
                f.write(f"duration {FRAME_SEC:.2f}\n")
            # Останній файл треба повторити: інакше ffmpeg обрахує його тривалість як 0.
            f.write(f"file '{_concat_path(frames[-1])}'\n")

        inputs = ["-f", "concat", "-safe", "0", "-i", list_file]
        idx = 1

        ov_idx: int | None = None
        if headline or cta:
            png = os.path.join(work, "overlay.png")
            render_overlay(png, headline, cta)
            inputs += [
                "-loop", "1", "-framerate", str(FPS),
                "-t", f"{total:.2f}", "-i", png,
            ]
            ov_idx = idx
            idx += 1

        a_idx: int | None = None
        if track:
            inputs += ["-stream_loop", "-1", "-i", track]
            a_idx = idx
            idx += 1

        color = COLOR_PRESETS.get(style, COLOR_PRESETS["default"])
        graph = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},{color},setsar=1,fps={FPS},format=yuv420p"
        )
        if ov_idx is not None:
            graph += (
                f"[base];[base][{ov_idx}:v]overlay=0:0:format=auto,"
                "format=yuv420p[v]"
            )
        else:
            graph += "[v]"

        cmd = ["ffmpeg", "-y", "-v", "error", *inputs,
               "-filter_complex", graph, "-map", "[v]"]

        if track:
            fade_len = min(0.6, total / 3)
            fade_start = max(0.0, total - fade_len)
            cmd += [
                "-map", f"{a_idx}:a",
                "-af", f"afade=t=out:st={fade_start:.2f}:d={fade_len:.2f}",
                "-c:a", "aac", "-b:a", "128k",
            ]
        else:
            cmd += ["-an"]

        cmd += [
            "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
            "-movflags", "+faststart",
            out,
        ]
        run_ffmpeg(cmd)
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def process_photos(
    paths,
    headline: str | None = None,
    cta: str | None = None,
    style: str = "default",
    track=None,
    *,
    text_on: bool = True,
    audio_on: bool = True,
) -> Path:
    """Зібрати mp4 з фото. Повертає шлях, який має видалити викликач."""
    items = [str(p) for p in paths]
    if not MIN_PHOTOS <= len(items) <= MAX_PHOTOS:
        raise PhotoError(
            f"Потрібно {MIN_PHOTOS}–{MAX_PHOTOS} фото, отримано {len(items)}."
        )
    if FRAME_SEC <= 0 or PHOTO_MIN_SEC <= 0 or PHOTO_MAX_SEC < PHOTO_MIN_SEC:
        raise PhotoError("Некоректні налаштування тривалості фото-ролика.")
    if PHOTO_MAX_SEC > 60:
        raise PhotoError("Занадто довгий фото-ролик (ліміт 60 с).")

    # 0.3 с на кадр, але ролик довший за альбом — крутимо фото по колу,
    # доки не наберемо випадкові 7–9 с.
    target = random.uniform(PHOTO_MIN_SEC, PHOTO_MAX_SEC)
    frame_count = math.ceil(target / FRAME_SEC)

    out = resolve_output_dir() / f"photos_{uuid.uuid4().hex}.mp4"
    await asyncio.to_thread(
        _render,
        items,
        str(out),
        headline if text_on else None,
        cta if text_on else None,
        style,
        resolve_track(track) if audio_on else None,
        uuid.uuid4().hex,
        frame_count,
    )
    return out
