from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import TelegramObject

from bot.config import settings
from bot.handlers import admin, driver, fallback, provider, start
from bot.handlers import settings as settings_handler
from bot.services.channel_reader import start_reader, stop_reader
from bot.services.user_service import seed_default_routes
from db.database import AsyncSessionLocal, engine


class DbSessionMiddleware:
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    # DB sxemasi Alembic bilan boshqariladi (alembic upgrade head).
    # Bu yerda create_all CHAQIRILMAYDI — Alembic bilan konflikt bo'lmasligi uchun.

    # Standart yo'nalishlarni seed qilish
    async with AsyncSessionLocal() as session:
        await seed_default_routes(session)
    log.info("Routes seed ✅")

    reader_task = None
    if settings.TELEGRAM_API_ID and settings.channel_ids_list:
        reader_task = asyncio.create_task(start_reader())
        log.info("Kanal o'quvchi task yaratildi ✅")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(start.router)
    dp.include_router(driver.router)
    dp.include_router(provider.router)
    dp.include_router(admin.router)
    dp.include_router(settings_handler.router)
    # Fallback (catch-all "Tushunarsiz buyruq") — DOIM eng oxirida bo'lishi shart
    dp.include_router(fallback.router)

    log.info("Bot polling rejimida ishga tushmoqda...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if reader_task:
            await stop_reader()
            reader_task.cancel()
        await engine.dispose()
        await bot.session.close()
        log.info("Bot to'xtatildi.")


if __name__ == "__main__":
    asyncio.run(main())
