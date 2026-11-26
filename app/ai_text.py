import json
import logging
import random
import re

import httpx

from . import config

log = logging.getLogger(__name__)

JSON_RULE = (
    "\n\nВерни СТРОГО JSON без пояснений и markdown: "
    '{"headline": "...", "cta": "..."}. '
    "headline — ультра-цепляющая фраза, максимум 5 слов. "
    "cta — призыв перейти в Telegram, максимум 6 слов. Оба поля на русском языке."
)

FALLBACKS = [
    {"headline": "Хватит работать на дядю", "cta": "Переходи в Telegram"},
    {"headline": "Деньги любят действие", "cta": "Всё в нашем Telegram"},
    {"headline": "Твой шанс уже здесь", "cta": "Жми в Telegram"},
]


def _limit_words(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip('"«»')
    return " ".join(text.split()[:n])


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0) if m else raw)
    headline = _limit_words(str(data["headline"]), 5)
    cta = _limit_words(str(data["cta"]), 6)
    if not headline or not cta:
        raise ValueError("empty fields")
    return {"headline": headline, "cta": cta}


async def _groq(client: httpx.AsyncClient, system: str, user: str) -> str:
    r = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        json={
            "model": config.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.9,
            "response_format": {"type": "json_object"},
        },
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


async def _gemini(client: httpx.AsyncClient, system: str, user: str) -> str:
    r = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
        params={"key": config.GEMINI_API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"},
        },
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def generate_texts(topic: str, system_prompt: str, cta_hint: str) -> dict:
    """Возвращает {"headline", "cta"} на русском. При сбоях AI — запасная фраза."""
    system = system_prompt + JSON_RULE
    user = f"Тема видео: {topic}\nЖелаемый смысл CTA: {cta_hint}"
    providers = []
    if config.GROQ_API_KEY:
        providers.append(_groq)
    if config.GEMINI_API_KEY:
        providers.append(_gemini)

    async with httpx.AsyncClient(timeout=30) as client:
        for provider in providers:
            for _ in range(2):
                try:
                    return _parse(await provider(client, system, user))
                except Exception as e:  # noqa: BLE001
                    log.warning("AI provider %s failed: %s", provider.__name__, e)
    return random.choice(FALLBACKS)
