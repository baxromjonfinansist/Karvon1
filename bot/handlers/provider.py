from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import confirm_kb, main_menu_provider_kb, remove_kb
from bot.services.load_service import (
    cancel_load,
    create_load,
    get_or_create_route,
    get_provider_loads,
)
from bot.services.rating_service import complete_deal, get_active_deal_by_load
from bot.services.user_service import get_or_none
from bot.states import LoadPost, RatingFlow
from db.models import LoadStatus, UserRole

router = Router(name="provider")

_STATUS_EMOJI = {
    "pending": "⏳",
    "open": "🟡",
    "matched": "🟢",
    "closed": "✅",
    "cancelled": "❌",
}

_CARGO_TYPES = ["Qurilish", "Oziq-ovqat", "Elektronika", "Kimyo", "Boshqa"]


def _cargo_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=f"cargo_{t}")]
            for t in _CARGO_TYPES
        ]
    )


def _fmt_price(price) -> str:
    if price is None:
        return "—"
    return f"{int(price):,}".replace(",", " ") + " so'm"


# ---------------------------------------------------------------------------
# ➕ Yuk joylash — FSM boshlanishi
# ---------------------------------------------------------------------------

@router.message(F.text == "➕ Yuk joylash", StateFilter(None))
async def start_load_post(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not user or user.role != UserRole.cargo_provider:
        await message.answer("Bu bo'lim faqat yuk beruvchilar uchun.")
        return

    await state.set_state(LoadPost.waiting_origin)
    await message.answer(
        "📍 Jo'nab ketish shahrini kiriting:\n(masalan: Toshkent)",
        reply_markup=remove_kb(),
    )


@router.message(LoadPost.waiting_origin)
async def load_origin(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("Iltimos, shahar nomini to'g'ri kiriting.")
        return
    await state.update_data(origin=message.text.strip())
    await state.set_state(LoadPost.waiting_destination)
    await message.answer("📍 Yetib borish shahrini kiriting:\n(masalan: Samarqand)")


@router.message(LoadPost.waiting_destination)
async def load_destination(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("Iltimos, shahar nomini to'g'ri kiriting.")
        return

    data = await state.get_data()
    if message.text.strip().lower() == data["origin"].lower():
        await message.answer("Jo'nab ketish va yetib borish shahri bir xil bo'lishi mumkin emas.")
        return

    await state.update_data(destination=message.text.strip())
    await state.set_state(LoadPost.waiting_cargo_type)
    await message.answer("📦 Yuk turini tanlang:", reply_markup=_cargo_type_kb())


@router.message(LoadPost.waiting_cargo_type)
async def load_cargo_type_text(message: Message) -> None:
    await message.answer("Iltimos, yuqoridagi tugmalardan birini tanlang.")


@router.callback_query(LoadPost.waiting_cargo_type, F.data.startswith("cargo_"))
async def load_cargo_type(callback: CallbackQuery, state: FSMContext) -> None:
    cargo_type = callback.data[len("cargo_"):]
    await state.update_data(cargo_type=cargo_type)
    await state.set_state(LoadPost.waiting_weight)
    await callback.message.edit_text(f"Yuk turi tanlandi: <b>{cargo_type}</b>")
    await callback.message.answer(
        "⚖️ Yuk vaznini kiriting (tonnada, masalan: 5 yoki 1.5):"
    )
    await callback.answer()


@router.message(LoadPost.waiting_weight)
async def load_weight(message: Message, state: FSMContext) -> None:
    try:
        weight = float(message.text.replace(",", "."))
        if not (0 < weight <= 200):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        await message.answer("Noto'g'ri qiymat. 0 dan 200 gacha son kiriting (masalan: 5 yoki 1.5).")
        return

    await state.update_data(weight_t=weight)
    await state.set_state(LoadPost.waiting_price)
    await message.answer("💰 Narxni kiriting (so'mda, masalan: 500000):")


@router.message(LoadPost.waiting_price)
async def load_price(message: Message, state: FSMContext) -> None:
    try:
        price = float(message.text.replace(" ", "").replace(",", "."))
        if price <= 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        await message.answer("Noto'g'ri qiymat. Musbat son kiriting (masalan: 500000).")
        return

    await state.update_data(price=price)
    data = await state.get_data()

    await state.set_state(LoadPost.waiting_confirm)
    await message.answer(
        f"📋 <b>Yuk ma'lumotlari:</b>\n\n"
        f"📍 Jo'nab ketish: {data['origin']}\n"
        f"📍 Yetib borish: {data['destination']}\n"
        f"📦 Yuk turi: {data['cargo_type']}\n"
        f"⚖️ Vazn: {data['weight_t']} t\n"
        f"💰 Narx: {_fmt_price(price)}\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=confirm_kb(),
    )


@router.callback_query(LoadPost.waiting_confirm, F.data == "confirm_yes")
async def load_confirm_yes(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = await get_or_none(session, callback.from_user.id)
    if not user:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    data = await state.get_data()
    route = await get_or_create_route(session, data["origin"], data["destination"])
    load = await create_load(
        session,
        provider=user,
        route_id=route.id,
        cargo_type=data["cargo_type"],
        weight_t=data["weight_t"],
        price=data["price"],
    )
    await session.commit()
    await state.clear()

    await callback.message.edit_text(
        f"✅ <b>Yuk #{load.id} qabul qilindi!</b>\n\n"
        f"⏳ Hozir moderatsiyada. Admin tasdiqlagach haydovchilarga ko'rinadi.",
        reply_markup=None,
    )
    await callback.message.answer("Asosiy menyu:", reply_markup=main_menu_provider_kb())
    await callback.answer()


@router.callback_query(LoadPost.waiting_confirm, F.data == "confirm_no")
async def load_confirm_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.", reply_markup=None)
    await callback.message.answer("Asosiy menyu:", reply_markup=main_menu_provider_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# 📦 Mening yuklarim
# ---------------------------------------------------------------------------

@router.message(F.text == "📦 Mening yuklarim")
async def show_my_loads(message: Message, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not user or user.role != UserRole.cargo_provider:
        await message.answer("Bu bo'lim faqat yuk beruvchilar uchun.")
        return

    loads = await get_provider_loads(session, user)
    if not loads:
        await message.answer("Hali yuk yo'q.\n\n➕ Yuk joylash tugmasini bosing.")
        return

    await message.answer(f"📦 <b>Sizning yuklaringiz ({len(loads)} ta):</b>")
    for load in loads:
        route = (
            f"{load.route.origin} → {load.route.destination}" if load.route else "—"
        )
        emoji = _STATUS_EMOJI.get(load.status.value, "—")
        weight = f"{load.weight_t} t" if load.weight_t else "—"
        date = load.posted_at.strftime("%d.%m.%Y") if load.posted_at else "—"

        kb = None
        if load.status == LoadStatus.matched:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="✅ Yetkazildi",
                    callback_data=f"delivered_{load.id}",
                )
            ]])
        elif load.status in (LoadStatus.pending, LoadStatus.open):
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🗑 Bekor qilish",
                    callback_data=f"cancel_load_{load.id}",
                )
            ]])

        await message.answer(
            f"{emoji} <b>Yuk #{load.id}</b>\n"
            f"Yo'nalish: {route}\n"
            f"Yuk: {load.cargo_type or '—'} | {weight}\n"
            f"Narx: {_fmt_price(load.price)}\n"
            f"Sana: {date}",
            reply_markup=kb,
        )


