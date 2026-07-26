from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bot.config import settings
from bot.services import reader_status as rs
from bot.services.reader_status import status
from bot.services.session_manager import get_session_path
from db.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_client: Optional[object] = None
_running = False

POLL_INTERVAL = 30        # soniya — yangi xabarlarni tekshirish oralig'i
POLL_LIMIT = 100          # har poll'da maks. yangi xabar
BACKFILL_LIMIT = 200      # ishga tushganda har kanaldan o'qiladigan eski xabar

BACKOFF_BASE = 15         # soniya — birinchi qayta ulanish kutish vaqti
BACKOFF_MAX = 600         # soniya — maksimal kutish (10 daqiqa)

# Bu xatolarda qayta ulanish FOYDASIZ — sessiya butunlay bekor qilingan,
# faqat qayta login yordam beradi. Nom bo'yicha tekshiramiz: telethon
# ixtiyoriy dependency, modul importida uni majburlamaymiz.
FATAL_AUTH_ERRORS = frozenset({
    "AuthKeyDuplicatedError",     # bitta sessiya ikki IP da ishlatilgan
    "AuthKeyUnregisteredError",
    "AuthKeyInvalidError",
    "AuthKeyPermEmptyError",
    "SessionRevokedError",
    "SessionExpiredError",
    "SessionPasswordNeededError",
    "UserDeactivatedError",
    "UserDeactivatedBanError",
    "PhoneNumberBannedError",
})


def is_fatal_auth_error(exc: BaseException) -> bool:
    """Sessiya bekor qilinganmi (retry foydasiz, qayta login shart)?"""
    return type(exc).__name__ in FATAL_AUTH_ERRORS


