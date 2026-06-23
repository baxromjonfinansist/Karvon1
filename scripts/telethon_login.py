"""Bir martalik Telethon login + guruh ID sini topish.

Terminalda ishga tushiring:
    python3 scripts/telethon_login.py

• SMS/Telegram kodi telefoningizga keladi — uni shu yerda kiritasiz.
• 2FA parolingiz YASHIRIN so'raladi (ekranda ko'rinmaydi) va HECH QAYERGA saqlanmaydi.
• Login bo'lgach sessiya `data/telethon_session` ga saqlanadi — keyin parol qayta so'ralmaydi.
• Oxirida guruh/kanallaringiz ro'yxati ID lari bilan chiqadi.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.services.session_manager import get_session_path  # noqa: E402


async def main() -> None:
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        print("❌ .env da TELEGRAM_API_ID / TELEGRAM_API_HASH yo'q.")
        return

    client = TelegramClient(
        get_session_path(),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )

    # start() interaktiv: kodni input() bilan, 2FA parolni getpass (yashirin) bilan so'raydi.
    # Parol bu yerda faqat bir marta ishlatiladi — hech qaysi faylga yozilmaydi.
    await client.start(phone=settings.TELEGRAM_PHONE or None)

    me = await client.get_me()
    print(f"\n✅ Login muvaffaqiyatli: {me.first_name} (id={me.id})\n")
    print("Guruh va kanallaringiz (ID lari bilan):\n")
    print(f"  {'ID':>16}   Nomi")
    print(f"  {'-' * 16}   {'-' * 30}")

    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            print(f"  {dialog.id:>16}   {dialog.title}")

    print(
        "\n⬆️ Kerakli guruh ID sini (-100... bilan boshlanadi) menga ayting "
        "yoki .env dagi CHANNEL_IDS ga yozing.\n"
    )
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
