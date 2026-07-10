from __future__ import annotations

from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.config import settings
from bot.services.load_service import get_driver_telegram_ids_for_route
from bot.services.logist_service import (
    add_logist_phone,
    list_logist_phones,
    remove_logist_phone,
)
from bot.services.user_service import (
    get_activity_dashboard,
    get_or_none,
    grant_subscription,
)
from db.models import (
    Deal, DealStatus, Load, LoadStatus,
    Subscription, SubscriptionPlan, SubscriptionStatus, User,
)

router = Router(name="admin")

_ROLE_LABELS = {
    "driver": "🚛 Haydovchi",
    "cargo_provider": "📦 Yuk beruvchi",
    "asset_owner": "🏭 Asset egasi",
    "staff_driver": "👤 Mashinasiz haydovchi",
    "admin": "👨‍💼 Admin",
}


def _is_admin(telegram_id: int) -> bool:
    return settings.ADMIN_ID is not None and telegram_id == settings.ADMIN_ID


def _admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Moderatsiya"), KeyboardButton(text="👥 Foydalanuvchilar")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📈 Dashboard")],
        ],
        resize_keyboard=True,
    )


def _approve_reject_kb(load_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tasdiq", callback_data=f"approve_{load_id}"),
            InlineKeyboardButton(text="❌ Rad", callback_data=f"reject_{load_id}"),
        ]]
    )


def _fmt_price(price) -> str:
    if price is None:
        return "—"
    return f"{int(price):,}".replace(",", " ") + " so'm"


# ---------------------------------------------------------------------------
# /admin
# ---------------------------------------------------------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(
            "❌ Sizda admin huquqi yo'q.\n\n"
            f"Sizning Telegram ID: <code>{message.from_user.id}</code>\n"
            "Agar siz admin bo'lishingiz kerak bo'lsa, ushbu ID'ni "
            "<code>.env</code> faylidagi <code>ADMIN_ID</code>'ga qo'shing."
        )
        return
    await message.answer(
        "👨‍💼 <b>Admin paneli</b>\n\nBo'limni tanlang:",
        reply_markup=_admin_menu_kb(),
    )


# ---------------------------------------------------------------------------
# 📋 Moderatsiya
# ---------------------------------------------------------------------------

@router.message(F.text == "📋 Moderatsiya")
async def moderation_queue(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    result = await session.execute(
        select(Load)
        .where(Load.status == LoadStatus.pending)
        .order_by(Load.posted_at.asc())
        .limit(20)
    )
    loads = list(result.scalars().all())

    if not loads:
        await message.answer("✅ Moderatsiya navbati bo'sh.")
        return

    await message.answer(f"📋 <b>Kutayotgan yuklar ({len(loads)} ta):</b>")
    for load in loads:
        price_text = _fmt_price(load.price)
        weight = f"{load.weight_t} t" if load.weight_t else "—"
        await message.answer(
            f"⏳ <b>Yuk #{load.id}</b>\n"
            f"Yuk turi: {load.cargo_type or '—'}\n"
            f"Vazn: {weight}\n"
            f"Narx: {price_text}\n"
            f"Kanal: {load.source_channel or '—'}",
            reply_markup=_approve_reject_kb(load.id),
        )


@router.callback_query(F.data.startswith("approve_"))
async def approve_load(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    load_id = int(callback.data.split("_")[1])
    result = await session.execute(
        select(Load).options(joinedload(Load.route)).where(Load.id == load_id)
    )
    load = result.scalar_one_or_none()

    if not load:
        await callback.answer("Yuk topilmadi.", show_alert=True)
        return

    load.status = LoadStatus.open
    route_id = load.route_id
    route_text = (
        f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    )
    price_text = _fmt_price(load.price)
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"✅ Yuk #{load_id} tasdiqlandi — status: open", show_alert=True)

    # Mos yo'nalishli haydovchilarga xabar
    driver_ids = await get_driver_telegram_ids_for_route(session, route_id)
    for tg_id in driver_ids:
        try:
            await bot.send_message(
                tg_id,
                f"🆕 <b>Yangi yuk!</b>\n\n"
                f"Yo'nalish: {route_text}\n"
                f"Yuk: {load.cargo_type or '—'}\n"
                f"Narx: {price_text}\n\n"
                f"«📦 Yuklar» bo'limidan ko'ring.",
            )
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("reject_"))
async def reject_load(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    load_id = int(callback.data.split("_")[1])
    result = await session.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()

    if not load:
        await callback.answer("Yuk topilmadi.", show_alert=True)
        return

    load.status = LoadStatus.cancelled
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"❌ Yuk #{load_id} rad etildi — status: cancelled", show_alert=True)


# ---------------------------------------------------------------------------
# /grant_sub — qo'lda obuna berish (Payme/Click integratsiyasigacha vaqtinchalik)
# Format: /grant_sub <telegram_id> <oy_soni> <plan>
#   plan: basic | premium
# ---------------------------------------------------------------------------

