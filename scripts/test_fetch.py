"""Guruhlardan oxirgi xabarlarni o'qib, kirish va faollikni tekshiradi."""
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

    for cid in settings.channel_ids_list:
        print(f"\n=== {cid} ===")
        try:
            ent = await client.get_entity(cid)
            print(f"Nomi: {getattr(ent, 'title', '?')}")
            msgs = await client.get_messages(cid, limit=5)
            for m in msgs:
                txt = (m.text or "").replace("\n", " ")[:70]
                print(f"  [{m.date:%H:%M:%S}] {txt}")
        except Exception as e:
            print(f"  XATO: {type(e).__name__}: {e}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
