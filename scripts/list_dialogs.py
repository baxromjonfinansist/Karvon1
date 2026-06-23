"""Saqlangan sessiya orqali guruh/kanallar ro'yxatini chiqaradi (interaktiv emas)."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.services.session_manager import get_session_path  # noqa: E402


async def main() -> None:
    client = TelegramClient(
        get_session_path(),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("NOT_AUTHORIZED")
        return

    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            print(f"{dialog.id}\t{dialog.title}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
