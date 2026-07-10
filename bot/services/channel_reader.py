from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bot.config import settings
from bot.services.session_manager import get_session_path
from db.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_client: Optional[object] = None
_running = False

POLL_INTERVAL = 30        # soniya — yangi xabarlarni tekshirish oralig'i
POLL_LIMIT = 100          # har poll'da maks. yangi xabar
BACKFILL_LIMIT = 200      # ishga tushganda har kanaldan o'qiladigan eski xabar


def _is_lorry_channel(channel: str) -> bool:
    """Kanal LORRY (ichki tashuvlar) guruhimi — logist aniqlash faqat shularda."""
    try:
        return int(channel) in settings.lorry_channel_ids_list
    except (ValueError, TypeError):
        return False


def _topic_id_of(message) -> Optional[int]:
    """Forum xabarining mavzu (topic) ID sini qaytaradi (yoki None)."""
    rt = getattr(message, "reply_to", None)
    if rt is None:
        return None
    tid = getattr(rt, "reply_to_top_id", None)
    if tid is not None:
        return tid
    if getattr(rt, "forum_topic", False):
        return getattr(rt, "reply_to_msg_id", None)
    return None


async def _build_topic_map(client, channel_id) -> Optional[dict]:
    """{topic_id: Viloyat nomi} — forum mavzularidan tuziladi.

    Faqat 14 rasmiy viloyatga mos keladigan mavzular qabul qilinadi (aniqlash
    parser_service'dagi shahar-alias jadvali orqali). "Premium", "🚛 haydovchi
    e'lonlari", "Elon berish", "General" kabi viloyat bo'lmagan mavzular
    filtrlanadi — aks holda ular ham "viloyat" sifatida bazaga tushib,
    haydovchi menyusida (ALL_VILOYATS) begona qator bo'lib chiqadi.

    Oddiy (forum bo'lmagan) guruh uchun None qaytaradi — bunday guruhda
    yo'nalish har bir xabar matnidan alohida o'qiladi (_process_message).
    """
    from telethon import functions
    from telethon.errors import ChannelForumMissingError

    from bot.services.parser_service import to_viloyat, _find_city_in
    from bot.services.load_service import ALL_VILOYATS

    region_by_topic: dict = {}
    try:
        res = await client(functions.channels.GetForumTopicsRequest(
            channel=channel_id, offset_date=0, offset_id=0, offset_topic=0, limit=100,
        ))
    except ChannelForumMissingError:
        return None  # oddiy guruh — forum emas
    except Exception as exc:
        log.warning("Forum mavzularini o'qib bo'lmadi [%s]: %s", channel_id, exc)
        return region_by_topic
    for t in res.topics:
        title = getattr(t, "title", None)
        tid = getattr(t, "id", None)
        if not title or tid is None:
            continue
        viloyat = to_viloyat(_find_city_in(title))
        if viloyat not in ALL_VILOYATS:
            log.info("Mavzu '%s' viloyat emas — o'tkazib yuborildi [%s]", title.strip(), channel_id)
            continue
        region_by_topic[tid] = viloyat
    return region_by_topic


async def _process_message(
    text: str, channel: str, regions: Optional[dict], topic_id: Optional[int], posted_at=None
) -> None:
    """Xabarni parse qilib, yo'nalish+telefon bo'lsa bazaga saqlaydi.

    Forum guruh (regions — dict): origin = mavzu viloyati, destination = matndan.
    Oddiy guruh (regions=None): origin HAM, destination HAM matndan o'qiladi.
    Telefon har doim majburiy. Narx umuman o'qilmaydi.
    """
    from bot.services.parser_service import (
        ParsedLoad,
        _extract_contact,
        _extract_route,
        _extract_weight,
        extract_destination_freetext,
        extract_note,
        save_parsed_load,
        to_viloyat,
    )

    if not text or len(text.strip()) < 8:
        return

    if regions is not None:
        # Forum guruh: mavzu aniqlanmasa (General/Elon berish) — tashlanadi.
        region = regions.get(topic_id)
        if not region:
            return
        origin = region
        destination = extract_destination_freetext(text)
    else:
        # Oddiy guruh: mavzu yo'q — yo'nalish to'liq matndan o'qiladi.
        # Origin viloyatga aylantiriladi (masalan Chortoq -> Namangan) —
        # viloyat menyusi LORRY kabi toza qolishi uchun.
        origin, destination = _extract_route(text)
        origin = to_viloyat(origin)

    if not origin or not destination or destination == origin:
        return  # yo'nalish topilmadi yoki origin=destination -> tashlanadi

    contact = _extract_contact(text)  # normallashtirilgan: +998 XX XXX XX XX
    if not contact:
        return  # telefon yo'q -> tashlanadi

    # Qo'lda-logist ro'yxati (admin qarori) — har qanday kanalda, algoritmdan ustun.
    from bot.services.logist_service import is_blocklisted
    if is_blocklisted(contact):
        log.info("🚫 Qo'lda-logist tel=%s — bazaga qo'shilmadi", contact)
        return

    # Telegram post vaqtini naive UTC ga keltiramiz (bazadagi ustun naive).
    if posted_at is not None and posted_at.tzinfo is not None:
        posted_at = posted_at.replace(tzinfo=None)

    parsed = ParsedLoad(
        origin=origin,
        destination=destination,
        cargo_type=None,
        weight_t=_extract_weight(text),
        contact=contact,
        note=extract_note(text),
        confidence=1.0,  # yo'nalish + telefon bor — ishonchli
    )

    async with AsyncSessionLocal() as session:
        # LORRY guruhida — logist aniqlash (route diversity, 12h). Boshqa
        # guruhlarda logist tushunchasi yo'q: to'g'ridan bazaga tushadi.
        if _is_lorry_channel(channel):
            from bot.services.logist_service import Label, evaluate_and_record

            decision = await evaluate_and_record(
                session,
                phone_raw=contact,
                origin=origin,
                dest=destination,
                source_group=channel,
                raw_text=text,
                posted_at=posted_at,
            )
            if decision and decision.label == Label.LOGIST:
                await session.commit()  # tarix saqlanadi, LEKIN yuk bazasiga tushmaydi
                log.info(
                    "🚫 LOGIST tel=%s distinct=%d/%dh — bazaga qo'shilmadi",
                    decision.phone, decision.distinct_routes, decision.window_hours,
                )
                return
            if decision and decision.label == Label.SUSPICIOUS:
                log.warning(
                    "⚠️ SUSPICIOUS tel=%s distinct=%d/%dh — bazaga tushdi (kuzatuv)",
                    decision.phone, decision.distinct_routes, decision.window_hours,
                )

        load = await save_parsed_load(
            session, parsed, text, channel,
            auto_approve_threshold=settings.PARSER_AUTO_APPROVE_CONFIDENCE,
            posted_at=posted_at,
        )
        if load is None:  # dublikat (Load) — lekin LORRY tarixi saqlanishi mumkin
            await session.commit()
            return
        await session.commit()

    log.info("✅ Yuk: %s→%s tel=%s status=%s", origin, destination, contact, load.status.value)