@router.message(Command("grant_sub"))
async def grant_sub(message: Message, session: AsyncSession, bot: Bot) -> None:
    if not _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer(
            "❌ Noto'g'ri format.\n\n"
            "<code>/grant_sub &lt;telegram_id&gt; &lt;oy_soni&gt; &lt;plan&gt;</code>\n\n"
            "Misol: <code>/grant_sub 6445652739 1 basic</code>\n"
            "Plan: <b>basic</b> yoki <b>premium</b>"
        )
        return

    _, tg_id_str, months_str, plan_str = parts

    try:
        target_tg_id = int(tg_id_str)
        months = int(months_str)
        if months <= 0 or months > 36:
            raise ValueError
    except ValueError:
        await message.answer("❌ telegram_id butun son, oy_soni 1–36 oralig'ida bo'lishi kerak.")
        return

    try:
        plan = SubscriptionPlan(plan_str.lower())
    except ValueError:
        await message.answer("❌ Plan faqat <b>basic</b> yoki <b>premium</b> bo'lishi mumkin.")
        return

    target = await get_or_none(session, target_tg_id)
    if not target:
        await message.answer(
            f"❌ Telegram ID <code>{target_tg_id}</code> bilan foydalanuvchi topilmadi.\n"
            "Avval u /start bilan ro'yxatdan o'tishi kerak."
        )
        return

    sub = await grant_subscription(session, target, months, plan)
    await session.commit()

    end_text = sub.end_date.strftime("%d.%m.%Y")
    await message.answer(
        f"✅ <b>Obuna berildi!</b>\n\n"
        f"Foydalanuvchi: {target.full_name}\n"
        f"Reja: {plan.value.title()}\n"
        f"Muddat: {months} oy\n"
        f"Tugashi: {end_text}"
    )

    # Foydalanuvchiga xabar
    try:
        await bot.send_message(
            target_tg_id,
            f"🎉 <b>Obunangiz faollashtirildi!</b>\n\n"
            f"Reja: {plan.value.title()}\n"
            f"Muddat: {months} oy\n"
            f"Tugashi: {end_text}\n\n"
            f"Endi «📦 Yuklar» bo'limidan yuklarni ko'rishingiz mumkin.",
        )
    except TelegramAPIError:
        pass


# ---------------------------------------------------------------------------
# /logist — qo'lda logist ro'yxati (bu raqamdan kelgan yuk bazaga tushmaydi)
#   /logist <raqam> [<raqam2> ...]   — qo'shish (bir nechta ham)
#   /logist_del <raqam>              — o'chirish
#   /logist_list                     — ro'yxat
# ---------------------------------------------------------------------------

