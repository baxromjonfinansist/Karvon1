from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, TelegramObject, Update

from bot.config import settings
from bot.handlers import admin, driver, fallback, misc, provider, start
from bot.handlers import settings as settings_handler
from bot.services.channel_reader import start_reader, stop_reader
from bot.services.notify_service import (
    notify_loop,
    reminder_loop,
    stop_notify,
    stop_reminder,
)
from bot.services.user_service import seed_default_routes, touch_last_active
from db.database import AsyncSessionLocal, engine


class DbSessionMiddleware:
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Aktivlik kuzatuvi (dashboard uchun): har harakatda last_active_at
        # yangilanadi (5 daqiqada bir marta). ALOHIDA session'da — handler
        # session'ining tranzaksiyasiga aralashmasligi uchun.
        tg_id = _telegram_id_of(event)
        if tg_id is not None:
            try:
                async with AsyncSessionLocal() as act_session:
                    await touch_last_active(act_session, tg_id)
            except Exception:  # aktivlik yozuvi asosiy oqimni buzmasin
                pass

        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)


def _telegram_id_of(event: TelegramObject) -> int | None:
    """Update ichidan foydalanuvchi Telegram ID sini oladi (message/callback)."""
    if isinstance(event, Update):
        if event.message and event.message.from_user:
            return event.message.from_user.id
        if event.callback_query and event.callback_query.from_user:
            return event.callback_query.from_user.id
    return None


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

    # Slash-buyruqlar menyusi ("/" bosilganda ko'rinadi) — keyin kengaytiriladi.
    await bot.set_my_commands([
        BotCommand(command="start", description="🤖 Botni qayta ishga tushirish"),
    ])

    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(start.router)
    dp.include_router(driver.router)
    dp.include_router(provider.router)
    dp.include_router(admin.router)
    dp.include_router(settings_handler.router)
    dp.include_router(misc.router)
    # Fallback (catch-all "Tushunarsiz buyruq") — DOIM eng oxirida bo'lishi shart
    dp.include_router(fallback.router)

    # Yo'nalish bo'yicha avtomatik yuk xabarnomasi (har 10 daqiqada)
    notify_task = asyncio.create_task(notify_loop(bot))

    # Xabarnoma o'chiq haydovchilarga kunlik eslatma (08:30 va 20:30)
    reminder_task = asyncio.create_task(reminder_loop(bot))

    log.info("Bot polling rejimida ishga tushmoqda...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if reader_task:
            await stop_reader()
            reader_task.cancel()
        stop_notify()
        notify_task.cancel()
        stop_reminder()
        reminder_task.cancel()
        await engine.dispose()
        await bot.session.close()
        log.info("Bot to'xtatildi.")


if __name__ == "__main__":
    asyncio.run(main())
