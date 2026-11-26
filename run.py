"""Точка входу: python run.py.

Окрім polling-бота піднімає маленький /health на PORT — це потрібно
Render/Railway/Fly, інакше платформа вважає сервіс мертвим.
"""

import asyncio
import os

from aiohttp import web

from app.main import main


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _start_health_server() -> None:
    app = web.Application()
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000")))
    await site.start()


async def entrypoint() -> None:
    await _start_health_server()
    await main()


if __name__ == "__main__":
    asyncio.run(entrypoint())