@router.message(Command("logist"))
async def cmd_logist(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        phones = await list_logist_phones(session)
        await message.answer(
            f"📋 <b>Qo'lda-logist ro'yxati:</b> {len(phones)} ta raqam.\n\n"
            "➕ Qo'shish: <code>/logist +998901234567</code>\n"
            "   (bir nechta raqamni birga tashlash mumkin)\n"
            "➖ O'chirish: <code>/logist_del +998901234567</code>\n"
            "📄 Ro'yxat: /logist_list"
        )
        return

    tokens = parts[1].replace(",", " ").split()
    added, skipped = [], []
    for tok in tokens:
        phone = await add_logist_phone(session, tok)
        (added if phone else skipped).append(phone or tok)
    await session.commit()

    lines: list[str] = []
    if added:
        lines.append(f"✅ Logist ro'yxatiga qo'shildi ({len(added)} ta):")
        lines += [f"  • <code>{p}</code>" for p in added]
        lines.append("Bu raqamlardan kelgan yuklar endi hech qaysi kanaldan bazaga tushmaydi.")
    if skipped:
        lines.append(f"⚠️ Tushunilmadi: {', '.join(skipped[:5])}")
    await message.answer("\n".join(lines) or "Hech narsa qo'shilmadi.")


@router.message(Command("logist_del"))
async def cmd_logist_del(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Format: <code>/logist_del +998901234567</code>")
        return
    phone = await remove_logist_phone(session, parts[1].strip())
    await session.commit()
    if phone:
        await message.answer(f"✅ Ro'yxatdan o'chirildi: <code>{phone}</code>")
    else:
        await message.answer("❌ Raqamni tushunib bo'lmadi.")


@router.message(Command("logist_list"))
async def cmd_logist_list(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    phones = await list_logist_phones(session)
    if not phones:
        await message.answer("📋 Qo'lda-logist ro'yxati bo'sh.")
        return
    lines = [f"📋 <b>Qo'lda-logist ({len(phones)} ta):</b>"]
    for phone, note in phones[:100]:
        lines.append(f"• <code>{phone}</code>" + (f" — {note}" if note else ""))
    if len(phones) > 100:
        lines.append(f"… va yana {len(phones) - 100} ta.")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# 👥 Foydalanuvchilar
# ---------------------------------------------------------------------------

@router.message(F.text == "👥 Foydalanuvchilar")
async def users_by_role(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    rows = (
        await session.execute(
            select(User.role, func.count(User.id).label("cnt"))
            .group_by(User.role)
            .order_by(func.count(User.id).desc())
        )
    ).fetchall()

    total = sum(row[1] for row in rows)
    lines = [f"👥 <b>Foydalanuvchilar ({total} ta):</b>\n"]
    for row in rows:
        label = _ROLE_LABELS.get(row[0].value, row[0].value)
        lines.append(f"{label}: {row[1]} ta")

    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# 📊 Statistika
# ---------------------------------------------------------------------------

@router.message(F.text == "📊 Statistika")
async def statistics(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    total_users = (
        await session.execute(select(func.count(User.id)))
    ).scalar() or 0

    total_loads = (
        await session.execute(select(func.count(Load.id)))
    ).scalar() or 0

    status_rows = (
        await session.execute(
            select(Load.status, func.count(Load.id)).group_by(Load.status)
        )
    ).fetchall()
    by_status = {row[0]: row[1] for row in status_rows}

    active_deals = (
        await session.execute(
            select(func.count(Deal.id)).where(Deal.status == DealStatus.active)
        )
    ).scalar() or 0

    completed_deals = (
        await session.execute(
            select(func.count(Deal.id)).where(Deal.status == DealStatus.completed)
        )
    ).scalar() or 0

    gmv_raw = (
        await session.execute(
            select(func.sum(Deal.agreed_price)).where(Deal.status == DealStatus.completed)
        )
    ).scalar()
    gmv = Decimal(str(gmv_raw)) if gmv_raw else Decimal("0")

    active_subs = (
        await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.active
            )
        )
    ).scalar() or 0

    matched = by_status.get(LoadStatus.matched, 0)
    closed = by_status.get(LoadStatus.closed, 0)
    cancelled = by_status.get(LoadStatus.cancelled, 0)
    non_cancelled = total_loads - cancelled
    fill_rate = (matched + closed) / non_cancelled * 100 if non_cancelled else 0.0

    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"💳 Faol obunalar: {active_subs}\n\n"
        f"📦 <b>Yuklar:</b>\n"
        f"  Jami: {total_loads}\n"
        f"  ⏳ Kutmoqda: {by_status.get(LoadStatus.pending, 0)}\n"
        f"  🟡 Ochiq: {by_status.get(LoadStatus.open, 0)}\n"
        f"  🟢 Olingan: {matched}\n"
        f"  ✅ Yopilgan: {closed}\n"
        f"  ❌ Bekor: {cancelled}\n\n"
        f"🤝 <b>Bitimlar:</b>\n"
        f"  Faol: {active_deals}\n"
        f"  Yakunlangan: {completed_deals}\n\n"
        f"💰 GMV: {_fmt_price(gmv)}\n"
        f"📈 Fill rate: {fill_rate:.1f}%"
    )


# ---------------------------------------------------------------------------
# 📈 Dashboard — aktiv foydalanuvchilar statistikasi (DAU/WAU/MAU)
# ---------------------------------------------------------------------------

@router.message(F.text == "📈 Dashboard")
async def dashboard(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return

    d = await get_activity_dashboard(session)

    total = d["total_users"]
    def _pct(n: int) -> str:
        return f" ({n / total * 100:.0f}%)" if total else ""

    # Rol bo'yicha aktiv (hafta) — nomlangan
    role_lines = []
    for role_key, cnt in sorted(d["active_by_role"].items(), key=lambda x: -x[1]):
        role_lines.append(f"  {_ROLE_LABELS.get(role_key, role_key)}: {cnt}")
    role_text = "\n".join(role_lines) if role_lines else "  —"

    await message.answer(
        f"📈 <b>Dashboard — aktivlik</b>\n\n"
        f"🟢 <b>Aktiv foydalanuvchilar:</b>\n"
        f"  Bugun (DAU): {d['dau']}{_pct(d['dau'])}\n"
        f"  Bu hafta (WAU): {d['wau']}{_pct(d['wau'])}\n"
        f"  Bu oy (MAU): {d['mau']}{_pct(d['mau'])}\n\n"
        f"🚛 <b>Yuk qidirgan haydovchilar:</b>\n"
        f"  Bugun: {d['feed_day']}\n"
        f"  Bu hafta: {d['feed_week']}\n\n"
        f"🆕 <b>Yangi ro'yxatdan o'tganlar:</b>\n"
        f"  Bugun: {d['signup_day']}\n"
        f"  Bu hafta: {d['signup_week']}\n"
        f"  Bu oy: {d['signup_month']}\n\n"
        f"👤 <b>Bu hafta aktiv (rol bo'yicha):</b>\n"
        f"{role_text}\n\n"
        f"<i>Jami: {total} · aktivlik kuzatuvi boshlangan userlar: {d['ever_active']}</i>"
    )
