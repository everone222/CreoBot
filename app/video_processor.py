"""
Обробка відео: найдинамічніший шматок 7-10 с, колір-пресет, 9:16,
звук (трек з бібліотеки / без звуку), текст з обводкою, чисті метадані.

Працює напряму через ffmpeg (потрібен ffmpeg + ffprobe в PATH). Потрібні Pillow + numpy.

Виклик (сумісний зі старим):
    out = await process_video(src, headline, cta, style, track)
    out = await process_video(src, headline, cta, style, track, text_on=False, audio_on=False)
"""
import asyncio
import os
import random
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config

W, H, FPS = 1080, 1920, 30
# Єдине джерело правди для довжини кліпу (раніше дублювалось у config.py).
MIN_DUR = getattr(config, "MIN_CLIP", 7.0)
MAX_DUR = getattr(config, "MAX_CLIP", 10.0)

# Кольорові пресети (ffmpeg-фільтри). Ключ = назва стилю.
COLOR_PRESETS = {
    "default": "eq=contrast=1.08:saturation=1.15:brightness=0.02",
    "cinematic": "eq=contrast=1.12:saturation=0.92:brightness=-0.01,colorbalance=rs=.04:bs=.06",
    "warm": "eq=contrast=1.05:saturation=1.2,colorbalance=rs=.08:bs=-.08",
    "cold": "eq=contrast=1.08:saturation=1.1,colorbalance=rs=-.06:bs=.08",
    "contrast": "eq=contrast=1.2:saturation=1.25:gamma=0.95",
    "bw": "hue=s=0,eq=contrast=1.15",
}


class VideoError(Exception):
    """Помилка обробки відео (текст показується користувачу)."""


# ---------- допоміжне ----------

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as e:
        raise VideoError("ffmpeg не найден в PATH") from e
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b"").decode("utf-8", "ignore")[-600:]
        raise VideoError(f"Ошибка ffmpeg: {tail}") from e


def _probe_duration(path: str) -> float:
    out = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ]).stdout.decode().strip()
    try:
        return float(out)
    except ValueError as e:
        raise VideoError("Не удалось прочитать видео") from e


def _pick_start(path: str, total: float, target: float) -> float:
    """Початок вікна довжиною target з максимальним рухом у кадрі."""
    if total <= target:
        return 0.0
    sw, sh = 64, 112
    raw = _run([
        "ffmpeg", "-v", "error", "-i", path,
        "-vf", f"fps=2,scale={sw}:{sh},format=gray",
        "-f", "rawvideo", "-",
    ]).stdout
    fs = sw * sh
    n = len(raw) // fs
    if n < 3:
        return 0.0
    frames = np.frombuffer(raw[: n * fs], np.uint8).reshape(n, fs).astype(np.int16)
    motion = np.abs(np.diff(frames, axis=0)).mean(axis=1)
    win = max(1, int(target * 2))
    if len(motion) <= win:
        return 0.0
    csum = np.concatenate([[0.0], np.cumsum(motion)])
    scores = csum[win:] - csum[:-win]
    start = int(np.argmax(scores)) / 2.0
    return float(min(start, max(0.0, total - target)))


def _track_path(track) -> str | None:
    """track з db.random_track(): шлях, Path, кортеж (id, name, path) або None."""
    if not track:
        return None
    if isinstance(track, (tuple, list)):
        track = track[-1]
    elif isinstance(track, dict):
        track = track.get("path")
    p = str(track) if track else None
    return p if p and os.path.exists(p) else None


def _find_font() -> str:
    cands = [
        os.getenv("FONT_PATH"),
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    # папка fonts/ у проєкті
    for f in Path("fonts").glob("*.ttf"):
        return str(f)
    raise VideoError("Не найден шрифт с кириллицей (положите .ttf в папку fonts)")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        t = f"{cur} {word}".strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _render_overlay(png_path: str, headline: str | None, cta: str | None) -> None:
    """Прозорий PNG 1080x1920 з текстом (білий з чорною обводкою)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fpath = _find_font()

    def block(text: str, start_size: int, center_y: int) -> None:
        size = start_size
        while True:
            font = ImageFont.truetype(fpath, size)
            lines = _wrap(d, text, font, W - 160)
            if len(lines) <= 5 or size <= 36:
                break
            size -= 4
        lh = int(size * 1.2)
        y = center_y - (lh * len(lines)) // 2
        for ln in lines:
            w = d.textlength(ln, font=font)
            d.text(
                ((W - w) / 2, y), ln, font=font, fill="white",
                stroke_width=max(4, size // 14), stroke_fill="black",
            )
            y += lh

    if headline:
        block(headline, 76, int(H * 0.30))
    if cta:
        block(cta, 58, int(H * 0.80))
    img.save(png_path)


def _output_dir() -> Path:
    for name in ("OUTPUT_DIR", "OUT_DIR", "OUTPUT_PATH"):
        v = getattr(config, name, None)
        if v:
            p = Path(v)
            break
    else:
        p = Path("data/output")
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- рендер (синхронний, у потоці) ----------

def _render(src: str, out: str, headline: str | None, cta: str | None,
            style: str, track: str | None) -> None:
    total = _probe_duration(src)
    dur = min(total, round(random.uniform(MIN_DUR, MAX_DUR), 1))
    start = _pick_start(src, total, dur)

    work = tempfile.mkdtemp(prefix="vp_")
    try:
        inputs = ["-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", src]
        idx = 1

        use_overlay = bool(headline or cta)
        ov_idx = None
        if use_overlay:
            png = os.path.join(work, "overlay.png")
            _render_overlay(png, headline, cta)
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.2f}", "-i", png]
            ov_idx = idx
            idx += 1

        a_idx = None
        if track:
            inputs += ["-stream_loop", "-1", "-i", track]
            a_idx = idx
            idx += 1

        color = COLOR_PRESETS.get(style, COLOR_PRESETS["default"])
        graph = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},{color},setsar=1,fps={FPS},format=yuv420p"
        )
        if use_overlay:
            graph += f"[base];[base][{ov_idx}:v]overlay=0:0:format=auto,format=yuv420p[v]"
        else:
            graph += "[v]"

        cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]"]

        if track:
            fade_st = max(0.0, dur - 0.6)
            cmd += [
                "-map", f"{a_idx}:a",
                "-af", f"afade=t=out:st={fade_st:.2f}:d=0.6",
                "-c:a", "aac", "-b:a", "128k",
            ]
        else:
            cmd += ["-an"]

        cmd += [
            "-t", f"{dur:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
            "-movflags", "+faststart",
            out,
        ]
        _run(cmd)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- публічна функція ----------

async def process_video(
    src,
    headline: str | None,
    cta: str | None,
    style: str,
    track=None,
    *,
    text_on: bool = True,
    audio_on: bool = True,
) -> Path:
    """
    text_on=False  -> без тексту на відео (headline і cta ігноруються)
    audio_on=False -> без звуку (трек ігнорується)
    audio_on=True  -> звук з треку; якщо треку немає — відео без звуку
    Повертає шлях до готового mp4 (видаляти після відправки має викликач).
    """
    out = _output_dir() / f"{uuid.uuid4().hex}.mp4"
    await asyncio.to_thread(
        _render,
        str(src),
        str(out),
        headline if text_on else None,
        cta if text_on else None,
        style,
        _track_path(track) if audio_on else None,
    )
    return out


# Публічні аліаси для сусідніх модулів (слайдшоу з фото використовує той самий рендер-стек).
run_ffmpeg = _run
render_overlay = _render_overlay
resolve_track = _track_path
resolve_output_dir = _output_dir
