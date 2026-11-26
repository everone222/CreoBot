import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from . import config, db
from .admin import deny_router
from .admin import router as admin_router
from .handlers import router
from .menu import router as menu_router
from .menu import user_router
from .stats_db import init_stats_db
from .tracking import TrackingMiddleware
from .broadcast import router as broadcast_router   # до імпортів роутерів
from .options import router as options_router


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.validate()
    await db.init_db()
    await init_stats_db()

    bot = Bot(config.BOT_TOKEN)
    dp = Dispatcher()
    dp.message.outer_middleware(TrackingMiddleware())
    dp.callback_query.outer_middleware(TrackingMiddleware())
    dp.include_router(broadcast_router)
    dp.include_router(admin_router)
    dp.include_router(deny_router)
    dp.include_router(menu_router)  # меню має бути першим
    dp.include_router(user_router)
    dp.include_router(router)
    dp.include_router(options_router)  # /options та застаріліtoggle:-кнопки
    await bot.set_my_commands([BotCommand(command="menu", description="Меню")])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
