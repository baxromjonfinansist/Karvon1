from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from bot.config import settings
from bot.services.load_service import _dest_region
from bot.services.parser_service import extract_body
from bot.services.user_service import is_subscribed
from db.database import AsyncSessionLocal
from db.models import Load, LoadStatus, Route, User, UserRole

log = logging.getLogger(__name__)

NOTIFY_INTERVAL = 600      # 10 daqiqada 1 marta
NOTIFY_MAX_PER_USER = 5    # bir haydovchiga bir sikldа maks. yuk
_LOOKBACK_MIN = 10         # last_notified_at bo'lmasa — shu oynadagi yuklar

# Kunlik eslatma (xabarnoma o'chiq haydovchilarga) — Toshkent vaqti bo'yicha.
TASHKENT_TZ = timezone(timedelta(hours=5))
REMINDER_HOURS = (8, 20)   # 08:30 (ertalab) va 20:30 (kechqurun)
REMINDER_MINUTE = 30
_DRIVER_ROLES = (UserRole.driver, UserRole.asset_owner, UserRole.staff_driver)

_running = False
_reminder_running = False


def _fmt(load: Load) -> str:
    """Yangi yuk xabarnomasi — shablon: yo'nalish, telefon, manba ma'lumoti."""
    route = f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    body = extract_body(load.raw_text or "", load.contact_phone) or load.note or load.cargo_type or "—"
    return (
        "🔔 <b>Yangi yuk!</b>\n"
        f"🚚 <b>{route}</b>\n"
        f"📞 {load.contact_phone or '—'}\n"
        f"📝 {escape(body)}"
    )


def _take_kb(load_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🤝 Olish", callback_data=f"take_{load_id}")
    ]])


async def _notify_driver(bot: Bot, session, user: User) -> None:
    """Bitta haydovchiga eng aktual yo'nalishi bo'yicha yangi yuklarni yuboradi.

    Yo'nalish ikki tomonlama: pref_origin↔pref_destination — yuk qaysi
    tomonga ketayotgan bo'lsa ham xabar boradi.
    """
    if not user.pref_origin or not user.pref_destination:
        return  # yo'nalish tanlanmagan — xabarnoma yubormaymiz

    cutoff = user.last_notified_at or (datetime.utcnow() - timedelta(minutes=_LOOKBACK_MIN))
    result = await session.execute(
        select(Load)
        .options(joinedload(Load.route))
        .join(Route, Load.route_id == Route.id)
        .where(
            Load.status == LoadStatus.open,
            Load.posted_at > cutoff,
            Route.origin.in_([user.pref_origin, user.pref_destination]),
        )
        .order_by(Load.posted_at.desc())
    )
    pair = {user.pref_origin, user.pref_destination}
    loads = [
        l for l in result.scalars().unique().all()
        if l.route and {l.route.origin, _dest_region(l.route.destination)} == pair
    ][:NOTIFY_MAX_PER_USER]

    # Oynani doim oldinga suramiz (yuk bo'lmasa ham) — keyingi sikldа dublikat bo'lmaydi.
    user.last_notified_at = datetime.utcnow()
    if not loads:
        return

    for load in reversed(loads):  # eng eskisidan yangisiga
        try:
            await bot.send_message(user.telegram_id, _fmt(load), reply_markup=_take_kb(load.id))
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)


async def _run_once(bot: Bot) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.notify_enabled.is_(True))
        )
        drivers = list(result.scalars().all())
        for user in drivers:
            if not settings.FREE_MODE and not await is_subscribed(session, user):
                continue
            try:
                await _notify_driver(bot, session, user)
            except Exception as exc:  # noqa: BLE001
                log.error("Xabarnoma xato [user=%s]: %s", user.telegram_id, exc)
        await session.commit()


async def notify_loop(bot: Bot) -> None:
    """Har 10 daqiqada opt-in haydovchilarga yo'nalishi bo'yicha yangi yuk yuboradi."""
    global _running
    _running = True
    log.info("Xabarnoma xizmati ishga tushdi (har %ss).", NOTIFY_INTERVAL)
    while _running:
        await asyncio.sleep(NOTIFY_INTERVAL)
        try:
            await _run_once(bot)
        except Exception as exc:  # noqa: BLE001
            log.error("Xabarnoma sikl xatosi: %s", exc)


def stop_notify() -> None:
    global _running
    _running = False


# ---------------------------------------------------------------------------
# Kunlik eslatma — xabarnoma o'chiq haydovchilarga (08:30 va 20:30, Toshkent)
# ---------------------------------------------------------------------------

def _reminder_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔔 Xabarnomani yoqish", callback_data="remind_enable")
    ]])


_REMINDER_TEXT = (
    "🔔 <b>Xabarnomani yoqib qo'ying</b>\n\n"
    "Hozir xabarnomangiz <b>o'chiq</b>. Yoqib qo'ysangiz:\n"
    "• O'z yo'nalishingizga mos yangi yuklar <b>avtomatik</b> keladi\n"
    "• Qo'lda qidirib o'tirishga hojat qolmaydi\n"
    "• Yuklarni <b>birinchilardan</b> bo'lib ko'rasiz — tezroq olasiz\n\n"
    "✅ <b>Qanday yoqiladi:</b>\n"
    "1️⃣ Pastdagi «🔔 Xabarnomani yoqish» tugmasini bosing, YOKI\n"
    "2️⃣ Menyudan ⚙️ <b>Sozlamalar</b> → «🔔 Xabarnomani yoqish» tugmasini bosing.\n\n"
    "Bir marta bosing 👇"
)


def _next_reminder_dt(now: datetime) -> datetime:
    """Keyingi eslatma vaqti (08:30 yoki 20:30, Toshkent) — hozirdan keyingisi."""
    candidates = []
    for h in REMINDER_HOURS:
        c = now.replace(hour=h, minute=REMINDER_MINUTE, second=0, microsecond=0)
        if c <= now:
            c += timedelta(days=1)
        candidates.append(c)
    return min(candidates)


async def _send_reminders(bot: Bot) -> None:
    """Xabarnoma o'chiq (notify_enabled=False) haydovchilarga tavsiya yuboradi."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(
                User.role.in_(_DRIVER_ROLES),
                User.notify_enabled.is_(False),
            )
        )
        users = list(result.scalars().all())
    sent = 0
    for user in users:
        try:
            await bot.send_message(
                user.telegram_id, _REMINDER_TEXT, reply_markup=_reminder_kb()
            )
            sent += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    log.info("Kunlik eslatma yuborildi: %d haydovchi (xabarnoma o'chiq).", sent)


async def reminder_loop(bot: Bot) -> None:
    """Har kuni 08:30 va 20:30 (Toshkent) da xabarnoma o'chiq haydovchilarga eslatma."""
    global _reminder_running
    _reminder_running = True
    log.info("Kunlik eslatma xizmati ishga tushdi (08:30 va 20:30, Toshkent).")
    while _reminder_running:
        now = datetime.now(TASHKENT_TZ)
        nxt = _next_reminder_dt(now)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        if not _reminder_running:
            break
        try:
            await _send_reminders(bot)
        except Exception as exc:  # noqa: BLE001
            log.error("Kunlik eslatma xatosi: %s", exc)


def stop_reminder() -> None:
    global _reminder_running
    _reminder_running = False
