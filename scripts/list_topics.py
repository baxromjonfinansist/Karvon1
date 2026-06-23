"""LORRY forum guruhidagi mavzular (topics) ro'yxati — read-only."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient, functions  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.services.session_manager import get_session_path  # noqa: E402


async def main() -> None:
    client = TelegramClient(
        get_session_path(), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("NOT_AUTHORIZED")
        return

    for cid in settings.channel_ids_list:
        print(f"\n=== Kanal {cid} ===")
        try:
            res = await client(functions.channels.GetForumTopicsRequest(
                channel=cid, offset_date=0, offset_id=0, offset_topic=0, limit=100,
            ))
            print(f"Mavzular soni: {len(res.topics)}")
            for t in res.topics:
                title = getattr(t, "title", "?")
                tid = getattr(t, "id", "?")
                print(f"  topic_id={tid}\t{title}")
        except Exception as e:
            print(f"  Forum emas yoki xato: {type(e).__name__}: {e}")

        # Bir nechta xabarning topic mapping'ini ko'rish
        print("  --- so'nggi xabarlar va ularning topic_id si ---")
        try:
            async for m in client.iter_messages(cid, limit=6):
                top = None
                if m.reply_to is not None:
                    top = getattr(m.reply_to, "reply_to_top_id", None) or getattr(
                        m.reply_to, "reply_to_msg_id", None
                    )
                txt = (m.text or "").replace("\n", " ")[:45]
                print(f"    msg_id={m.id} topic_id={top} | {txt}")
        except Exception as e:
            print(f"    xato: {e}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
