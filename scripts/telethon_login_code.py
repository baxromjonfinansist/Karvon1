"""Serverda (stdin'siz) Telethon login — ikki qadamda.

`telethon_login.py` interaktiv: kodni `input()` bilan so'raydi. Serverda
(systemd/SSH buyrug'i ostida) stdin yo'q, shu sabab bu skript kodni
argument orqali oladi va holatni sessiya faylida saqlaydi.

Ishlatish:

    systemctl stop yukbot                       # sessiyani band qilmaslik uchun
    python3 scripts/telethon_login_code.py send        # kod so'raydi
    python3 scripts/telethon_login_code.py verify 12345
    systemctl start yukbot

2FA parol yoqilgan bo'lsa `verify` shuni aytadi; parolni HECH QAYERGA
saqlamaslik uchun uni faqat muhit o'zgaruvchisi orqali beriladi:

    TELETHON_2FA=... python3 scripts/telethon_login_code.py verify 12345
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402
from telethon.errors import (  # noqa: E402
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from bot.config import settings  # noqa: E402
from bot.services.session_manager import get_session_path  # noqa: E402

# `phone_code_hash` ni ikki qadam orasida saqlaydi (kod emas — faqat hash).
STATE_FILE = Path("data/login_state.json")


def _client() -> TelegramClient:
    return TelegramClient(
        get_session_path(), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH
    )


async def send_code() -> None:
    phone = settings.TELEGRAM_PHONE
    if not phone:
        print("❌ .env da TELEGRAM_PHONE yo'q.")
        return

    client = _client()
    await client.connect()
    if await client.is_user_authorized():
        print("✅ Sessiya allaqachon avtorizatsiyadan o'tgan — login kerak emas.")
        await client.disconnect()
        return

    sent = await client.send_code_request(phone)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "phone": phone,
        "phone_code_hash": sent.phone_code_hash,
    }))
    await client.disconnect()
    print(
        f"📨 Kod yuborildi: {phone} (Telegram ilovasi yoki SMS).\n"
        f"Keyin: python3 scripts/telethon_login_code.py verify <KOD>"
    )


async def verify(code: str) -> None:
    if not STATE_FILE.exists():
        print("❌ Avval `send` buyrug'ini bajaring.")
        return
    state = json.loads(STATE_FILE.read_text())

    client = _client()
    await client.connect()
    try:
        await client.sign_in(
            phone=state["phone"],
            code=code.strip(),
            phone_code_hash=state["phone_code_hash"],
        )
    except SessionPasswordNeededError:
        password = os.getenv("TELETHON_2FA")
        if not password:
            print(
                "🔐 2FA parol kerak. Qayta ishga tushiring:\n"
                "   TELETHON_2FA='parolingiz' python3 "
                "scripts/telethon_login_code.py verify <KOD>"
            )
            await client.disconnect()
            return
        await client.sign_in(password=password)
    except PhoneCodeInvalidError:
        print("❌ Kod noto'g'ri — qaytadan `send` qilib, yangi kodni kiriting.")
        await client.disconnect()
        return
    except PhoneCodeExpiredError:
        print("❌ Kod muddati o'tgan — qaytadan `send` qiling.")
        await client.disconnect()
        return

    me = await client.get_me()
    await client.disconnect()
    STATE_FILE.unlink(missing_ok=True)      # hash endi kerak emas
    print(f"✅ Login muvaffaqiyatli: {me.first_name} (id={me.id})")
    print("Endi: systemctl start yukbot")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("send", "verify"):
        print(__doc__)
        return
    if sys.argv[1] == "send":
        asyncio.run(send_code())
    else:
        if len(sys.argv) < 3:
            print("❌ Kodni bering: verify 12345")
            return
        asyncio.run(verify(sys.argv[2]))


if __name__ == "__main__":
    main()