async def start_reader(_dp: object = None) -> None:
    """Telethon polling — forum mavzulari (viloyat) bo'yicha yuklarni o'qiydi."""
    global _client, _running

    try:
        from telethon import TelegramClient
    except ImportError:
        log.warning("telethon o'rnatilmagan — kanal o'quvchi ishlamaydi.")
        return

    channel_ids = settings.channel_ids_list
    if not channel_ids:
        log.info("CHANNEL_IDS sozlanmagan — kanal o'quvchi o'chirildi.")
        return
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        log.warning("TELEGRAM_API_ID/HASH yo'q — kanal o'quvchi o'chirildi.")
        return

    _client = TelegramClient(
        get_session_path(), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH
    )
    await _client.start(phone=settings.TELEGRAM_PHONE or None)
    _running = True

    # Har kanal uchun mavzu→viloyat xaritasi (oddiy guruh uchun None)
    topic_maps: dict = {}
    for cid in channel_ids:
        tm = await _build_topic_map(_client, cid)
        topic_maps[cid] = tm
        if tm is None:
            log.info("Kanal %s — oddiy guruh (forum emas), yo'nalish matndan o'qiladi.", cid)
        else:
            log.info("Kanal %s — %d ta viloyat mavzusi topildi.", cid, len(tm))

    log.info("Telethon kanal o'quvchi (polling) ulandi ✅")

    # Qo'lda-logist ro'yxatini keshga yuklaymiz (backfill'dan oldin ham amal qilsin).
    try:
        from bot.services.logist_service import refresh_blocklist
        async with AsyncSessionLocal() as session:
            n = await refresh_blocklist(session)
        log.info("Qo'lda-logist ro'yxati yuklandi: %d ta raqam.", n)
    except Exception as exc:  # noqa: BLE001
        log.error("Blocklist yuklash xato: %s", exc)

    last_ids: dict = {}

    # --- Backfill ---
    for cid in channel_ids:
        regions = topic_maps[cid]
        max_id = 0
        try:
            async for m in _client.iter_messages(cid, limit=BACKFILL_LIMIT):
                if m.id > max_id:
                    max_id = m.id
                await _process_message(m.text or "", str(cid), regions, _topic_id_of(m), m.date)
        except Exception as exc:
            log.error("Backfill xato [%s]: %s", cid, exc)
        last_ids[cid] = max_id

    # LORRY tarix jadvalidan oynadan ancha eski (48s+) yozuvlarni tozalaymiz.
    if settings.lorry_channel_ids_list:
        try:
            from bot.services.logist_service import purge_old_listings
            async with AsyncSessionLocal() as session:
                removed = await purge_old_listings(session)
                await session.commit()
            if removed:
                log.info("LORRY tarixidan %d eski yozuv tozalandi.", removed)
        except Exception as exc:  # noqa: BLE001
            log.error("LORRY purge xato: %s", exc)

    log.info("Backfill tugadi. Har %ss da yangi yuklar tekshiriladi.", POLL_INTERVAL)

    # --- Polling ---
    while _running:
        await asyncio.sleep(POLL_INTERVAL)
        # Qo'lda-logist ro'yxatini yangilab turamiz (admin qo'shsa, tez amal qilsin).
        try:
            from bot.services.logist_service import refresh_blocklist
            async with AsyncSessionLocal() as session:
                await refresh_blocklist(session)
        except Exception as exc:  # noqa: BLE001
            log.error("Blocklist refresh xato: %s", exc)
        for cid in channel_ids:
            regions = topic_maps[cid]
            try:
                msgs = await _client.get_messages(
                    cid, min_id=last_ids.get(cid, 0), limit=POLL_LIMIT
                )
                for m in reversed(msgs):
                    if m.id > last_ids.get(cid, 0):
                        last_ids[cid] = m.id
                    await _process_message(m.text or "", str(cid), regions, _topic_id_of(m), m.date)
            except Exception as exc:
                log.error("Polling xato [%s]: %s", cid, exc)


async def stop_reader() -> None:
    """Telethon clientni to'xtatadi."""
    global _client, _running
    _running = False
    if _client is not None:
        try:
            await _client.disconnect()
            log.info("Telethon kanal o'quvchi to'xtatildi.")
        except Exception:
            pass
        _client = None
