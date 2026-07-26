"""Kanal → parser pipeline diagnostikasi: yuk qaysi bosqichda tushib qolyapti.

Ishlatish (SERVERDA, bot ishlab turgan holda ham xavfsiz — ALOHIDA sessiya):

    TELETHON_SESSION_NAME=diag_session python3 scripts/diag_reader.py

Birinchi ishga tushirishda kod so'raydi (alohida sessiya login qiladi).
Bazaga HECH NARSA yozmaydi — faqat o'qiydi va sanaydi.

Chiqishi:
  • kanal forum ekanmi, qaysi mavzular viloyat deb qabul qilingani
  • oxirgi N xabar taqdiri: ok / no_topic / no_route / no_phone / blocklist
  • har bir drop sababi uchun namuna matn

MUHIM: `TELETHON_SESSION_NAME` bermasangiz bot bilan BIR sessiyani
ishlatadi va Telegram auth key ni bekor qiladi (AuthKeyDuplicatedError) —
reader o'lib qoladi. Shu sabab skript nomni majburlaydi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.services.channel_reader import (  # noqa: E402
    _build_topic_map,
    _topic_id_of,
    prepare_message,
)
from bot.services.session_manager import (  # noqa: E402
    DEFAULT_SESSION_NAME,
    ENV_SESSION_NAME,
    get_session_path,
)

LIMIT = int(os.environ.get("DIAG_LIMIT", "200"))


async def main() -> None:
    session_name = os.getenv(ENV_SESSION_NAME)
    if not session_name or session_name == DEFAULT_SESSION_NAME:
        print(
            f"❌ {ENV_SESSION_NAME} ni bering (bot sessiyasidan boshqa nom):\n"
            f"   {ENV_SESSION_NAME}=diag_session python3 scripts/diag_reader.py"
        )
        return

    print(f"Sessiya: {get_session_path()}")
    print(f"CHANNEL_IDS      = {settings.channel_ids_list}")
    print(f"LORRY_CHANNEL_IDS= {settings.lorry_channel_ids_list}")
    print(f"AUTO_APPROVE     = {settings.PARSER_AUTO_APPROVE_CONFIDENCE}\n")

    client = TelegramClient(
        get_session_path(), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH
    )
    await client.start(phone=settings.TELEGRAM_PHONE or None)

    for cid in settings.channel_ids_list:
        print(f"=== KANAL {cid} ===")
        try:
            ent = await client.get_entity(cid)
            print(f"  Nomi: {getattr(ent, 'title', '?')}  forum={getattr(ent, 'forum', None)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ ENTITY XATO: {type(exc).__name__}: {exc}")
            continue

        try:
            regions = await _build_topic_map(client, cid)
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ TOPIC MAP XATO: {type(exc).__name__}: {exc}")
            continue

        if regions is None:
            print("  Rejim: oddiy guruh — yo'nalish matndan o'qiladi")
        else:
            print(f"  Rejim: forum — {len(regions)} viloyat mavzusi")
            for tid, vil in regions.items():
                print(f"    [{tid:>7}] -> {vil}")

        reasons: Counter = Counter()
        samples: dict = {}
        total = 0
        async for m in client.iter_messages(cid, limit=LIMIT):
            total += 1
            text = m.text or ""
            parsed, reason = prepare_message(text, regions, _topic_id_of(m))
            key = reason if parsed is None else "ok"
            reasons[key] += 1
            if key not in samples:
                info = f"{parsed.origin}→{parsed.destination} {parsed.contact}" if parsed else ""
                samples[key] = (info, text[:160].replace("\n", " | "))

        print(f"\n  Jami xabar: {total}")
        for reason, count in reasons.most_common():
            share = 100 * count / total if total else 0
            print(f"    {reason:<12} {count:>4}  ({share:.0f}%)")

        print("\n  --- namunalar ---")
        for key, (info, txt) in samples.items():
            print(f"  [{key}] {info}\n      {txt!r}\n")

    await client.disconnect()
    print(
        "Izoh: 'ok' bo'lgan xabarlar bazaga tushishi kerak. Agar 'ok' bor, "
        "lekin bazada yuk yo'q bo'lsa — logist filtri yoki dublikat to'sib "
        "turgan bo'ladi: botda /reader ni tekshiring."
    )


if __name__ == "__main__":
    asyncio.run(main())
