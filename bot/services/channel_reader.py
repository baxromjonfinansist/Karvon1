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


async def _build_topic_map(client, channel_id) -> dict:
    """{topic_id: Viloyat nomi} — forum mavzularidan tuziladi."""
    from telethon import functions

    region_by_topic: dict = {}
    try:
        res = await client(functions.channels.GetForumTopicsRequest(
            channel=channel_id, offset_date=0, offset_id=0, offset_topic=0, limit=100,
        ))
        for t in res.topics:
            title = getattr(t, "title", None)
            tid = getattr(t, "id", None)
            if not title or tid is None:
                continue
            if title.strip().upper() in ("ELON BERISH", "GENERAL"):
                continue
            region_by_topic[tid] = title.strip().capitalize()
    except Exception as exc:
        log.warning("Forum mavzularini o'qib bo'lmadi [%s]: %s", channel_id, exc)
    return region_by_topic


async def _process_message(text: str, channel: str, region: Optional[str]) -> None:
    """Xabarni parse qilib, yo'nalish+telefon bo'lsa bazaga saqlaydi.

    Yo'nalish: origin = mavzu viloyati (region), destination = matndan.
    Telefon majburiy — bo'lmasa saqlanmaydi.
    """
    from bot.services.parser_service import (
        ParsedLoad,
        _extract_contact,
        _extract_price,
        _extract_weight,
        extract_destination_freetext,
    )
    from bot.services.parser_service import save_parsed_load

    if not text or len(text.strip()) < 8:
        return

    # Mavzu (viloyat) aniqlanmasa — kategoriyalab bo'lmaydi, tashlanadi.
    if not region:
        return
    origin = region

    contact = _extract_contact(text)
    if not contact:
        return  # telefon yo'q -> tashlanadi

    destination = extract_destination_freetext(text)
    if not destination or destination == origin:
        return  # manzil yo'q yoki origin bilan bir xil -> tashlanadi

    parsed = ParsedLoad(
        origin=origin,
        destination=destination,
        cargo_type=None,
        weight_t=_extract_weight(text),
        price=_extract_price(text),
        contact=contact,
        confidence=1.0,  # yo'nalish + telefon bor — ishonchli
    )

    async with AsyncSessionLocal() as session:
        load = await save_parsed_load(
            session, parsed, text, channel,
            auto_approve_threshold=settings.PARSER_AUTO_APPROVE_CONFIDENCE,
        )
        if load is None:  # dublikat
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

    # Har kanal uchun mavzu→viloyat xaritasi
    topic_maps: dict = {}
    for cid in channel_ids:
        topic_maps[cid] = await _build_topic_map(_client, cid)
        log.info("Kanal %s — %d ta viloyat mavzusi topildi.", cid, len(topic_maps[cid]))

    log.info("Telethon kanal o'quvchi (polling) ulandi ✅")

    last_ids: dict = {}

    # --- Backfill ---
    for cid in channel_ids:
        regions = topic_maps[cid]
        max_id = 0
        try:
            async for m in _client.iter_messages(cid, limit=BACKFILL_LIMIT):
                if m.id > max_id:
                    max_id = m.id
                region = regions.get(_topic_id_of(m))
                await _process_message(m.text or "", str(cid), region)
        except Exception as exc:
            log.error("Backfill xato [%s]: %s", cid, exc)
        last_ids[cid] = max_id
    log.info("Backfill tugadi. Har %ss da yangi yuklar tekshiriladi.", POLL_INTERVAL)

    # --- Polling ---
    while _running:
        await asyncio.sleep(POLL_INTERVAL)
        for cid in channel_ids:
            regions = topic_maps[cid]
            try:
                msgs = await _client.get_messages(
                    cid, min_id=last_ids.get(cid, 0), limit=POLL_LIMIT
                )
                for m in reversed(msgs):
                    if m.id > last_ids.get(cid, 0):
                        last_ids[cid] = m.id
                    region = regions.get(_topic_id_of(m))
                    await _process_message(m.text or "", str(cid), region)
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
