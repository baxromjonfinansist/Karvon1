from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services.load_service import get_driver_deals, get_feed, get_load_detail, take_load
from bot.services.rating_service import (
    get_deal_for_rating,
    get_pending_ratings,
    has_rated,
    submit_rating,
)
from bot.services.user_service import get_active_subscription, get_or_none, is_subscribed
from bot.states import RatingFlow
from db.models import LoadStatus, User, UserRole

router = Router(name="driver")

_DRIVER_ROLES = {UserRole.driver, UserRole.asset_owner, UserRole.staff_driver}

_DEAL_STATUS = {
    "active": "🟡 Aktiv",
    "completed": "✅ Yakunlandi",
    "cancelled": "❌ Bekor",
}


def _fmt_price(price) -> str:
    if price is None:
        return "Kelishiladi"
    return f"{int(price):,}".replace(",", " ") + " so'm"


def _fmt_load(load) -> str:
    route = (
        f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    )
    risk_map = {"premium_safe": "🟢", "standard": "🟡", "budget": "🔴"}
    risk = risk_map.get(load.risk_tier.value, "🟡") if load.risk_tier else "🟡"
    weight = f"{load.weight_t} t" if load.weight_t else "—"
    return (
        f"📦 <b>#{load.id} — {route}</b>\n"
        f"Yuk: {load.cargo_type or '—'} | {weight}\n"
        f"Narx: {_fmt_price(load.price)}\n"
        f"Risk: {risk}"
    )


def _take_kb(load_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Olish", callback_data=f"take_{load_id}")]
        ]
    )


# ---------------------------------------------------------------------------
# 📦 Yuklar — feed
# ---------------------------------------------------------------------------

@router.message(F.text == "📦 Yuklar")
async def show_feed(message: Message, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not user or user.role not in _DRIVER_ROLES:
        await message.answer("Bu bo'lim faqat haydovchilar uchun.")
        return

    if not await is_subscribed(session, user):
        await message.answer(
            "❌ Obuna faol emas.\n\n"
            "/subscribe buyrug'ini yuboring yoki admin bilan bog'laning."
        )
        return

    loads = await get_feed(session, user)
    if not loads:
        await message.answer("Hozircha yuklar yo'q 🤷\n\nKeyinroq tekshiring.")
        return

    await message.answer(f"📋 <b>{len(loads)} ta yuk topildi:</b>")
    for load in loads:
        await message.answer(_fmt_load(load), reply_markup=_take_kb(load.id))


# ---------------------------------------------------------------------------
# 🤝 Olish — callback
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("take_"))
async def take_load_cb(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    load_id = int(callback.data.split("_")[1])

    user = await get_or_none(session, callback.from_user.id)
    if not user or user.role not in _DRIVER_ROLES:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    if not await is_subscribed(session, user):
        await callback.answer("❌ Obuna faol emas.", show_alert=True)
        return

    load = await get_load_detail(session, load_id)
    if not load:
        await callback.answer("Yuk topilmadi.", show_alert=True)
        return

    # Atomar band qilish — race condition'dan himoya
    deal = await take_load(session, load, user)
    if deal is None:
        await session.rollback()
        await callback.answer("❌ Bu yuk allaqachon band qilingan.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    await session.commit()

    route = (
        f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    )
    price_text = _fmt_price(deal.agreed_price)
    await callback.message.edit_text(
        f"✅ <b>Yuk olindi!</b>\n\n"
        f"Yo'nalish: {route}\n"
        f"Narx: {price_text}\n"
        f"Bitim #{deal.id} yaratildi."
    )
    await callback.answer("Muvaffaqiyatli!")

    # Provider'ga xabar berish
    if load.provider and load.provider.telegram_id:
        try:
            await bot.send_message(
                load.provider.telegram_id,
                f"🟢 <b>Yukingiz #{load.id} olindi!</b>\n\n"
                f"Yo'nalish: {route}\n"
                f"Narx: {price_text}\n"
                f"Haydovchi: {user.full_name}"
                + (f" ({user.phone})" if user.phone else ""),
            )
        except TelegramAPIError:
            pass


# ---------------------------------------------------------------------------
# 📋 Bitimlarim
# ---------------------------------------------------------------------------

@router.message(F.text == "📋 Bitimlarim")
async def show_deals(message: Message, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not user or user.role not in _DRIVER_ROLES:
        await message.answer("Bu bo'lim faqat haydovchilar uchun.")
        return

    deals = await get_driver_deals(session, user)
    if not deals:
        await message.answer("Hali bitim yo'q.\n\n📦 Yuklar bo'limidan yuk oling.")
        return

    pending = await get_pending_ratings(session, user)
    pending_ids = {d.id for d in pending}

    await message.answer(f"📋 <b>Sizning bitimlaringiz ({len(deals)} ta):</b>")
    for deal in deals:
        route = "—"
        if deal.load and deal.load.route:
            route = f"{deal.load.route.origin} → {deal.load.route.destination}"
        date = deal.created_at.strftime("%d.%m.%Y") if deal.created_at else "—"
        status = _DEAL_STATUS.get(deal.status.value, deal.status.value)

        kb = None
        if deal.id in pending_ids:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="⭐ Reyting berish",
                    callback_data=f"rate_deal_{deal.id}",
                )
            ]])

        await message.answer(
            f"🤝 <b>Bitim #{deal.id}</b>\n"
            f"Yo'nalish: {route}\n"
            f"Narx: {_fmt_price(deal.agreed_price)}\n"
            f"Holat: {status}\n"
            f"Sana: {date}",
            reply_markup=kb,
        )