def next_backoff(attempt: int) -> int:
    """Qayta ulanishgacha kutish (eksponensial, BACKOFF_MAX bilan cheklangan)."""
    delay = BACKOFF_BASE * (2 ** max(0, attempt - 1))
    return min(delay, BACKOFF_MAX)


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

    Faqat 14 rasmiy viloyatga mos keladigan mavzular qabul qilinadi ("Premium",
    "Elon berish", "General" kabi mavzular filtrlanadi — aks holda ular ham
    haydovchi menyusida begona qator bo'lib chiqadi).

    Qaytaradi:
      - dict — forum guruh, viloyat mavzulari topildi (origin = mavzu).
      - None — forum emas YOKI viloyat mavzusi topilmadi: yo'nalish har bir
        xabar matnidan o'qiladi. MUHIM: ilgari bu holatda bo'sh dict
        qaytardi va natijada HAR BIR xabar "no_topic" bo'lib tashlanardi
        (bazaga bitta ham yuk tushmasdi).

    Kutilmagan xatoni YUTMAYDI — ko'taradi, supervisor qayta uradi.
    """
    from telethon import functions
    from telethon.errors import ChannelForumMissingError

    from bot.services.load_service import ALL_VILOYATS
    from bot.services.parser_service import _find_city_in, to_viloyat

    try:
        res = await client(functions.channels.GetForumTopicsRequest(
            channel=channel_id, offset_date=0, offset_id=0, offset_topic=0, limit=100,
        ))
    except ChannelForumMissingError:
        return None  # oddiy guruh — forum emas

    region_by_topic: dict = {}
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

    if not region_by_topic:
        log.error(
            "Kanal %s forum, lekin viloyat mavzusi topilmadi (%d mavzu ko'rildi) — "
            "yo'nalish matndan o'qiladi.", channel_id, len(res.topics),
        )
        return None
    return region_by_topic


def prepare_message(
    text: str, regions: Optional[dict], topic_id: Optional[int]
):
    """Xabarni parse qiladi. Qaytaradi: (ParsedLoad|None, sabab).

    Sof funksiya (DB'siz) — shu sabab har bir drop sababi test qilinadi.

    Forum guruh (regions — dict): origin = mavzu viloyati, destination = matndan.
    Oddiy guruh (regions=None): origin HAM, destination HAM matndan o'qiladi.
    Telefon har doim majburiy. Narx umuman o'qilmaydi.
    """
    from bot.services.logist_service import is_blocklisted
    from bot.services.parser_service import (
        ParsedLoad,
        _extract_cargo_type,
        _extract_contact,
        _extract_route,
        _extract_weight,
        extract_destination_freetext,
        extract_note,
        to_viloyat,
    )

    if not text or len(text.strip()) < 8:
        return None, rs.NO_TEXT

    if regions is not None:
        # Forum guruh: mavzu viloyat bo'lmasa (General/Elon berish) — tashlanadi.
        region = regions.get(topic_id)
        if not region:
            return None, rs.NO_TOPIC
        origin = region
        destination = extract_destination_freetext(text)
    else:
        # Oddiy guruh: yo'nalish to'liq matndan. Origin viloyatga aylantiriladi
        # (Chortoq -> Namangan) — viloyat menyusi toza qolishi uchun.
        origin, destination = _extract_route(text)
        origin = to_viloyat(origin)

    if not origin or not destination or destination == origin:
        return None, rs.NO_ROUTE

    contact = _extract_contact(text)   # normallashtirilgan: +998XXXXXXXXX
    if not contact:
        return None, rs.NO_PHONE

    # Qo'lda-logist ro'yxati (admin qarori) — har qanday kanalda, algoritmdan ustun.
    if is_blocklisted(contact):
        return None, rs.BLOCKLIST

    return (
        ParsedLoad(
            origin=origin,
            destination=destination,
            cargo_type=_extract_cargo_type(text),
            weight_t=_extract_weight(text),
            contact=contact,
            note=extract_note(text),
            confidence=1.0,  # yo'nalish (forum topic / regex) + telefon bor
        ),
        rs.OK,
    )


async def _process_message(
    text: str, channel: str, regions: Optional[dict], topic_id: Optional[int], posted_at=None
) -> None:
    """Xabarni parse qilib, yo'nalish+telefon bo'lsa bazaga saqlaydi.

    Har bir xabar taqdiri `reader_status` da sanaladi — admin `/reader` da
    ko'radi (nima uchun yuk tushmadi degan savol darhol javob topadi).
    """
    from bot.services.parser_service import save_parsed_load

    parsed, reason = prepare_message(text, regions, topic_id)
    if parsed is None:
        status.note(reason)
        if reason == rs.BLOCKLIST:
            log.info("🚫 Qo'lda-logist — bazaga qo'shilmadi: %r", text[:60])
        else:
            log.debug("DROP(%s) ch=%s text=%r", reason, channel, text[:80])
        return

    # Telegram post vaqtini naive UTC ga keltiramiz (bazadagi ustun naive).
    if posted_at is not None and posted_at.tzinfo is not None:
        posted_at = posted_at.replace(tzinfo=None)

    async with AsyncSessionLocal() as session:
        # LORRY guruhida — logist aniqlash (route diversity, 12h). Boshqa
        # guruhlarda logist tushunchasi yo'q: to'g'ridan bazaga tushadi.
        if _is_lorry_channel(channel):
            from bot.services.logist_service import Label, evaluate_and_record

            decision = await evaluate_and_record(
                session,
                phone_raw=parsed.contact,
                origin=parsed.origin,
                dest=parsed.destination,
                source_group=channel,
                raw_text=text,
                posted_at=posted_at,
            )
            if decision and decision.label == Label.LOGIST:
                await session.commit()  # tarix saqlanadi, LEKIN yuk bazasiga tushmaydi
                status.note(rs.LOGIST)
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
            status.note(rs.DUPLICATE)
            return
        await session.commit()
        load_status = load.status.value

    status.note(rs.SAVED)
    log.info(
        "✅ Yuk: %s→%s tel=%s status=%s",
        parsed.origin, parsed.destination, parsed.contact, load_status,
    )


async def run_reader_forever(bot=None) -> None:
    """Reader supervisori — xato bo'lsa qayta ulanadi, sessiya o'lsa xabar beradi.

    Ilgari reader `create_task(start_reader())` bilan ishga tushirilgan:
    startup'dagi xato (masalan sessiya bekor bo'lishi) jim yutilib, bot
    "ishlab turgan" holda reader butunlay o'lik bo'lib qolgan — yuklar
    bazasiga tushmagan va buni hech narsa ko'rsatmagan.
    """
    attempt = 0
    while True:
        attempt += 1
        connected_before = status.connected_at
        status.mark_connecting()
        try:
            await start_reader()
            # Normal chiqish (stop_reader). Sozlama xatosi bo'lsa (masalan
            # CHANNEL_IDS yo'q) start_reader ERROR holatini qoldiradi — uni
            # o'chirmaymiz, admin `/reader` da ko'rishi kerak.
            if status.state != rs.ERROR:
                status.mark_stopped()
            return
        except asyncio.CancelledError:
            status.mark_stopped()
            raise
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"
            await _safe_disconnect()

            if is_fatal_auth_error(exc):
                status.mark_needs_login(detail)
                log.error("🔴 Telethon sessiya bekor — QAYTA LOGIN kerak: %s", detail)
                await _alert_admins(bot, (
                    "🔴 <b>Kanal o'quvchi to'xtadi</b>\n\n"
                    f"{detail}\n\n"
                    "Sessiya bekor qilingan (ko'p hollarda bitta sessiya fayli "
                    "server va boshqa kompyuterda bir vaqtda ishlatilgani uchun).\n\n"
                    "Yechim — serverda qayta login:\n"
                    "<code>python3 scripts/telethon_login.py</code>"
                ))
                return

            # Ulangandan keyin uzilgan bo'lsa — backoff'ni noldan boshlaymiz.
            if status.connected_at != connected_before:
                attempt = 1
            delay = next_backoff(attempt)
            status.mark_error(detail)
            log.error(
                "Kanal o'quvchi xato (#%d): %s — %ss dan keyin qayta ulanadi",
                attempt, detail, delay, exc_info=True,
            )
            if attempt in (1, 5) or attempt % 20 == 0:
                await _alert_admins(bot, (
                    f"🟠 Kanal o'quvchi xatosi (#{attempt}):\n<code>{detail}</code>\n"
                    f"{delay}s dan keyin qayta ulanadi."
                ))
            await asyncio.sleep(delay)


async def _alert_admins(bot, text: str) -> None:
    """Adminlarga ogohlantirish yuboradi (bot bo'lmasa — faqat log)."""
    if bot is None:
        return
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Adminga (%s) xabar yuborilmadi: %s", admin_id, exc)


async def _safe_disconnect() -> None:
    global _client
    if _client is not None:
        try:
            await _client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        _client = None


async def start_reader(_dp: object = None) -> None:
    """Telethon polling — forum mavzulari (viloyat) bo'yicha yuklarni o'qiydi.

    Xatoni YUTMAYDI — `run_reader_forever` supervisoriga ko'taradi.
    """
    global _client, _running

    try:
        from telethon import TelegramClient
    except ImportError:
        log.warning("telethon o'rnatilmagan — kanal o'quvchi ishlamaydi.")
        status.mark_error("telethon o'rnatilmagan")
        return

    channel_ids = settings.channel_ids_list
    if not channel_ids:
        log.info("CHANNEL_IDS sozlanmagan — kanal o'quvchi o'chirildi.")
        status.mark_error("CHANNEL_IDS sozlanmagan")
        return
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        log.warning("TELEGRAM_API_ID/HASH yo'q — kanal o'quvchi o'chirildi.")
        status.mark_error("TELEGRAM_API_ID/HASH yo'q")
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
            desc = "oddiy guruh (yo'nalish matndan)"
        else:
            desc = f"forum, {len(tm)} viloyat mavzusi"
        status.note_channel(cid, desc)
        log.info("Kanal %s — %s", cid, desc)

    status.mark_running()
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

    # --- Backfill (eskidan yangiga: logist oynasi xronologik to'g'ri sanalsin) ---
    for cid in channel_ids:
        regions = topic_maps[cid]
        max_id = 0
        try:
            async for m in _client.iter_messages(cid, limit=BACKFILL_LIMIT, reverse=True):
                if m.id > max_id:
                    max_id = m.id
                await _process_message(m.text or "", str(cid), regions, _topic_id_of(m), m.date)
        except Exception as exc:
            if is_fatal_auth_error(exc):
                raise
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
        status.mark_poll()
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
                for m in reversed(msgs):   # eskidan yangiga
                    if m.id > last_ids.get(cid, 0):
                        last_ids[cid] = m.id
                    await _process_message(m.text or "", str(cid), regions, _topic_id_of(m), m.date)
            except Exception as exc:
                # Sessiya bekor bo'lsa — jim yutmaymiz, supervisor ko'radi.
                if is_fatal_auth_error(exc):
                    raise
                log.error("Polling xato [%s]: %s", cid, exc)


async def stop_reader() -> None:
    """Telethon clientni to'xtatadi."""
    global _running
    _running = False
    if _client is not None:
        await _safe_disconnect()
        status.mark_stopped()
        log.info("Telethon kanal o'quvchi to'xtatildi.")
