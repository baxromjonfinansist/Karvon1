from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Contact,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import (
    confirm_kb,
    main_menu_driver_kb,
    main_menu_provider_kb,
    phone_request_kb,
    pref_viloyat_kb,
    remove_kb,
    role_choice_kb,
    vehicle_type_kb,
)
from bot.services.load_service import get_ranked_viloyats
from bot.services.user_service import (
    create_user,
    get_or_none,
    update_user_role,
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
    "Kichik (Porter/Labo)": VehicleType.kichik,
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

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    # /start har doim ishlashi kerak — hatto foydalanuvchi biror jarayonda
    # (masalan yo'nalish tanlashda) "qotib qolgan" bo'lsa ham qutqaradi.
    await state.clear()

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
    await state.set_state(DriverReg.waiting_pref_origin)

    viloyats = await get_ranked_viloyats(session)
    await message.answer(
        "📍 <b>Eng aktual yo'nalishingiz</b>\n\n"
        "Qaysi viloyatdan yuk olasiz? (eng ko'p yuk chiqadigan joylar yuqorida):",
        reply_markup=pref_viloyat_kb(viloyats, "prego"),
    )


@router.callback_query(DriverReg.waiting_pref_origin, F.data.startswith("prego_"))
async def driver_pref_origin(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    origin = callback.data.split("_", 1)[1]
    await state.update_data(pref_origin=origin)
    await state.set_state(DriverReg.waiting_pref_destination)

    viloyats = await get_ranked_viloyats(session, origin_filter=origin)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"📍 <b>{origin}</b>dan qayerga olib borasiz?\n"
        "(Ikkala yo'nalish bo'yicha ham xabarnoma keladi — masalan "
        f"{origin}→X va X→{origin}):",
        reply_markup=pref_viloyat_kb(viloyats, "predst"),
    )
    await callback.answer()


def _notify_ask_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔔 Ha, xabar bering", callback_data="notify_yes"),
        InlineKeyboardButton(text="🔕 Yo'q", callback_data="notify_no"),
    ]])


@router.callback_query(DriverReg.waiting_pref_destination, F.data.startswith("predst_"))
async def driver_pref_destination(callback: CallbackQuery, state: FSMContext) -> None:
    destination = callback.data.split("_", 1)[1]
    await state.update_data(pref_destination=destination)
    await state.set_state(DriverReg.waiting_notify)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "🔔 <b>Xabarnoma</b>\n\n"
        "Shu yo'nalishga yangi yuk kelsa, sizga avtomatik xabar yuboraylikmi? "
        "(Keyin ⚙️ Sozlamalarda o'zgartirishingiz mumkin)",
        reply_markup=_notify_ask_kb(),
    )
    await callback.answer()


@router.callback_query(DriverReg.waiting_notify, F.data.in_(["notify_yes", "notify_no"]))
async def driver_notify_choice(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    notify = callback.data == "notify_yes"
    data = await state.get_data()

    if data.get("reregister"):
        user = await get_or_none(session, callback.from_user.id)
        user = await update_user_role(
            session, user,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=data.get("phone"),
            notify_enabled=notify,
        )
    else:
        user = await create_user(
            session,
            telegram_id=callback.from_user.id,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=data.get("phone"),
            notify_enabled=notify,
        )

    user.pref_origin = data.get("pref_origin")
    user.pref_destination = data.get("pref_destination")

    await session.commit()
    await state.clear()

    notify_line = (
        "🔔 Xabarnoma yoqildi — yangi yuklar avtomatik keladi."
        if notify else
        "🔕 Xabarnoma o'chiq — ⚙️ Sozlamalardan yoqishingiz mumkin."
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: {user.full_name}\n"
        f"Rol: Haydovchi\n"
        f"Yo'nalish: {user.pref_origin} ↔ {user.pref_destination}\n"
        f"{notify_line}\n\n"
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

    if data.get("reregister"):
        user = await get_or_none(session, message.from_user.id)
        user = await update_user_role(
            session, user,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=phone,
        )
    else:
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
