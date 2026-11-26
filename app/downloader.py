"""Скачування відео з Pinterest за посиланням (yt-dlp)."""
import asyncio
import os
import re
import tempfile

import aiohttp
from yt_dlp import YoutubeDL

PIN_RE = re.compile(r"https?://(?:[\w-]+\.)?(?:pinterest\.[a-z.]+|pin\.it)/\S+", re.I)


async def _resolve(url: str) -> str:
    """pin.it/... -> повне посилання pinterest.com/pin/..."""
    if "pin.it" not in url:
        return url
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.get(url, allow_redirects=True) as r:
            return str(r.url)


def _download(url: str, out_dir: str) -> str:
    opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


async def download_pinterest(url: str) -> str:
    """Повертає шлях до скачаного файлу (у новій тимчасовій папці)."""
    url = await _resolve(url)
    out_dir = tempfile.mkdtemp(prefix="pin_")
    return await asyncio.to_thread(_download, url, out_dir)

def find_pinterest_url(text: str) -> str | None:
    m = PIN_RE.search(text or "")
    return m.group(0) if m else None


async def download_video(url: str, *args, **kwargs) -> str:
    return await download_pinterest(url)