# ---------------------------------------------------------------------------
# 💳 Obunam
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ⭐ Reyting berish — driver tomonidan
# ---------------------------------------------------------------------------

def _score_kb(deal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"⭐{i}", callback_data=f"score_{deal_id}_{i}")
            for i in range(1, 6)
        ]]
    )


@router.callback_query(F.data.startswith("rate_deal_"))
async def rate_deal_cb(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    deal_id = int(callback.data.split("_")[2])
    user = await get_or_none(session, callback.from_user.id)
    if not user:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    if await has_rated(session, user.id, deal_id):
        await callback.answer(
            "Siz bu bitim uchun allaqachon reyting qoldirgansiz.",
            show_alert=True,
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    await state.set_state(RatingFlow.waiting_score)
    await callback.message.answer(
        "⭐ <b>Reyting bering</b> (1 dan 5 gacha):", reply_markup=_score_kb(deal_id)
    )
    await callback.answer()


@router.callback_query(RatingFlow.waiting_score, F.data.startswith("score_"))
async def score_cb(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    parts = callback.data.split("_")
    deal_id = int(parts[1])
    score = int(parts[2])

    user = await get_or_none(session, callback.from_user.id)
    if not user:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    deal = await get_deal_for_rating(session, deal_id)
    if not deal:
        await callback.answer("Bitim topilmadi.", show_alert=True)
        return

    # Kim baholayapti, kimni baholayapti?
    to_user_id: int | None = None
    if deal.driver_id == user.id:
        to_user_id = deal.load.provider_id if deal.load else None
    elif deal.load and deal.load.provider_id == user.id:
        to_user_id = deal.driver_id

    if to_user_id is None:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    await state.update_data(deal_id=deal_id, score=score, to_user_id=to_user_id)
    await state.set_state(RatingFlow.waiting_comment)

    stars = "⭐" * score
    await callback.message.edit_text(f"Siz {stars} ({score}/5) berdingiz.")
    await callback.message.answer(
        "💬 Izoh qoldiring (ixtiyoriy).\n\n"
        "/skip — izohsiz o'tkazib yuborish."
    )
    await callback.answer()


@router.message(RatingFlow.waiting_comment)
async def rating_comment(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    comment_text = (message.text or "").strip()
    comment = None if comment_text == "/skip" else (comment_text or None)

    user = await get_or_none(session, message.from_user.id)
    if not user:
        await message.answer("Foydalanuvchi topilmadi.")
        await state.clear()
        return

    data = await state.get_data()
    try:
        await submit_rating(
            session,
            from_user=user,
            to_user_id=data["to_user_id"],
            deal_id=data["deal_id"],
            score=data["score"],
            comment=comment,
        )
        await session.commit()
    except ValueError as e:
        await message.answer(str(e))
        await state.clear()
        return

    await state.clear()

    # Ko'rsatish uchun yangilangan reyting
    to_user = (
        await session.execute(select(User).where(User.id == data["to_user_id"]))
    ).scalar_one_or_none()
    rating_str = f"{to_user.rating:.1f}" if to_user and to_user.rating else "—"

    await message.answer(
        f"✅ <b>Rahmat! Reytingiz qabul qilindi.</b>\n\n"
        f"Baholangan foydalanuvchi reytingi: ⭐ {rating_str}"
    )


# ---------------------------------------------------------------------------
# 💳 Obunam
# ---------------------------------------------------------------------------

@router.message(F.text == "💳 Obunam")
async def show_subscription(message: Message, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not user:
        await message.answer("Avval /start buyrug'ini yuboring.")
        return

    if await is_subscribed(session, user):
        sub = await get_active_subscription(session, user)
        end_text = sub.end_date.strftime("%d.%m.%Y") if sub else "—"
        plan = sub.plan.value.title() if sub else "—"
        await message.answer(
            f"✅ <b>Obuna faol</b>\n\n"
            f"Reja: {plan}\n"
            f"Muddati tugashi: {end_text}"
        )
    else:
        await message.answer(
            "❌ <b>Obuna yo'q</b>\n\n"
            "Obuna narxlari:\n"
            "• Basic — 150 000 so'm/oy\n"
            "• Premium — 300 000 so'm/oy\n\n"
            "To'lov tizimi tez orada ulanadi.\n"
            "Admin bilan bog'laning: @admin_username"
        )
