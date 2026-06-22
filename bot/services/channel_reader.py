from __future__ import annotations

import logging
from typing import Optional

from bot.config import settings
from bot.services.session_manager import get_session_path
from db.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_client: Optional[object] = None


async def start_reader(_dp: object = None) -> None:
    """
    Start a Telethon user-account client that listens to configured channels.
    Runs indefinitely (until stop_reader() is called or connection drops).
    First run: phone verification prompt appears in terminal.
    Subsequent runs: session file handles auth automatically.
    """
    global _client

    try:
        from telethon import TelegramClient, events
    except ImportError:
        log.warning("telethon o'rnatilmagan — kanal o'quvchi ishlamaydi. pip install telethon")
        return

    channel_ids = settings.channel_ids_list
    if not channel_ids:
        log.info("CHANNEL_IDS sozlanmagan — kanal o'quvchi o'chirildi.")
        return

    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        log.warning("TELEGRAM_API_ID / TELEGRAM_API_HASH yo'q — kanal o'quvchi o'chirildi.")
        return

    _client = TelegramClient(
        get_session_path(),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )

    await _client.start(phone=settings.TELEGRAM_PHONE or None)
    log.info("Telethon kanal o'quvchi ulandi ✅  (kanallar: %s)", channel_ids)

    @_client.on(events.NewMessage(chats=channel_ids))
    async def _on_message(event) -> None:
        from bot.services.parser_service import parse_load, save_parsed_load

        raw_text: str = event.message.text or ""
        if len(raw_text.strip()) < 10:
            return

        channel = str(event.chat_id)
        try:
            parsed = await parse_load(raw_text, settings.OPENAI_API_KEY)

            # Ignore if we couldn't determine at least one city
            if not parsed.origin and not parsed.destination:
                return

            async with AsyncSessionLocal() as session:
                load = await save_parsed_load(
                    session,
                    parsed,
                    raw_text,
                    channel,
                    auto_approve_threshold=settings.PARSER_AUTO_APPROVE_CONFIDENCE,
                )
                await session.commit()

            log.info(
                "Yangi yuk qabul qilindi: kanal=%s id=%s status=%s confidence=%.2f",
                channel,
                load.id,
                load.status.value,
                parsed.confidence,
            )
        except Exception as exc:
            log.error("Kanal xabarini qayta ishlashda xato [kanal=%s]: %s", channel, exc)

    await _client.run_until_disconnected()


async def stop_reader() -> None:
    """Gracefully disconnect the Telethon client."""
    global _client
    if _client is not None:
        try:
            await _client.disconnect()
            log.info("Telethon kanal o'quvchi to'xtatildi.")
        except Exception:
            pass
        _client = None
