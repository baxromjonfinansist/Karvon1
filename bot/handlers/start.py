from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Contact, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import (
    confirm_kb,
    main_menu_driver_kb,
    main_menu_provider_kb,
    phone_request_kb,
    remove_kb,
    role_choice_kb,
    routes_kb,
    vehicle_type_kb,
)
from bot.services.user_service import (
    create_user,
    get_all_routes,
    get_or_none,
    set_preferred_routes,
)
from bot.states import DriverReg, ProviderReg
from db.models import UserRole, VehicleType

router = Router(name="start")

ROLE_MAP = {
    "🚛 Haydovchi": UserRole.driver,
    "📦 Yuk beruvchi": UserRole.cargo_provider,
    "🏭 Asset egasi": UserRole.asset_owner,
}

VEHICLE_TYPE_MAP = {
    "Isuzu": VehicleType.isuzu,
    "Fura": VehicleType.fura,
    "Boshqa": VehicleType.other,
}


def _normalize_phone(raw: str) -> str | None:
    """O'zbekiston raqamini tekshirib normallashtiradi.

    Qabul qilinadi: +998901234567, 998901234567, 901234567 (9 ta raqam).
    Qaytaradi: +998XXXXXXXXX yoki None (noto'g'ri bo'lsa).
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 9:  # operator+raqam, 998 siz kiritilgan
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    return None


async def _send_main_menu(message: Message, role: UserRole) -> None:
    if role == UserRole.cargo_provider:
        await message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_provider_kb(),
        )
    else:
        await message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_driver_kb(),
        )


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@router.message(CommandStart(), StateFilter(None))
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_or_none(session, message.from_user.id)
    if user:
        await _send_main_menu(message, user.role)
        return

    await message.answer(
        "Yuk Logistika Marketplace-ga xush kelibsiz!\n\n"
        "Ro'lni tanlang:",
        reply_markup=role_choice_kb(),
    )


# ---------------------------------------------------------------------------
# Rol tanlash
# ---------------------------------------------------------------------------

@router.message(F.text.in_(ROLE_MAP.keys()), StateFilter(None))
async def role_chosen(message: Message, state: FSMContext) -> None:
    role = ROLE_MAP[message.text]
    await state.update_data(role=role.value)

    if role == UserRole.cargo_provider:
        await state.set_state(ProviderReg.waiting_name)
    else:
        await state.set_state(DriverReg.waiting_name)

    await message.answer(
        "Ismingiz va familiyangizni kiriting\n(masalan: Alisher Qodirov):",
        reply_markup=remove_kb(),
    )


# ---------------------------------------------------------------------------
# DriverReg oqimi
# ---------------------------------------------------------------------------

@router.message(DriverReg.waiting_name)
async def driver_name(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Iltimos, to'liq ism kiriting (kamida 3 harf).")
        return

    await state.update_data(full_name=message.text.strip())
    await state.set_state(DriverReg.waiting_phone)
    await message.answer(
        "Telefon raqamingizni yuboring:",
        reply_markup=phone_request_kb(),
    )


@router.message(DriverReg.waiting_phone, F.contact)
async def driver_phone_contact(message: Message, state: FSMContext) -> None:
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await state.set_state(DriverReg.waiting_vehicle_type)
    await message.answer(
        "Mashina turini tanlang:",
        reply_markup=vehicle_type_kb(),
    )


@router.message(DriverReg.waiting_phone, F.text)
async def driver_phone_text(message: Message, state: FSMContext) -> None:
    phone = _normalize_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Noto'g'ri format. Raqamni +998XXXXXXXXX shaklida kiriting yoki "
            "«📱 Raqamni yuborish» tugmasini bosing."
        )
        return

    await state.update_data(phone=phone)
    await state.set_state(DriverReg.waiting_vehicle_type)
    await message.answer(
        "Mashina turini tanlang:",
        reply_markup=vehicle_type_kb(),
    )


@router.message(DriverReg.waiting_vehicle_type, F.text == "⬅️ Orqaga")
async def driver_vehicle_back(message: Message, state: FSMContext) -> None:
    await state.set_state(DriverReg.waiting_phone)
    await message.answer(
        "Telefon raqamingizni yuboring:",
        reply_markup=phone_request_kb(),
    )


@router.message(DriverReg.waiting_vehicle_type, F.text.in_(VEHICLE_TYPE_MAP.keys()))
async def driver_vehicle_type(message: Message, state: FSMContext) -> None:
    await state.update_data(vehicle_type=message.text)
    await state.set_state(DriverReg.waiting_capacity)
    await message.answer(
        "Mashina yuk ko'tarish quvvatini kiriting (tonnada, masalan: 5 yoki 1.5):",
        reply_markup=remove_kb(),
    )


@router.message(DriverReg.waiting_vehicle_type)
async def driver_vehicle_type_invalid(message: Message) -> None:
    await message.answer("Iltimos, tugmalardan birini tanlang.")


@router.message(DriverReg.waiting_capacity)
async def driver_capacity(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        capacity = float(message.text.replace(",", "."))
        if capacity <= 0 or capacity > 100:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("Noto'g'ri qiymat. 0 dan 100 gacha son kiriting (masalan: 5 yoki 1.5).")
        return

    await state.update_data(capacity_t=capacity)

    routes = await get_all_routes(session)
    await state.update_data(selected_routes=[])
    await state.set_state(DriverReg.waiting_routes)
    await message.answer(
        "Siz ishlashni afzal ko'rgan yo'nalishlarni tanlang.\n"
        "Bir nechta tanlashingiz mumkin, tugagach «✅ Tayyor» bosing:",
        reply_markup=routes_kb(routes, []),
    )


@router.callback_query(DriverReg.waiting_routes, F.data.startswith("route_"))
async def driver_route_toggle(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    route_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    selected: list[int] = data.get("selected_routes", [])

    if route_id in selected:
        selected.remove(route_id)
    else:
        selected.append(route_id)

    await state.update_data(selected_routes=selected)

    routes = await get_all_routes(session)
    await callback.message.edit_reply_markup(reply_markup=routes_kb(routes, selected))
    await callback.answer()


@router.callback_query(DriverReg.waiting_routes, F.data == "routes_done")
async def driver_routes_done(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()

    user = await create_user(
        session,
        telegram_id=callback.from_user.id,
        role=UserRole(data["role"]),
        full_name=data["full_name"],
        phone=data.get("phone"),
    )

    selected_routes = data.get("selected_routes", [])
    if selected_routes:
        await set_preferred_routes(session, user, selected_routes)

    await session.commit()
    await state.clear()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: {user.full_name}\n"
        f"Rol: Haydovchi\n"
        f"Tanlangan yo'nalishlar: {len(selected_routes)} ta\n\n"
        f"Asosiy menyu:",
        reply_markup=main_menu_driver_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# ProviderReg oqimi
# ---------------------------------------------------------------------------

@router.message(ProviderReg.waiting_name)
async def provider_name(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Iltimos, to'liq ism kiriting (kamida 3 harf).")
        return

    await state.update_data(full_name=message.text.strip())
    await state.set_state(ProviderReg.waiting_phone)
    await message.answer(
        "Telefon raqamingizni yuboring:",
        reply_markup=phone_request_kb(),
    )


@router.message(ProviderReg.waiting_phone, F.contact)
async def provider_phone_contact(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = message.contact.phone_number
    await _finish_provider_reg(message, state, session, phone)


@router.message(ProviderReg.waiting_phone, F.text)
async def provider_phone_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = _normalize_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Noto'g'ri format. Raqamni +998XXXXXXXXX shaklida kiriting yoki "
            "«📱 Raqamni yuborish» tugmasini bosing."
        )
        return
    await _finish_provider_reg(message, state, session, phone)


async def _finish_provider_reg(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    phone: str,
) -> None:
    data = await state.get_data()

    user = await create_user(
        session,
        telegram_id=message.from_user.id,
        role=UserRole(data["role"]),
        full_name=data["full_name"],
        phone=phone,
    )
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: {user.full_name}\n"
        f"Rol: Yuk beruvchi\n\n"
        f"Asosiy menyu:",
        reply_markup=main_menu_provider_kb(),
    )


# ---------------------------------------------------------------------------
# Kutilmagan xabarlar handler'i alohida router'ga ko'chirildi
# (bot/handlers/fallback.py) — u eng oxirida ro'yxatdan o'tishi kerak,
# aks holda menyu tugmalarini "yutib" yuboradi.
# ---------------------------------------------------------------------------
