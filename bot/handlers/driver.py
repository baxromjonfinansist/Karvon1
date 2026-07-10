from __future__ import annotations

from datetime import datetime
from html import escape

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


from bot.config import settings
from bot.services.load_service import (
    delete_stale_loads,
    get_destination_regions,
    get_driver_deals,
    get_load_detail,
    get_origin_regions_with_open_loads,
    get_selection_loads,
    get_vehicle_counts_by_origin,
    take_load,
)
from bot.services.parser_service import extract_body
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
    """Shablon: 1-qator yo'nalish, 2-qator telefon, 3-qator manbadagi
    barcha ma'lumot (yo'nalish va telefondan tashqari)."""
    route = (
        f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    )
    phone = load.contact_phone or "—"
    body = extract_body(load.raw_text or "", load.contact_phone) or load.note or load.cargo_type or "—"
    return f"🚚 <b>{route}</b>\n📞 {phone}\n📝 {escape(body)}"


def _take_kb(load_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Olish", callback_data=f"take_{load_id}")]
        ]
    )


def _take_confirm_kb(load_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, olaman", callback_data=f"takeyes_{load_id}"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data=f"takeno_{load_id}"),
        ]]
    )


def _regions_menu_kb(regions_with_counts) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{origin} ({count})",
            callback_data=f"region_{origin}",
        )]
        for origin, count in regions_with_counts
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


_VEHICLE_LABELS = {"fura": "🚛 Fura", "isuzu": "🚚 Isuzu", "kichik": "🚐 Kichik (Porter/Labo)"}


def _vehicle_menu_kb(origin: str, vehicle_counts) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{_VEHICLE_LABELS.get(veh, veh)} ({count})",
            callback_data=f"veh|{origin}|{veh}",
        )]
        for veh, count in vehicle_counts
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _dest_menu_kb(origin: str, vehicle: str, dests_with_counts) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{region} ({count})",
            callback_data=f"dst|{origin}|{vehicle}|{region}",
        )]
        for region, count in dests_with_counts
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _pager_kb(
    origin: str, vehicle: str, region: str, offset: int, has_more: bool
) -> InlineKeyboardMarkup | None:
    row = []
    if offset > 0:
        row.append(InlineKeyboardButton(
            text="◀️ Oldingi", callback_data=f"more|{origin}|{vehicle}|{region}|{max(0, offset - 10)}"
        ))
    if has_more:
        row.append(InlineKeyboardButton(
            text="Keyingi ▶️", callback_data=f"more|{origin}|{vehicle}|{region}|{offset + 10}"
        ))
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def _check_driver(user) -> bool:
    return bool(user and user.role in _DRIVER_ROLES)


async def _send_selection(
    callback: CallbackQuery, session: AsyncSession,
    origin: str, vehicle: str, region: str, offset: int,
) -> None:
    """Chiqish viloyati+mashina turi+borish viloyati bo'yicha 10 ta yuk (eng yangisidan)."""
    loads, has_more = await get_selection_loads(
        session, origin, region, vehicle=vehicle, offset=offset, limit=10
    )
    if not loads:
        await callback.answer("Bu yo'nalishda boshqa yuk yo'q.", show_alert=True)
        return

    await callback.answer()
    label = _VEHICLE_LABELS.get(vehicle, vehicle)
    start, end = offset + 1, offset + len(loads)
    await callback.message.answer(
        f"📦 <b>{origin} → {region}</b> {label} ({start}–{end}-yuk, eng yangisidan):"
    )
    for load in loads:
        await callback.message.answer(_fmt_load(load), reply_markup=_take_kb(load.id))

    pager = _pager_kb(origin, vehicle, region, offset, has_more)
    if pager:
        tail = "Yana yuklar bor 👇" if has_more else "Boshqa yuk yo'q."
        await callback.message.answer(tail, reply_markup=pager)