# ---------------------------------------------------------------------------
# ✅ Yetkazildi — deal yopish va reyting
# ---------------------------------------------------------------------------

def _score_kb(deal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"⭐{i}", callback_data=f"score_{deal_id}_{i}")
            for i in range(1, 6)
        ]]
    )


@router.callback_query(F.data.startswith("delivered_"))
async def delivered_cb(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    load_id = int(callback.data.split("_")[1])

    user = await get_or_none(session, callback.from_user.id)
    if not user or user.role != UserRole.cargo_provider:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    deal = await get_active_deal_by_load(session, load_id)
    if not deal:
        await callback.answer(
            "Faol bitim topilmadi. Yuk allaqachon yopilgan bo'lishi mumkin.",
            show_alert=True,
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    driver_tg_id = deal.driver.telegram_id if deal.driver else None
    completed = await complete_deal(session, deal.id)
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ <b>Bitim #{completed.id} yopildi!</b>\n\n"
        f"Haydovchiga reyting bering:"
    )

    await state.set_state(RatingFlow.waiting_score)
    await callback.message.answer(
        "⭐ <b>Reyting bering</b> (1 dan 5 gacha):",
        reply_markup=_score_kb(completed.id),
    )
    await callback.answer("✅ Yetkazildi!")

    # Haydovchiga xabar — bitim yopildi, reyting berishi mumkin
    if driver_tg_id:
        try:
            await bot.send_message(
                driver_tg_id,
                f"✅ <b>Bitim #{completed.id} yopildi!</b>\n\n"
                f"Yuk yetkazib berildi. «📋 Bitimlarim» bo'limidan "
                f"yuk beruvchiga reyting qoldirishingiz mumkin.",
            )
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("cancel_load_"))
async def cancel_load_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    load_id = int(callback.data.split("_")[2])

    user = await get_or_none(session, callback.from_user.id)
    if not user or user.role != UserRole.cargo_provider:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    ok = await cancel_load(session, load_id, user.id)
    await session.commit()

    if not ok:
        await callback.answer(
            "Bekor qilib bo'lmadi. Yuk allaqachon haydovchi tomonidan olingan yoki yopilgan.",
            show_alert=True,
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"🗑 <b>Yuk #{load_id} bekor qilindi.</b>")
    await callback.answer("Bekor qilindi.")