async def _show_dest_menu(
    callback: CallbackQuery, session: AsyncSession, origin: str, vehicle: str
) -> None:
    """Mashina turi tanlangandan keyin — borish viloyati menyusi."""
    dests = await get_destination_regions(session, origin, vehicle=vehicle)
    if not dests:
        await callback.answer("Bu turda yuk qolmadi.", show_alert=True)
        return
    await callback.answer()
    label = _VEHICLE_LABELS.get(vehicle, vehicle)
    await callback.message.answer(
        f"📥 <b>{origin}</b> {label} — qayerga? Borish viloyatini tanlang:",
        reply_markup=_dest_menu_kb(origin, vehicle, dests),
    )


# ---------------------------------------------------------------------------
# 📦 Yuklar — feed: chiqish viloyati → borish viloyati → yuklar (sahifalangan)
# ---------------------------------------------------------------------------

@router.message(F.text == "📦 Yuklar")
async def show_feed(message: Message, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not _check_driver(user):
        await message.answer("Bu bo'lim faqat haydovchilar uchun.")
        return

    if not settings.FREE_MODE and not await is_subscribed(session, user):
        await message.answer(
            "❌ Obuna faol emas.\n\n"
            "/subscribe buyrug'ini yuboring yoki admin bilan bog'laning."
        )
        return

    # Dashboard uchun: yuk feed'ini haqiqatan ochgan haydovchini belgilaymiz.
    user.last_feed_view_at = datetime.utcnow()
    await session.commit()

    await delete_stale_loads(session)  # 10 daqiqadan eski yuklarni tozalaymiz

    regions = await get_origin_regions_with_open_loads(session)
    if not regions:
        await message.answer("Hozircha yuklar yo'q 🤷\n\nKeyinroq tekshiring.")
        return

    await message.answer(
        "📤 <b>Qayerdan?</b> Chiqish viloyatini tanlang:\n(qavs ichida — yuklar soni)",
        reply_markup=_regions_menu_kb(regions),
    )


@router.callback_query(F.data.startswith("region_"))
async def show_vehicle_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    origin = callback.data.split("_", 1)[1]

    user = await get_or_none(session, callback.from_user.id)
    if not _check_driver(user):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    if not settings.FREE_MODE and not await is_subscribed(session, user):
        await callback.answer("❌ Obuna faol emas.", show_alert=True)
        return

    await delete_stale_loads(session)

    vehicle_counts = await get_vehicle_counts_by_origin(session, origin)
    if not vehicle_counts:
        await callback.answer("Bu viloyatda yuk qolmadi.", show_alert=True)
        return

    # Bitta mashina turi bo'lsa — menyusiz to'g'ridan-to'g'ri borish viloyati.
    if len(vehicle_counts) == 1:
        await _show_dest_menu(callback, session, origin, vehicle_counts[0][0])
        return

    await callback.answer()
    await callback.message.answer(
        f"🚚 <b>{origin}</b> — mashina turini tanlang:",
        reply_markup=_vehicle_menu_kb(origin, vehicle_counts),
    )


@router.callback_query(F.data.startswith("veh|"))
async def show_destinations(callback: CallbackQuery, session: AsyncSession) -> None:
    _, origin, vehicle = callback.data.split("|", 2)

    user = await get_or_none(session, callback.from_user.id)
    if not _check_driver(user):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    if not settings.FREE_MODE and not await is_subscribed(session, user):
        await callback.answer("❌ Obuna faol emas.", show_alert=True)
        return

    await delete_stale_loads(session)
    await _show_dest_menu(callback, session, origin, vehicle)


@router.callback_query(F.data.startswith("dst|"))
async def show_dest_loads(callback: CallbackQuery, session: AsyncSession) -> None:
    _, origin, vehicle, region = callback.data.split("|", 3)

    user = await get_or_none(session, callback.from_user.id)
    if not _check_driver(user):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    if not settings.FREE_MODE and not await is_subscribed(session, user):
        await callback.answer("❌ Obuna faol emas.", show_alert=True)
        return

    await delete_stale_loads(session)
    await _send_selection(callback, session, origin, vehicle, region, offset=0)


@router.callback_query(F.data.startswith("more|"))
async def show_more_loads(callback: CallbackQuery, session: AsyncSession) -> None:
    _, origin, vehicle, region, offset = callback.data.split("|", 4)

    user = await get_or_none(session, callback.from_user.id)
    if not _check_driver(user):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    if not settings.FREE_MODE and not await is_subscribed(session, user):
        await callback.answer("❌ Obuna faol emas.", show_alert=True)
        return

    await _send_selection(callback, session, origin, vehicle, region, offset=int(offset))


# ---------------------------------------------------------------------------
# 🤝 Olish — 1-bosqich: tasdiq so'rash (yuk HALI band qilinmaydi)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("take_"))
async def take_load_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    load_id = int(callback.data.split("_")[1])

    user = await get_or_none(session, callback.from_user.id)
    if not user or user.role not in _DRIVER_ROLES:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    if not settings.FREE_MODE and not await is_subscribed(session, user):
        await callback.answer("❌ Obuna faol emas.", show_alert=True)
        return

    load = await get_load_detail(session, load_id)
    if not load:
        await callback.answer("Yuk topilmadi.", show_alert=True)
        return

    if load.status != LoadStatus.open:
        await callback.answer("❌ Bu yuk allaqachon band qilingan.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    # Tasdiq so'raymiz — adashib bosishdan himoya
    await callback.message.edit_text(
        f"{_fmt_load(load)}\n\n"
        f"❓ <b>Haqiqatan ham bu yukni olasizmi?</b>",
        reply_markup=_take_confirm_kb(load_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 🤝 Olish — 2-bosqich: tasdiqlandi → atomar band qilish
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("takeyes_"))
async def take_confirm_cb(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    load_id = int(callback.data.split("_")[1])

    user = await get_or_none(session, callback.from_user.id)
    if not user or user.role not in _DRIVER_ROLES:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    if not settings.FREE_MODE and not await is_subscribed(session, user):
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
        await callback.message.edit_text(
            f"{_fmt_load(load)}\n\n❌ <i>Afsus, bu yuk allaqachon band qilingan.</i>",
            reply_markup=None,
        )
        return

    await session.commit()

    route = (
        f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    )
    # Telefon o'chib qolmasligi uchun yuk matnini saqlaymiz, faqat "olindi" ikonka qo'shamiz.
    await callback.message.edit_text(
        f"{_fmt_load(load)}\n\n"
        f"✅ <b>Olindi</b> · Bitim #{deal.id}",
        reply_markup=None,
    )
    await callback.answer("Muvaffaqiyatli!")

    # Provider'ga xabar berish
    if load.provider and load.provider.telegram_id:
        try:
            await bot.send_message(
                load.provider.telegram_id,
                f"🟢 <b>Yukingiz #{load.id} olindi!</b>\n\n"
                f"Yo'nalish: {route}\n"
                f"Haydovchi: {user.full_name}"
                + (f" ({user.phone})" if user.phone else ""),
            )
        except TelegramAPIError:
            pass


# ---------------------------------------------------------------------------
# 🤝 Olish — bekor: tasdiqdan voz kechildi, yuk ochiq qoladi
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("takeno_"))
async def take_decline_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    load_id = int(callback.data.split("_")[1])

    load = await get_load_detail(session, load_id)
    if load and load.status == LoadStatus.open:
        # Asl ko'rinishni "Olish" tugmasi bilan tiklaymiz
        await callback.message.edit_text(_fmt_load(load), reply_markup=_take_kb(load_id))
    else:
        await callback.message.edit_text(
            "Bu yuk endi mavjud emas.", reply_markup=None
        )
    await callback.answer("Bekor qilindi.")


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
